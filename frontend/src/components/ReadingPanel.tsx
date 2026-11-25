import {useEffect, useState} from 'react';
import {api, type Region} from '../services/api';
import {renderMathHtml} from '../services/notes';
import {isKnowledgeReading, knowledgeReadingVersion, readingDate} from '../services/reading';
import {InlineRichText} from './MarkdownPreview';

type Config = {
  endpoint:string; model:string; key_env:string;
  configured?:boolean; knowledge_reading_enabled?:boolean; uses_default_model?:boolean;
  has_saved_key?:boolean; masked_key?:string|null; use_system_proxy?:boolean;
};
type Run = {id:string; parse_run_id:string; job_id:string; status:string; error:string|null; pipeline_version:string;
  report_status?:string; created_at?:number; checkpoint:{message?:string; stages?:Record<string,string>}|null};
type Evidence = {block_id:string; quote:string; matched:boolean; regions:Region[]};
type Claim = {id?:string; topic?:string; text:string; kind:string; verification:string; evidence:Evidence[];
  formulas?:{id:string; latex:string|null; recognition:string}[]};
type Report = {run:Run; warnings:string[]; paper_type?:string; failed_stages?:string[]; synthesis?:Record<string,string[]>;
  usage?:{calls:number; input_tokens:number; output_tokens:number; estimated_calls:number};
  sections:{section_key:string; title:string; summary:string; claims:Claim[]}[]};

const labels:Record<string,string> = {planner:'全局理解', prerequisite:'前置知识', method:'架构、算法与公式', experiment:'实验分析', synthesis:'综合结论'};
const statuses:Record<string,string> = {queued:'等待执行', running:'精读中', succeeded:'已生成', failed:'失败', cancelled:'已取消',
  completed:'已完成', completed_with_warnings:'已完成 · 有提示', partially_completed:'部分完成'};
const stages:Record<string,string> = {pending:'等待', running:'进行中', completed:'已完成', failed:'失败'};
const checks:Record<string,string> = {inferred:'推断', unsupported:'证据不足', conflicted:'存在冲突'};
const presets = [
  {label:'DeepSeek 官方', endpoint:'https://api.deepseek.com/chat/completions', model:'deepseek-chat'},
  {label:'DeepSeek Flash', endpoint:'https://api.deepseek.com/chat/completions', model:'deepseek-flash'},
  {label:'硅基流动 Qwen', endpoint:'https://api.siliconflow.cn/v1/chat/completions', model:'Qwen/Qwen2.5-72B-Instruct'},
  {label:'OpenAI 兼容', endpoint:'https://api.openai.com/v1/chat/completions', model:'gpt-4o-mini'},
  {label:'本地 Ollama', endpoint:'http://127.0.0.1:11434/v1/chat/completions', model:'qwen2.5:14b'},
];
const post = (data:unknown):RequestInit => ({method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});

export function ReadingPanel({parseId,fileId,onLocate,onNote,compact=false}:{parseId:string|null; fileId:string;
  onLocate:(r:Region[],label:string)=>void; onNote:(id:string)=>void; compact?:boolean}) {
  const [config,setConfig] = useState<Config>({endpoint:'',model:'',key_env:'',use_system_proxy:false});
  const [draft,setDraft] = useState<Config>({endpoint:'',model:'',key_env:'',use_system_proxy:false});
  const [apiKey,setApiKey] = useState(''), [testing,setTesting] = useState(false);
  const [edit,setEdit] = useState(false), [runs,setRuns] = useState<Run[]>([]), [selected,setSelected] = useState('');
  const [report,setReport] = useState<Report|null>(null), [error,setError] = useState(''), [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState(''), [savedNotes,setSavedNotes] = useState<Record<string,string>>({});

  useEffect(()=>{let live=true; void api<Config>('/v1/reading-settings').then(c=>{if(live){setConfig(c);setDraft(c)}})
    .catch(e=>{if(live)setError(e.message)}); return()=>{live=false}},[]);
  const enabled=config.knowledge_reading_enabled===true;
  const settingsLoaded=config.configured!==undefined;
  const active=runs.find(r=>r.status==='running'||r.status==='queued');

  useEffect(()=>{
    if(!parseId){setRuns([]);return}
    let live=true;
    void api<Run[]>(`/v1/parse-runs/${parseId}/reading-runs`).then(v=>{if(live)setRuns(v.filter(isKnowledgeReading))})
      .catch(e=>{if(live)setError((e as Error).message)});
    return()=>{live=false};
  },[parseId]);

  useEffect(()=>{
    if(!active||!parseId)return;
    const {id,job_id}=active;
    let live=true;
    const stream=new EventSource(`/api/jobs/${job_id}/events`);
    const onProgress=(event:MessageEvent<string>)=>{
      try{
        const checkpoint:Run['checkpoint']=JSON.parse(event.data);
        setRuns(rows=>rows.map(r=>r.id===id&&['queued','running'].includes(r.status)?{...r,checkpoint}:r));
      }catch{}
    };
    stream.addEventListener('progress',onProgress);
    for(const status of ['succeeded','failed','cancelled'])stream.addEventListener(status,()=>{
      stream.close();
      void api<Run>(`/v1/reading-runs/${id}`).then(run=>{if(live)setRuns(rows=>rows.map(r=>r.id===id?run:r))}).catch(()=>{});
    });
    const fallback=setInterval(()=>{
      void api<Run>(`/v1/reading-runs/${id}`).then(run=>{if(live)setRuns(rows=>rows.map(r=>r.id===id?run:r))}).catch(()=>{});
    },3000);
    return()=>{live=false;stream.close();clearInterval(fallback)};
  },[active?.job_id,parseId]);

  const row=runs.find(r=>r.id===selected)||runs[0];
  const runId=row?.id, runStatus=row?.status;
  useEffect(()=>{setReport(null);if(!runId||runStatus!=='succeeded')return;let live=true;
    void api<Report>(`/v1/reading-runs/${runId}/report`).then(value=>{if(live&&value.run.parse_run_id===parseId)setReport(value)})
      .catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[runId,runStatus,parseId]);

  async function action(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  function selectRun(run:Run){
    if(!isKnowledgeReading(run))throw new Error('当前服务没有返回综合精读任务。');
    setRuns(p=>[run,...p.filter(x=>x.id!==run.id)]);setSelected(run.id);
  }
  async function saveSettings(e:React.FormEvent){
    e.preventDefault();
    await action(async()=>{
      const payload:Record<string,unknown>={endpoint:draft.endpoint,model:draft.model,key_env:draft.key_env,use_system_proxy:!!draft.use_system_proxy};
      if(apiKey.trim())payload.api_key=apiKey.trim();
      const c=await api<Config>('/v1/reading-settings',post(payload));
      const next={...c,knowledge_reading_enabled:config.knowledge_reading_enabled,configured:true};
      setConfig(next);setDraft(next);setApiKey('');setEdit(false);
      setNotice(apiKey.trim()?'模型配置与 API 密钥已通过 Windows DPAPI 加密保存（立即生效，无需重启）':'模型配置已保存');
    });
  }
  async function clearSavedKey(){
    await action(async()=>{
      const c=await api<Config>('/v1/reading-settings',post({endpoint:draft.endpoint,model:draft.model,key_env:draft.key_env,use_system_proxy:!!draft.use_system_proxy,clear_api_key:true}));
      const next={...c,knowledge_reading_enabled:config.knowledge_reading_enabled,configured:true};
      setConfig(next);setDraft(next);setNotice('已清除本地加密保存的 API 密钥');
    });
  }
  async function testConnection(){
    setTesting(true);setError('');setNotice('');
    try{
      const res=await api<{ok:boolean;latency_ms:number;model:string}>('/v1/reading-settings/test',post({
        endpoint:draft.endpoint,model:draft.model,key_env:draft.key_env,
        api_key:apiKey.trim()||undefined,use_system_proxy:!!draft.use_system_proxy,
      }));
      setNotice(`连接成功 · 模型 ${res.model} · 响应耗时 ${res.latency_ms} ms`);
    }catch(e){setError((e as Error).message)}finally{setTesting(false)}
  }
  async function start(){await action(async()=>{selectRun(await api<Run>(`/v1/parse-runs/${parseId}/reading-runs`,
    post({force:row?.status==='succeeded',pipeline_version:knowledgeReadingVersion})))})}
  async function retry(run:Run){await action(async()=>{selectRun(await api<Run>(`/v1/reading-runs/${run.id}/retry-specialties`,post({})))})}
  async function cancel(run:Run){await action(async()=>{await api(`/jobs/${run.job_id}/cancel`,post({}));
    setRuns(p=>p.map(x=>x.id===run.id?{...x,status:'cancelled'}:x))})}
  async function copy(run:Run){await action(async()=>{const value=await api<{markdown:string}>(`/v1/reading-runs/${run.id}/markdown`);
    await navigator.clipboard.writeText(value.markdown);setNotice('已复制 Obsidian 兼容 Markdown 报告')})}
  async function saveNote(run:Run){await action(async()=>{
    if(savedNotes[run.id]){onNote(savedNotes[run.id]);return}
    const value=await api<{note_id:string}>(`/v1/notes`,post({paper_file_id:fileId,parse_run_id:run.parse_run_id,
      reading_run_id:run.id,operation_key:'paper-note-v1-'+run.id}));
    setSavedNotes(p=>({...p,[run.id]:value.note_id}));onNote(value.note_id);setNotice('已保存到知识笔记');
  })}
  const currentReport=report?.run.id===runId ? report : null;
  const specialties=['prerequisite','method','experiment'] as const;
  const specialtySections=new Map(currentReport?.sections.map(section=>[section.section_key,section]));
  const claimMap=new Map(currentReport?.sections.flatMap(s=>s.claims).filter(c=>c.id).map(c=>[c.id,c]));

  return <aside className="ai-reading-panel" aria-label="AI 深度精读">
    {!compact&&<h2>AI 深度精读</h2>}
    <p className="reading-disclosure">综合论文所需的前置知识、方法与公式、实验和局限。精读与问答共用此模型配置。</p>
    <div className="reading-actions">
      <button className="primary" disabled={!enabled||!parseId||!config.configured||busy||!!active} onClick={()=>void start()}>
        {currentReport?'重新生成综合精读':'开始综合精读'}</button>
      <button onClick={()=>{setDraft(config);setEdit(v=>!v)}} aria-expanded={edit}>{edit?'收起配置':'模型配置'}</button>
    </div>
    {settingsLoaded&&!enabled&&<p className="reading-caution">综合精读已暂停，暂时无法生成或重试。</p>}
    {!parseId&&<p>请先完成左侧论文结构解析。</p>}
    {!config.has_saved_key&&config.uses_default_model&&!edit&&<p className="reading-caution">尚未配置 API 密钥。点击上方「模型配置」可直接输入密钥并加密保存，无需重启软件。</p>}
    {edit&&<form className="reading-settings" onSubmit={saveSettings}>
      <label>快捷服务预设
        <select aria-label="模型预设" value="" onChange={e=>{const p=presets.find(x=>x.label===e.target.value);if(p)setDraft(d=>({...d,endpoint:p.endpoint,model:p.model}))}}>
          <option value="">选择常用服务自动填入…</option>
          {presets.map(p=><option key={p.label} value={p.label}>{p.label} ({p.model})</option>)}
        </select>
      </label>
      <label>完整生成端点<input type="url" required placeholder="https://api.deepseek.com/chat/completions" value={draft.endpoint} onChange={e=>setDraft(c=>({...c,endpoint:e.target.value}))}/></label>
      <label>模型名称<input required value={draft.model} onChange={e=>setDraft(c=>({...c,model:e.target.value}))}/></label>
      <label>API 密钥（Windows DPAPI 本机加密存储）
        <input type="password" autoComplete="off" placeholder={config.has_saved_key?`已保存密钥 (${config.masked_key})，留空保持不变`:'粘贴 sk-... 密钥，保存即生效'} value={apiKey} onChange={e=>setApiKey(e.target.value)}/>
      </label>
      <label className="checkbox-inline"><input type="checkbox" checked={!!draft.use_system_proxy} onChange={e=>setDraft(c=>({...c,use_system_proxy:e.target.checked}))}/> 跟随 Windows 系统代理（访问海外模型或 arXiv 时建议勾选）</label>
      <details><summary>高级：环境变量凭据名</summary>
        <label>环境变量名（可选）<input placeholder="PAPERMIND_MODEL_API_KEY" value={draft.key_env} onChange={e=>setDraft(c=>({...c,key_env:e.target.value}))}/></label>
      </details>
      <div className="reading-actions">
        <button type="submit" className="primary" disabled={busy||testing}>保存模型配置</button>
        <button type="button" disabled={busy||testing} onClick={()=>void testConnection()}>{testing?'测试中…':'测试连接'}</button>
        {config.has_saved_key&&<button type="button" disabled={busy||testing} onClick={()=>void clearSavedKey()}>清除密钥</button>}
      </div>
    </form>}
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status" className="notice">{notice}</p>}
    {active&&<div className="reading-progress"><p role="status">{statuses[active.status]} · {active.checkpoint?.message||'等待 Worker'}</p>
      {active.checkpoint?.stages&&<ol>{Object.entries(labels).map(([id,name])=><li key={id}>{name} · {stages[active.checkpoint!.stages![id]]||'等待'}</li>)}</ol>}
      <button disabled={busy} onClick={()=>void cancel(active)}>取消精读</button></div>}
    {runs.length>1&&<label>精读历史 <select aria-label="精读历史" value={runId} onChange={e=>setSelected(e.target.value)}>
      {runs.map((r,i)=><option key={r.id} value={r.id}>{statuses[r.report_status||r.status]} · {readingDate(r.created_at)||('报告 '+(runs.length-i))}</option>)}</select></label>}
    {row?.status==='cancelled'&&!active&&<p>精读已取消，可以重新开始。</p>}
    {row?.status==='failed'&&!active&&<div><p role="alert" className="error">{row.error||'精读失败'}</p><button disabled={busy||!enabled} onClick={()=>void retry(row)}>重试精读</button></div>}
    {currentReport&&<article className="reading-report" aria-label="精读报告">
      <h2>综合精读报告</h2>
      {currentReport.paper_type&&<p>{currentReport.paper_type} · {statuses[row?.report_status||'completed']}</p>}
      <nav className="reading-specialties" aria-label="精读专项导航">
        {specialties.map(id=><button type="button" key={id} onClick={e=>{
          const section=e.currentTarget.closest('article')?.querySelector<HTMLElement>(`[data-reading-specialty="${id}"]`);
          section?.scrollIntoView({block:'start'});
          section?.focus({preventScroll:true});
        }}>{labels[id]}{specialtySections.has(id)?'':'（未完成）'}</button>)}
      </nav>
      <div className="reading-actions">
        <button disabled={busy} onClick={()=>void copy(currentReport.run)}>复制 Markdown</button>
        <button className="primary" disabled={busy} onClick={()=>void saveNote(currentReport.run)}>{savedNotes[currentReport.run.id]?'打开知识笔记':'保存为知识笔记'}</button>
        {!!currentReport.failed_stages?.length&&!active&&<button disabled={busy||!enabled} onClick={()=>void retry(currentReport.run)}>重试未完成的专项</button>}
      </div>
      {(['overview','contributions','limitations','implementation','review_points'] as const).map((k,i)=>{const ids=currentReport.synthesis?.[k];return ids?.length?<section key={k}>
        <h3>{['综合要点','主要贡献','局限性','实现要点','复习要点'][i]}</h3><ul>{ids.map(id=>{const cl=claimMap.get(id);return cl?<li key={id}><InlineRichText text={cl.text}/>{cl.kind==='inference'?'（推断）':''}</li>:null})}</ul></section>:null})}
      {specialties.map(id=>specialtySections.get(id)??{section_key:id,title:labels[id],summary:null,claims:[]}).map(s=><section key={s.section_key} data-reading-specialty={s.section_key} tabIndex={-1}><h3>{s.title}</h3>{s.summary===null?<p>此专项未生成，可使用「重试未完成的专项」继续。</p>:<p className="reading-summary">导览（未核验）：<InlineRichText text={s.summary}/></p>}
        {s.claims.map((c,i)=><div className={'reading-claim '+c.verification} key={c.id||i}>
          {(c.topic||checks[c.verification])&&<small>{[c.topic,checks[c.verification]].filter(Boolean).join(' · ')}</small>}
          <p><InlineRichText text={c.text}/></p>
          {c.formulas?.map(f=>{const html=f.latex?renderMathHtml(f.latex,true):null;return <div key={f.id} className="claim-formula">{html?<div className="math-block" dangerouslySetInnerHTML={{__html:html}}/>:<code>{f.latex||'未完整识别'}</code>}<small>解析公式 · 需对照原文</small></div>})}
          {c.evidence.filter(e=>e.matched).map((e,n)=><button key={n} title={e.quote} onClick={()=>onLocate(e.regions,e.quote)}>查看原文{n>0?' '+(n+1):''}</button>)}
        </div>)}</section>)}
      <details open={!!currentReport.failed_stages?.length}><summary>阅读提示与用量</summary>
        {currentReport.warnings.map((w,n)=><p key={n}>{w}</p>)}
        {currentReport.usage&&<p>模型调用 {currentReport.usage.calls} 次 · 输入 {currentReport.usage.input_tokens} · 输出 {currentReport.usage.output_tokens} Token
          {currentReport.usage.estimated_calls>0?'（含估算）':''}</p>}</details>
    </article>}
  </aside>;
}
