import {useEffect,useRef,useState} from 'react';
import {api,type Region,type Structure} from '../services/api';
import {TranslationDocument,type TranslationResult as Result} from './TranslationDocument';

type Model={endpoint:string;model:string;key_env:string;revision:string|null;source?:'workspace'|'task'};
type Term={english:string;chinese:string;locked:boolean;priority:string};
type Glossary={id:string|null;entries:Term[]};
type RunItem={id:string;job_id:string;status:string;error:string|null;counts:Record<string,number>};
type Run=RunItem & {blocks:Result[];snapshot:{task:string;scope?:string;glossary:Glossary;config:Model;blocks:Structure['blocks']}};

function isFullTranslation(run:Run, blockCount:number) {
  return run.snapshot.task === 'translation' && (run.snapshot.scope === 'full' ||
    (!run.snapshot.scope && run.snapshot.blocks.length === blockCount));
}

export function TranslationPanel({structure,paperId,onLocate,onDirty,bilingual=false}:{structure:Structure;paperId:string;onLocate:(r:Region[],label:string)=>void;onDirty:(value:boolean)=>void;bilingual?:boolean}){
  const [runs,setRuns]=useState<RunItem[]>([]),[run,setRun]=useState<Run|null>(null),[selected,setSelected]=useState('');
  const [gloss,setGloss]=useState<Glossary>({id:null,entries:[]}),[termText,setTermText]=useState('[]');
  const [task,setTask]=useState('translation'),[model,setModel]=useState<Model>({endpoint:'',model:'',key_env:'',revision:null});
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
    const data=await r.json();
    if(!r.ok){setDetail(JSON.stringify(data.detail,null,2));throw new Error(typeof data.detail==='string'?data.detail:'版本冲突，编辑内容保留，请比较后人工合并')}
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
      setRuns(history);
      setGloss(glossary);
      setTermText(JSON.stringify(glossary.entries,null,2));
      for (const item of history) {
        if (!live || runSelectionChanged.current) return;
        if (item.counts.total !== blockCount) continue;
        const candidate = await api<Run>(`/v1/translation-runs/${item.id}`);
        if (isFullTranslation(candidate,blockCount)) {
          if (live && !runSelectionChanged.current) setRun(candidate);
          return;
        }
      }
    }
    void load().catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[parseId,paperId,blockCount]);
  useEffect(()=>{let live=true;void api<Model>('/v1/task-model-settings/'+task).then(v=>{if(live)setModel(v)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[task]);
  useEffect(()=>{if(!run||!['queued','running'].includes(run.status))return;let live=true;const timer=setInterval(()=>{void api<Run>('/v1/translation-runs/'+run.id).then(v=>{if(live)setRun(v)}).catch(e=>{if(live)setError(e.message)})},1000);return()=>{live=false;clearInterval(timer)}},[run?.id,run?.status]);
  function accept(r:Run,id=selected){setRun(r);setSelected(id);const b=r.blocks.find(x=>x.block_id===id);setText(b?.result.text||'');setBase(b?.id||'');setDirty(false)}
  async function submit(ids:string[]=scope==='full'?[]:[scopeId],chosen=scope,forced=force,chosenTask=task){
    runSelectionChanged.current=true;
    const r=await request<Run>('/parse-runs/'+parseId+'/translation-runs',{scope:chosen,ids,force:forced,task:chosenTask,operation_key:crypto.randomUUID()});accept(r,'');setRuns(await request<RunItem[]>('/parse-runs/'+parseId+'/translation-runs'));
  }
  const block=structure.blocks.find(b=>b.id===selected),result=run?.blocks.find(b=>b.block_id===selected);
  useEffect(()=>{if(result&&!dirty&&!busy){setText(result.result.text);setBase(result.id)}},[result?.id,dirty,busy]);
  return <section className="translation-panel" aria-label={bilingual?'双语对照':'中文翻译'}>
    {error&&<p role="alert">{error}</p>}{detail&&<pre style={{whiteSpace:'pre-wrap'}}>{detail}</pre>}
    <fieldset disabled={busy}>
      {!run&&<div className="translation-start">
        <p>{bilingual?'翻译整篇论文后，可在原文下方对照阅读中文译文。':'翻译完成后，中文译文会按论文顺序连续显示。'}</p>
        <button type="button" className="primary" onClick={()=>void work(()=>submit([],'full',false,'translation'))}>翻译整篇论文</button>
      </div>}
      <details className="translation-controls"><summary>翻译设置与历史</summary>
      <label>任务类型<select aria-label="翻译任务类型" value={task} onChange={e=>setTask(e.target.value)}><option value="translation">学术翻译</option><option value="glossary">术语建议提取</option></select></label>
      <p>{model.model ? `${model.source==='task'?'专用模型':'工作台默认模型'} · ${model.model}` : '请先在 AI 分章节精读中配置工作台默认模型。'}</p>
      <details><summary>单独指定模型（可选）</summary>
        <label>模型端点<input aria-label="翻译模型端点" value={model.endpoint} onChange={e=>setModel({...model,endpoint:e.target.value})}/></label><label>模型名<input aria-label="翻译模型名" value={model.model} onChange={e=>setModel({...model,model:e.target.value})}/></label><label>Worker凭据环境变量名<input aria-label="翻译凭据变量" value={model.key_env} onChange={e=>setModel({...model,key_env:e.target.value})}/></label>
        <button onClick={()=>void work(async()=>setModel(await request<Model>('/task-model-settings/'+task,{...model,expected_revision:model.revision})))}>保存翻译模型设置</button><p>保存配置不会调用模型。支持非流式 Chat Completions JSON 协议。</p></details>
      <details><summary>论文术语与锁定</summary><p>每项含 english、chinese、locked、priority。priority 使用 confirmed 或 suggested。大小写不敏感，词边界匹配，最长优先。修改生成新版本。</p>
        <textarea aria-label="论文术语JSON" rows={7} value={termText} onChange={e=>setTermText(e.target.value)}/><button onClick={()=>void work(async()=>{const g=await request<Glossary>('/papers/'+paperId+'/glossary',{expected_revision:gloss.id,entries:JSON.parse(termText)});setGloss(g);setTermText(JSON.stringify(g.entries,null,2))})}>保存术语新版本</button><p>当前术语版本 {gloss.id||'默认词表'}；已提交任务使用原快照。</p></details>
      <label>翻译范围<select aria-label="翻译范围" value={scope} disabled={dirty} onChange={e=>{setScope(e.target.value);setScopeId('')}}><option value="full">全文</option><option value="sections">章节</option><option value="blocks">单块</option></select></label>
      {scope!=='full'&&<select aria-label="翻译范围对象" value={scopeId} disabled={dirty} onChange={e=>setScopeId(e.target.value)}><option value="">选择范围</option>{(scope==='sections'?structure.sections:structure.blocks).map(b=><option key={b.id} value={b.id}>{'title' in b?b.title:b.text.slice(0,65)}</option>)}</select>}
      <label><input type="checkbox" checked={force} onChange={e=>setForce(e.target.checked)}/>强制重译并保留旧运行</label><button disabled={dirty||scope!=='full'&&!scopeId} onClick={()=>void work(()=>submit())}>{task==='glossary'?'提取术语建议':scope==='full'?'翻译整篇论文':'翻译所选范围'}</button>
      <label>翻译运行历史<select aria-label="翻译运行历史" disabled={dirty} value={run?.id||''} onChange={e=>{
        const id=e.target.value;
        runSelectionChanged.current=true;
        if(!id){setRun(null);setSelected('');return;}
        void work(async()=>accept(await request<Run>(`/translation-runs/${id}`),''));
      }}><option value="">选择运行</option>{runs.map(r=><option key={r.id} value={r.id}>{r.id.slice(0,8)} · {r.status}</option>)}</select></label>
      </details>
      {run&&<><p role="status">
        {['queued','running'].includes(run.status)?`已处理 ${run.blocks.length} / ${run.counts.total} 块`:run.counts.failed+run.counts.needs_review>0?`${run.counts.failed+run.counts.needs_review} 处译文待处理，正文已标注。`:run.error||'翻译已完成'}
      </p><details><summary>翻译任务详情</summary>
        <p>已译 {run.counts.translated} · 保留 {run.counts.preserved} · 待复核 {run.counts.needs_review} · 失败 {run.counts.failed} · 缓存 {run.counts.cache_hits} · 完成率 {Math.round(run.counts.completion*100)}%</p>
        <p>模型 {run.snapshot.config.model} · 术语快照 {run.snapshot.glossary.id||'默认词表'} · {run.error}</p>
        <button disabled={dirty} onClick={()=>void work(async()=>accept(await request<Run>('/translation-runs/'+run.id)))}>刷新翻译进度</button>
        <button disabled={dirty||!run.blocks.some(b=>['failed','needs_review'].includes(b.result.status))} onClick={()=>void work(()=>submit(run.blocks.filter(b=>['failed','needs_review'].includes(b.result.status)).map(b=>b.block_id),'blocks',true,run.snapshot.task))}>重试问题块（新运行）</button>
        </details>
        {run.snapshot.task==='translation'&&<>
          <h3>{isFullTranslation(run,blockCount)?'全文译文':'所选范围译文'}</h3>
          <TranslationDocument blocks={run.snapshot.blocks} results={run.blocks} parseId={parseId} status={run.status} bilingual={bilingual} onLocate={onLocate} onEdit={id=>{
            if(dirty||working.current)return;
            accept(run,id);
            if(editor.current){editor.current.open=true;editor.current.scrollIntoView({block:'start'});}
          }}/>
        </>}
        <details ref={editor}><summary>{run.snapshot.task==='glossary'?'查看术语建议':'按段校对或重译'}</summary>
        <select aria-label="翻译结果块" disabled={dirty} value={selected} onChange={e=>accept(run,e.target.value)}><option value="">选择块结果</option>{run.snapshot.blocks.map(b=><option key={b.id} value={b.id}>{b.type} · {b.text.slice(0,60)} · {run.blocks.find(x=>x.block_id===b.id)?.result.status||'等待处理'}</option>)}</select>
        {block&&<><h3>英文原文</h3><pre style={{whiteSpace:'pre-wrap'}}>{block.text}</pre><button disabled={!block.regions.length} onClick={()=>onLocate(block.regions,block.text)}>定位翻译原文</button>{!block.regions.length&&<p>来源缺少可靠区域，无法定位</p>}
          {result&&<><p>{result.result.status} · {result.result.reason} {result.result.manual?'人工修改，待复核':''}</p>{result.result.table?<table><tbody>{result.result.table.cells.map((cell,i)=><tr key={i}><td>行 {cell.row} 列 {cell.column}</td><td>{cell.text}</td></tr>)}</tbody></table>:<><h3>中文译文</h3><textarea aria-label="译文编辑" rows={8} value={text} onChange={e=>{setText(e.target.value);setDirty(true)}}/><button disabled={!dirty} onClick={()=>void work(async()=>accept(await request<Run>('/translation-runs/'+run.id+'/blocks/'+selected,{expected_revision:base,text},'PATCH')))}>保存译文修改</button>{dirty&&<button onClick={()=>void work(async()=>{const latest=await request<Run>('/translation-runs/'+run.id);const head=latest.blocks.find(b=>b.block_id===selected);if(!head)throw new Error('当前译文版本不存在');setRun(latest);setBase(head.id);setDetail(JSON.stringify({remote:head.result.text,current_revision:head.id},null,2))})}>保留文字并载入最新译文基线</button>}</>}
          {result.result.terms&&<pre style={{whiteSpace:'pre-wrap'}}>{JSON.stringify(result.result.terms,null,2)}</pre>}
          <button disabled={dirty} onClick={()=>void work(()=>submit([selected],'blocks',true))}>重新翻译此块</button><button disabled={dirty} onClick={()=>void work(async()=>setDetail(JSON.stringify(await request('/translation-runs/'+run.id+'/blocks/'+selected+'/revisions'),null,2)))}>查看译文版本</button></>}
        </>}
        </details>
      </>}
    </fieldset>
  </section>;
}
