import {useEffect,useRef,useState} from 'react';
import {api,type Region,type Structure} from '../services/api';
import type {Highlight} from '../services/highlights';
import {TranslationDocument,type PassageSelection,type TranslationResult as Result} from './TranslationDocument';

type Model={endpoint:string;model:string;key_env:string;revision:string|null;source?:'workspace'|'task';uses_default_model?:boolean;has_saved_key?:boolean;masked_key?:string|null;use_system_proxy?:boolean};
type Term={english:string;chinese:string;locked:boolean;priority:string};
type Glossary={id:string|null;entries:Term[]};
type RunItem={id:string;job_id:string;status:string;error:string|null;scope?:string;task?:string;counts:Record<string,number>};
type Run=RunItem & {blocks:Result[];snapshot:{task:string;scope?:string;glossary:Glossary;config:Model;blocks:Structure['blocks']}};

function isFullTranslation(run:Run, blockCount:number) {
  return run.snapshot.task === 'translation' && (run.snapshot.scope === 'full' ||
    (!run.snapshot.scope && run.snapshot.blocks.length === blockCount));
}

export function TranslationPanel({structure,paperId,settingsVersion=0,onLocate,onDirty,bilingual=false,highlights=[],onSelectPassage,onHighlightClick}:{structure:Structure;paperId:string;settingsVersion?:number;onLocate:(r:Region[],label:string)=>void;onDirty:(value:boolean)=>void;bilingual?:boolean;highlights?:Highlight[];onSelectPassage?:(sel:PassageSelection|null)=>void;onHighlightClick?:(id:string|null)=>void}){
  const [runs,setRuns]=useState<RunItem[]>([]),[run,setRun]=useState<Run|null>(null),[selected,setSelected]=useState('');
  const [gloss,setGloss]=useState<Glossary>({id:null,entries:[]}),[terms,setTerms]=useState<Term[]>([]);
  const [newEn,setNewEn]=useState(''),[newZh,setNewZh]=useState(''),[newLock,setNewLock]=useState(true);
  const [task,setTask]=useState('translation'),[model,setModel]=useState<Model>({endpoint:'',model:'',key_env:'',revision:null});
  const [apiKey,setApiKey]=useState('');
  const [scope,setScope]=useState('full'),[scopeId,setScopeId]=useState(''),[force,setForce]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[detail,setDetail]=useState(''),[text,setText]=useState(''),[base,setBase]=useState('');
  const working=useRef(false),[dirty,setDirty]=useState(false);
  const editor=useRef<HTMLDetailsElement>(null);
  const runSelectionChanged=useRef(false);
  const parseId=structure.run.id;
  const blockCount=structure.blocks.length;

  useEffect(()=>{onDirty(dirty);return()=>onDirty(false)},[dirty,onDirty]);
  useEffect(()=>{if(!dirty)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=''};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn)},[dirty]);

  async function request<T>(path:string,value?:unknown,method='POST'){
    if(value===undefined)return api<T>('/v1'+path);
    const r=await fetch('/api/v1'+path,{method,headers:{'Content-Type':'application/json','X-PaperMind-Client':'workspace'},body:JSON.stringify(value)});
    let data:Record<string,unknown>={};
    try{data=(await r.json()) as Record<string,unknown>}catch{throw new Error(`服务响应格式无效 (HTTP ${r.status})`)}
    if(!r.ok){
      if(r.status===409&&data.detail&&typeof data.detail==='object'&&!Array.isArray(data.detail)){
        setDetail(JSON.stringify(data.detail,null,2));
        throw new Error('版本冲突，编辑内容已保留，请比较后人工合并');
      }
      throw new Error(typeof data.detail==='string'?data.detail:`请求失败 (HTTP ${r.status})`);
    }
    return data as T;
  }
  async function work(fn:()=>Promise<void>){if(working.current)return;working.current=true;setBusy(true);setError('');setDetail('');try{await fn()}catch(e){setError((e as Error).message)}finally{working.current=false;setBusy(false)}}

  useEffect(()=>{
    let live=true;
    async function load(){
      const [history, glossary] = await Promise.all([
        api<RunItem[]>(`/v1/parse-runs/${parseId}/translation-runs`),
        api<Glossary>(`/v1/papers/${paperId}/glossary`),
      ]);
      if (!live) return;
      setRuns(history);setGloss(glossary);setTerms(glossary.entries);
      const match = history.find(item => (item.task || 'translation') === 'translation' && (item.scope === 'full' || item.counts.total === blockCount));
      if (match && !runSelectionChanged.current) {
        const candidate = await api<Run>(`/v1/translation-runs/${match.id}`);
        if (live && !runSelectionChanged.current && isFullTranslation(candidate, blockCount)) setRun(candidate);
      }
    }
    void load().catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[parseId,paperId,blockCount]);

  useEffect(()=>{let live=true;void api<Model>('/v1/task-model-settings/'+task).then(v=>{if(live)setModel(v)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[task,settingsVersion]);
  useEffect(()=>{if(!run||!['queued','running'].includes(run.status))return;let live=true;const timer=setInterval(()=>{void api<Run>('/v1/translation-runs/'+run.id).then(v=>{if(live)setRun(v)}).catch(e=>{if(live)setError(e.message)})},1500);return()=>{live=false;clearInterval(timer)}},[run?.id,run?.status]);

  function accept(r:Run,id=selected){setRun(r);setSelected(id);const b=r.blocks.find(x=>x.block_id===id);setText(b?.result.text||'');setBase(b?.id||'');setDirty(false)}
  async function submit(ids:string[]=scope==='full'?[]:[scopeId],chosen=scope,forced=force,chosenTask=task){
    runSelectionChanged.current=true;
    const r=await request<Run>('/parse-runs/'+parseId+'/translation-runs',{scope:chosen,ids,force:forced,task:chosenTask,operation_key:crypto.randomUUID()});accept(r,'');setRuns(await request<RunItem[]>('/parse-runs/'+parseId+'/translation-runs'));
  }
  async function cancelJob(){
    if(!run)return;
    await api(`/jobs/${run.job_id}/cancel`,{method:'POST'});
    setRun({...run,status:'cancelled'});
  }
  const block=structure.blocks.find(b=>b.id===selected),result=run?.blocks.find(b=>b.block_id===selected);
  useEffect(()=>{if(result&&!dirty&&!busy){setText(result.result.text);setBase(result.id)}},[result?.id,dirty,busy]);

  return <section className="translation-panel" aria-label={bilingual?'双语对照':'中文翻译'}>
    {error&&<p role="alert" className="error">{error}</p>}{detail&&<pre style={{whiteSpace:'pre-wrap'}}>{detail}</pre>}
    <fieldset disabled={busy}>
      {!run&&<div className="translation-start">
        <p>{bilingual?'翻译整篇论文后，可在原文下方逐段对照阅读中文译文（已启用同章节批量加速翻译）。':'翻译完成后，中文译文与渲染后的数学公式将按论文顺序连续显示。'}</p>
        {!model.has_saved_key&&model.uses_default_model&&<p className="reading-caution">请先在右侧「AI 精读 → 模型配置」中填写并保存 API 密钥。</p>}
        <button type="button" className="primary" onClick={()=>void work(()=>submit([],'full',false,'translation'))}>翻译整篇论文</button>
      </div>}
      <details className="translation-controls"><summary>翻译设置、专业术语表与历史</summary>
        <div className="notes-toolbar">
          <label>任务类型<select aria-label="翻译任务类型" value={task} onChange={e=>setTask(e.target.value)}><option value="translation">学术翻译</option><option value="glossary">提取论文术语建议</option></select></label>
          <span>当前模型：{model.model||'未配置'} ({model.source==='task'?'翻译专用':'沿用精读默认'})</span>
        </div>
        <details><summary>单独为翻译指定模型（可选）</summary>
          <label>模型端点<input aria-label="翻译模型端点" value={model.endpoint} onChange={e=>setModel({...model,endpoint:e.target.value})}/></label>
          <label>模型名<input aria-label="翻译模型名" value={model.model} onChange={e=>setModel({...model,model:e.target.value})}/></label>
          <label>专用 API 密钥（可选，DPAPI 加密保存）<input type="password" placeholder={model.has_saved_key?`已保存 (${model.masked_key})`:'留空则沿用精读密钥'} value={apiKey} onChange={e=>setApiKey(e.target.value)}/></label>
          <label className="checkbox-inline"><input type="checkbox" checked={!!model.use_system_proxy} onChange={e=>setModel({...model,use_system_proxy:e.target.checked})}/> 跟随系统代理</label>
          <button type="button" onClick={()=>void work(async()=>{const m=await request<Model>('/task-model-settings/'+task,{endpoint:model.endpoint,model:model.model,key_env:model.key_env,expected_revision:model.revision,api_key:apiKey.trim()||undefined,use_system_proxy:!!model.use_system_proxy});setModel(m);setApiKey('')})}>保存专用模型</button>
        </details>

        <details><summary>论文术语锁定表 ({terms.length} 项)</summary>
          <p>锁定的英文术语在翻译中会被严格保护替换，确保全篇译法统一。</p>
          {terms.length>0&&<table className="glossary-table"><thead><tr><th>英文原词</th><th>固定中文译法</th><th>强制锁定</th><th>操作</th></tr></thead><tbody>
            {terms.map((t,idx)=><tr key={idx}>
              <td><input value={t.english} onChange={e=>setTerms(ts=>ts.map((x,i)=>i===idx?{...x,english:e.target.value}:x))}/></td>
              <td><input value={t.chinese} onChange={e=>setTerms(ts=>ts.map((x,i)=>i===idx?{...x,chinese:e.target.value}:x))}/></td>
              <td><input type="checkbox" checked={t.locked} onChange={e=>setTerms(ts=>ts.map((x,i)=>i===idx?{...x,locked:e.target.checked}:x))}/></td>
              <td><button type="button" onClick={()=>setTerms(ts=>ts.filter((_,i)=>i!==idx))}>删除</button></td>
            </tr>)}
          </tbody></table>}
          <div className="notes-toolbar" style={{marginTop:8}}>
            <input placeholder="英文术语，如 ablation study" value={newEn} onChange={e=>setNewEn(e.target.value)}/>
            <input placeholder="中文译法，如 消融实验" value={newZh} onChange={e=>setNewZh(e.target.value)}/>
            <label className="checkbox-inline"><input type="checkbox" checked={newLock} onChange={e=>setNewLock(e.target.checked)}/> 锁定</label>
            <button type="button" disabled={!newEn.trim()||!newZh.trim()} onClick={()=>{setTerms(p=>[...p,{english:newEn.trim(),chinese:newZh.trim(),locked:newLock,priority:'confirmed'}]);setNewEn('');setNewZh('')}}>＋ 添加术语</button>
            <button type="button" className="primary" onClick={()=>void work(async()=>{const g=await request<Glossary>('/papers/'+paperId+'/glossary',{expected_revision:gloss.id,entries:terms});setGloss(g);setTerms(g.entries)})}>保存术语表</button>
          </div>
        </details>

        <div className="notes-toolbar" style={{marginTop:8}}>
          <label>翻译范围<select aria-label="翻译范围" value={scope} disabled={dirty} onChange={e=>{setScope(e.target.value);setScopeId('')}}><option value="full">全文</option><option value="sections">指定章节</option><option value="blocks">指定段落</option></select></label>
          {scope!=='full'&&<select aria-label="翻译范围对象" value={scopeId} disabled={dirty} onChange={e=>setScopeId(e.target.value)}><option value="">选择对象…</option>{(scope==='sections'?structure.sections:structure.blocks).map(b=><option key={b.id} value={b.id}>{'title' in b?b.title:b.text.slice(0,65)}</option>)}</select>}
          <label className="checkbox-inline"><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)}/> 忽略缓存重译</label>
          <button type="button" className="primary" disabled={dirty||scope!=='full'&&!scopeId} onClick={()=>void work(()=>submit())}>{task==='glossary'?'提取术语建议':scope==='full'?'翻译整篇论文':'翻译所选范围'}</button>
        </div>
        {runs.length>0&&<label>历史翻译记录 <select aria-label="翻译运行历史" disabled={dirty} value={run?.id||''} onChange={e=>{
          const id=e.target.value;runSelectionChanged.current=true;
          if(!id){setRun(null);setSelected('');return;}
          void work(async()=>accept(await request<Run>(`/translation-runs/${id}`),''));
        }}><option value="">切换翻译记录…</option>{runs.map(r=><option key={r.id} value={r.id}>{r.id.slice(0,8)} · {r.status} · 已完成 {Math.round((r.counts?.completion||0)*100)}%</option>)}</select></label>}
      </details>

      {run&&<>
        <div className="notes-toolbar">
          <p role="status">
            {['queued','running'].includes(run.status)?`正在批量翻译：已完成 ${run.blocks.length} / ${run.counts.total} 块`:run.counts.failed>0?`${run.counts.failed} 处译文失败，可点击重试问题块`:`翻译已完成（共 ${run.counts.translated} 段译文，${run.counts.preserved} 处图表/公式原样保留）`}
          </p>
          {['queued','running'].includes(run.status)&&<button type="button" onClick={()=>void work(cancelJob)}>取消翻译</button>}
          {!['queued','running'].includes(run.status)&&run.blocks.some(b=>b.result.status==='failed')&&<button type="button" disabled={dirty} onClick={()=>void work(()=>submit(run.blocks.filter(b=>b.result.status==='failed').map(b=>b.block_id),'blocks',true,run.snapshot.task))}>重试失败块</button>}
        </div>
        {run.snapshot.task==='translation'&&<>
          <TranslationDocument blocks={run.snapshot.blocks} results={run.blocks} parseId={parseId} status={run.status} bilingual={bilingual} highlights={highlights} onSelectPassage={onSelectPassage} onHighlightClick={onHighlightClick} onLocate={onLocate} onEdit={id=>{
            if(dirty||working.current)return;
            accept(run,id);
            if(editor.current){editor.current.open=true;editor.current.scrollIntoView({block:'start'});}
          }}/>
        </>}
        <details ref={editor}><summary>{run.snapshot.task==='glossary'?'查看提取的术语建议':'逐段人工润色与修订'}</summary>
          <select aria-label="翻译结果块" disabled={dirty} value={selected} onChange={e=>accept(run,e.target.value)}><option value="">选择需要校对的段落…</option>{run.snapshot.blocks.map(b=><option key={b.id} value={b.id}>{b.type} · {b.text.slice(0,60)}</option>)}</select>
          {block&&<><h4>英文原文</h4><pre style={{whiteSpace:'pre-wrap'}}>{block.text}</pre><button type="button" disabled={!block.regions.length} onClick={()=>onLocate(block.regions,block.text)}>在 PDF 中定位</button>
            {result&&<>{result.result.table?<table><thead><tr><th>位置</th><th>译文</th></tr></thead><tbody>{result.result.table.cells.map((cell,i)=><tr key={i}><td>行 {cell.row} 列 {cell.column}</td><td>{cell.text}</td></tr>)}</tbody></table>:<><h4>中文译文修订</h4><textarea aria-label="译文编辑" rows={6} value={text} onChange={e=>{setText(e.target.value);setDirty(true)}}/><div className="notes-toolbar"><button type="button" className="primary" disabled={!dirty} onClick={()=>void work(async()=>accept(await request<Run>('/translation-runs/'+run.id+'/blocks/'+selected,{expected_revision:base,text},'PATCH')))}>保存修订</button><button type="button" disabled={dirty} onClick={()=>void work(()=>submit([selected],'blocks',true))}>单段重译</button></div></>}
            {result.result.terms&&<div><h4>建议术语（点击一键加入术语表）</h4><div className="reading-actions">{result.result.terms.map((tm,i)=><button type="button" key={i} onClick={()=>setTerms(p=>p.some(x=>x.english.toLowerCase()===tm.english.toLowerCase())?p:[...p,{english:tm.english,chinese:tm.chinese,locked:true,priority:'confirmed'}])}>＋ {tm.english} → {tm.chinese}</button>)}</div></div>}</>}
          </>}
        </details>
      </>}
    </fieldset>
  </section>;
}
