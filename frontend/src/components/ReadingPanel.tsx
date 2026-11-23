import {useEffect, useState} from 'react';
import {api, type Region} from '../services/api';
import {isKnowledgeReading, knowledgeReadingVersion, readingDate} from '../services/reading';

type Config = {endpoint:string; model:string; key_env:string; configured?:boolean; knowledge_reading_enabled?:boolean; uses_default_model?:boolean};
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
const post = (data:unknown):RequestInit => ({method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});

export function ReadingPanel({parseId,fileId,onLocate,onNote,compact=false}:{parseId:string|null; fileId:string;
  onLocate:(r:Region[],label:string)=>void; onNote:(id:string)=>void; compact?:boolean}) {
  const [config,setConfig] = useState<Config>({endpoint:'',model:'',key_env:''});
  const [edit,setEdit] = useState(false), [runs,setRuns] = useState<Run[]>([]), [selected,setSelected] = useState('');
  const [report,setReport] = useState<Report|null>(null), [error,setError] = useState(''), [busy,setBusy] = useState(false);
  const [notice,setNotice] = useState(''), [savedNotes,setSavedNotes] = useState<Record<string,string>>({});
  useEffect(()=>{let live=true; void api<Config>('/v1/reading-settings').then(c=>{if(live)setConfig(c)})
    .catch(e=>{if(live)setError(e.message)}); return()=>{live=false}},[]);
  const enabled=config.knowledge_reading_enabled===true;
  const settingsLoaded=config.configured!==undefined;
  const active=runs.find(r=>r.status==='running'||r.status==='queued');
  useEffect(()=>{
    if(!parseId)return;
    let live=true,pending=false;
    const load=async()=>{if(pending)return; pending=true;
      try{const values=await api<Run[]>(`/v1/parse-runs/${parseId}/reading-runs`); if(live)setRuns(values.filter(isKnowledgeReading))}
      catch(e){if(live)setError((e as Error).message)}finally{pending=false}};
    void load();const timer=setInterval(()=>void load(),active?1300:5000);
    return()=>{live=false;clearInterval(timer)};
  },[parseId,active?.id]);
  useEffect(()=>{
    if(!active)return;
    const {id,job_id}=active;
    let live=true;
    const stream=new EventSource(`/api/jobs/${job_id}/events`);
    const onProgress=(event:MessageEvent<string>)=>{
      const checkpoint:Run['checkpoint']=JSON.parse(event.data);
      setRuns(rows=>rows.map(r=>r.id===id&&['queued','running'].includes(r.status)?{...r,checkpoint}:r));
    };
    stream.addEventListener('progress',onProgress);
    for(const status of ['succeeded','failed','cancelled'])stream.addEventListener(status,()=>{
      stream.close();
      void api<Run>(`/v1/reading-runs/${id}`).then(run=>{if(live)setRuns(rows=>rows.map(r=>r.id===id?run:r))}).catch(()=>{});
    });
    return()=>{live=false;stream.close()};
  },[active?.job_id]);
  const row=runs.find(r=>r.id===selected)||runs[0];
  const runId=row?.id, runStatus=row?.status;
  useEffect(()=>{setReport(null);if(!runId||runStatus!=='succeeded')return;let live=true;
    void api<Report>(`/v1/reading-runs/${runId}/report`).then(value=>{if(live&&value.run.parse_run_id===parseId)setReport(value)})
      .catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[runId,runStatus,parseId]);
  async function action(fn:()=>Promise<void>){setBusy(true);setError('');setNotice('');try{await fn()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  function selectRun(run:Run){
    if(!isKnowledgeReading(run))throw new Error('当前服务没有返回综合精读任务，请更新并重启 PaperMind 服务。');
    setRuns(p=>[run,...p.filter(x=>x.id!==run.id)]);setSelected(run.id)
  }
  async function settings(e:React.FormEvent){e.preventDefault();await action(async()=>{
    const c=await api<Config>('/v1/reading-settings',post({endpoint:config.endpoint,model:config.model,key_env:config.key_env}));
    setConfig({...c, knowledge_reading_enabled:config.knowledge_reading_enabled,configured:true});setEdit(false);
  })}
  async function start(){await action(async()=>{selectRun(await api<Run>(`/v1/parse-runs/${parseId}/reading-runs`,
    post({force:row?.status==='succeeded',pipeline_version:knowledgeReadingVersion})))})}
  async function retry(run:Run){await action(async()=>{
    selectRun(await api<Run>(`/v1/reading-runs/${run.id}/retry-specialties`,post({})));
  })}
  async function cancel(run:Run){await action(async()=>{await api(`/jobs/${run.job_id}/cancel`,post({}));
    setRuns(p=>p.map(x=>x.id===run.id?{...x,status:'cancelled'}:x))})}
  async function copy(run:Run){await action(async()=>{const value=await api<{markdown:string}>(`/v1/reading-runs/${run.id}/markdown`);
    await navigator.clipboard.writeText(value.markdown);setNotice('已复制 Markdown 报告')})}
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
    <p className="reading-disclosure">综合论文所需的前置知识、方法与公式、实验和局限。生成时会将必要的解析内容发送给你配置的模型服务。</p>
    <div className="reading-actions">
      <button className="primary" disabled={!enabled||!parseId||!config.configured||busy||!!active} onClick={()=>void start()}>
        {currentReport?'重新生成综合精读':'开始综合精读'}</button>
      <button onClick={()=>setEdit(v=>!v)} aria-expanded={edit}>{edit?'收起配置':'模型配置'}</button>
    </div>
    {settingsLoaded&&!enabled&&<p className="reading-caution">{config.knowledge_reading_enabled===false
      ?'综合精读已暂停，暂时无法生成或重试。'
      :'当前后端版本不支持综合精读，请更新并重启 PaperMind 服务。'}</p>}
    {!parseId&&<p>请先完成论文解析。</p>}{!config.configured&&!edit&&<p>首次使用，请先配置模型服务。</p>}
    {config.uses_default_model&&<p>已预设 DeepSeek Flash。首次使用请在项目的 <code>.env</code> 填入自己的 DeepSeek API 密钥，再重启 PaperMind；无需保存模型配置。</p>}
    {edit&&<form className="reading-settings" onSubmit={settings}>
      <label>完整生成端点<input type="url" required placeholder="https://服务地址/v1/chat/completions" value={config.endpoint} onChange={e=>setConfig(c=>({...c,endpoint:e.target.value}))}/></label>
      <label>模型名称<input required value={config.model} onChange={e=>setConfig(c=>({...c,model:e.target.value}))}/></label>
      <label>凭据环境变量名（可选）<input placeholder="PAPERMIND_MODEL_API_KEY" value={config.key_env} onChange={e=>setConfig(c=>({...c,key_env:e.target.value}))}/></label>
      <small>这里填写变量名。模型凭据从 Worker 的运行环境读取。</small><button disabled={busy}>保存模型配置</button>
    </form>}
    {error&&<p role="alert" className="error">{error}</p>}{notice&&<p role="status">{notice}</p>}
    {active&&<div className="reading-progress"><p role="status">{statuses[active.status]} · {active.checkpoint?.message||'等待 Worker'}</p>
      {active.checkpoint?.stages&&<ol>{Object.entries(labels).map(([id,name])=><li key={id}>{name} · {stages[active.checkpoint!.stages![id]]||'等待'}</li>)}</ol>}
      <button disabled={busy} onClick={()=>void cancel(active)}>取消精读</button></div>}
    {runs.length>1&&<label>精读历史 <select aria-label="精读历史" value={runId} onChange={e=>setSelected(e.target.value)}>
      {runs.map((r,i)=><option key={r.id} value={r.id}>{statuses[r.report_status||r.status]} · {readingDate(r.created_at)||('报告 '+(runs.length-i))}</option>)}</select></label>}
    {row?.status==='cancelled'&&!active&&<p>精读已取消，可以重新开始。</p>}
    {row?.status==='failed'&&!active&&<div><p role="alert">{row.error||'精读失败'}</p><button disabled={busy||!enabled} onClick={()=>void retry(row)}>重试精读</button></div>}
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
        <button disabled={busy} onClick={()=>void saveNote(currentReport.run)}>{savedNotes[currentReport.run.id]?'打开知识笔记':'保存为知识笔记'}</button>
        {!!currentReport.failed_stages?.length&&!active&&<button disabled={busy||!enabled} onClick={()=>void retry(currentReport.run)}>重试未完成的专项</button>}
      </div>
      {(['overview','contributions','limitations','implementation','review_points'] as const).map((k,i)=>{const ids=currentReport.synthesis?.[k];return ids?.length?<section key={k}>
        <h3>{['综合要点','主要贡献','局限性','实现要点','复习要点'][i]}</h3><ul>{ids.map(id=><li key={id}>{claimMap.get(id)?.text}{claimMap.get(id)?.kind==='inference'?'（推断）':''}</li>)}</ul></section>:null})}
      {specialties.map(id=>specialtySections.get(id)??{section_key:id,title:labels[id],summary:null,claims:[]}).map(s=><section key={s.section_key} data-reading-specialty={s.section_key} tabIndex={-1}><h3>{s.title}</h3>{s.summary===null?<p>此专项未生成，可使用「重试未完成的专项」继续。</p>:<p className="reading-summary">导览（未核验）：{s.summary}</p>}
        {s.claims.map((c,i)=><div className={'reading-claim '+c.verification} key={c.id||i}>
          {(c.topic||checks[c.verification])&&<small>{[c.topic,checks[c.verification]].filter(Boolean).join(' · ')}</small>}
          <p>{c.text}</p>
          {c.formulas?.map(f=><p key={f.id}><code>{f.latex||'未完整识别'}</code> <small>解析公式 · 需对照原文</small></p>)}
          {c.evidence.filter(e=>e.matched).map((e,n)=><button key={n} title={e.quote} onClick={()=>onLocate(e.regions,e.quote)}>查看原文{n>0?' '+(n+1):''}</button>)}
        </div>)}</section>)}
      <details open={!!currentReport.failed_stages?.length}><summary>阅读提示</summary>
        {currentReport.warnings.map((w,n)=><p key={n}>{w}</p>)}
        {currentReport.usage&&<p>模型调用 {currentReport.usage.calls} 次 · 输入 {currentReport.usage.input_tokens} · 输出 {currentReport.usage.output_tokens} Token
          {currentReport.usage.estimated_calls>0?'（含估算）':''}</p>}</details>
    </article>}
  </aside>;
}
