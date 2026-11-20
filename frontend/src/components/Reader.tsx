import {useEffect,useRef,useState} from 'react';
import {getDocument,GlobalWorkerOptions,type PDFDocumentProxy} from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import {api,type Paper,type Region,type ParseRun,type Structure,type Job,type SourceStatus} from '../services/api';
import {PdfPage} from './PdfPage';
import {StructurePanel} from './StructurePanel';
import {ReadingPanel} from './ReadingPanel';
import {ChatPanel} from './ChatPanel';
import {NotesPanel} from './NotesPanel';
import {TranslationPanel} from './TranslationPanel';
import type {PaperSelection} from '../services/selection';
import type {Identity} from '../services/chat';
import '../reader.css';
GlobalWorkerOptions.workerSrc=workerUrl;
type ReaderMode='original'|'translation'|'bilingual';
const readerModes: {id:ReaderMode;label:string}[]=[{id:'original',label:'英文原文'},{id:'translation',label:'中文翻译'},{id:'bilingual',label:'双语对照'}];
type SearchHit={text:string;page_label:string;regions:Region[]};

export function Reader({paper,onBack}:{paper:Paper;onBack:()=>void}){
  const [readerMode,setReaderMode]=useState<ReaderMode>('bilingual');
  const [selectedSection,setSelectedSection]=useState<string|null>(null);
  const [translationDirty,setTranslationDirty]=useState(false);
  function leaveTranslation(){return !translationDirty||window.confirm('译文有未保存修改，确定放弃这些修改？')}
  const [notesOpen,setNotesOpen]=useState(false),[savedMessage,setSavedMessage]=useState<string|null>(null);
  const chatVisible=import.meta.env.VITE_PAPERMIND_INTERACTIVE_READING==='1';
  const [showReading,setShowReading]=useState(true),[sideMode,setSideMode]=useState<'reading'|'chat'>(()=>chatVisible&&sessionStorage.getItem('reader-side-'+paper.id)==='chat'?'chat':'reading');
  const pendingSource=useRef<{identity:Identity;regions:Region[];label:string}|null>(null);
  const [fid,setFid]=useState(()=>paper.files.find(f=>f.id===sessionStorage.getItem('reader-file-'+paper.id))?.id||paper.files[0].id),[doc,setDoc]=useState<PDFDocumentProxy|null>(null);
  const fileRef=useRef(fid);fileRef.current=fid;
  const [page,setPage]=useState(1),[scale,setScale]=useState(1),[rotation,setRotation]=useState(0),[error,setError]=useState('');
  const [runs,setRuns]=useState<ParseRun[]>([]),[current,setCurrent]=useState<string|null>(null),[viewRun,setViewRun]=useState<string|null>(()=>sessionStorage.getItem('reader-run-'+fid));
  const [structure,setStructure]=useState<Structure|null>(null),[job,setJob]=useState<Job|null>(null),[mode,setMode]=useState('docling');
  const [formulas,setFormulas]=useState(true);
  const [sourcePreferred,setSourcePreferred]=useState(true),[source,setSource]=useState<SourceStatus|null>(null),[sourceJob,setSourceJob]=useState<Job|null>(null);
  const [regions,setRegions]=useState<Region[]>([]),[located,setLocated]=useState(''),[selection,setSelection]=useState<PaperSelection|null>(null);
  const [query,setQuery]=useState(''),[hits,setHits]=useState<SearchHit[]>([]),[searching,setSearching]=useState(false),[submitting,setSubmitting]=useState(false);
  useEffect(()=>{window.scrollTo(0,0)},[]);
  useEffect(()=>{if(showReading)sessionStorage.setItem('reader-side-'+paper.id,sideMode);else sessionStorage.removeItem('reader-side-'+paper.id)},[showReading,sideMode,paper.id]);
  useEffect(()=>{sessionStorage.setItem('reader-file-'+paper.id,fid)},[fid,paper.id]);
  useEffect(()=>{if(structure?.run.paper_file_id===fid&&structure.run.id===(viewRun||current))sessionStorage.setItem('reader-run-'+fid,structure.run.id)},[structure,fid,viewRun,current]);
  useEffect(()=>{
    setDoc(null);setPage(1);setRegions([]);setStructure(null);setViewRun(pendingSource.current?.identity.paper_file_id===fid?pendingSource.current.identity.parse_run_id:sessionStorage.getItem('reader-run-'+fid));setCurrent(null);setRuns([]);setJob(null);setSource(null);setSourceJob(null);setError('');setSelection(null);setHits([]);setLocated('');
    let live=true;
    const task=getDocument('/api/files/'+fid+'/content');
    task.promise.then(d=>{if(live)setDoc(d)}).catch(()=>{if(live)setError('PDF 无法打开')});
    async function load(){
      const r=await api<{runs:ParseRun[];current_run_id:string|null}>(`/v1/files/${fid}/parse-runs`);
      const src=await api<SourceStatus>(`/v1/files/${fid}/source`);if(live)setSource(src);
      if(!live)return;
      setRuns(r.runs);setCurrent(r.current_run_id);setError(previous=>previous.startsWith('服务响应不完整')?'':previous);
      const latest=r.runs[0];
      if(latest){const j=await api<Job>('/jobs/'+latest.job_id);if(live)setJob(j)}
    }
    void load().catch(e=>{if(live)setError(e.message)});
    const timer=setInterval(()=>void load().catch(e=>{if(live)setError(e.message)}),1500);
    return()=>{live=false;clearInterval(timer);void task.destroy()};
  },[fid]);
  useEffect(()=>{
    if(!sourceJob||!['queued','running'].includes(sourceJob.status))return;
    let live=true;const id=sourceJob.id;
    const timer=setInterval(()=>{void api<Job>('/jobs/'+id).then(j=>{if(live)setSourceJob(j)}).catch(e=>{if(live)setError(e.message)})},1500);
    return()=>{live=false;clearInterval(timer)};
  },[fid,sourceJob?.id,sourceJob?.status]);
  async function fetchSource(){
    const requested=fid;setError('');
    try{const r=await api<{job_id:string}>(`/v1/files/${fid}/source`,{method:'POST'});const j=await api<Job>('/jobs/'+r.job_id);if(fileRef.current===requested)setSourceJob(j)}catch(e){if(fileRef.current===requested)setError((e as Error).message)}
  }
  const target=viewRun||current;
  useEffect(()=>{
    setRegions([]);setLocated('');
    if(!target){setStructure(null);return}
    let live=true;
    api<Structure>(`/v1/parse-runs/${target}/structure`).then(s=>{if(live&&s.run.paper_file_id===fid)setStructure(s)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[target,fid]);
  async function parse(force:boolean){
    if(!leaveTranslation())return;
    setError('');setSubmitting(true);
    try{const r=await api<ParseRun>(`/v1/files/${fid}/parse-runs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode,force,formulas,source_preferred:sourcePreferred})});if(fileRef.current!==fid)return;setRuns(p=>[r,...p.filter(v=>v.id!==r.id)]);const j=await api<Job>('/jobs/'+r.job_id);if(fileRef.current!==fid)return;setJob(j);setViewRun(null)}catch(e){if(fileRef.current===fid)setError((e as Error).message)}finally{setSubmitting(false)}
  }
  async function retry(){if(!job)return;try{setJob(await api<Job>(`/jobs/${job.id}/retry`,{method:'POST'}))}catch(e){setError((e as Error).message)}}
  function locate(rs:Region[],label:string){setRegions(rs);setLocated(label);setSelection(null);if(rs.length)setPage(rs[0].page_index+1)}
  async function search(e:React.FormEvent){e.preventDefault();setSearching(true);setError('');try{const r=await api<{results:SearchHit[];truncated:boolean}>(`/v1/files/${fid}/search?q=${encodeURIComponent(query)}`);if(fileRef.current!==fid)return;setHits(r.results);if(r.results.length)locate(r.results[0].regions,query)}catch(e){if(fileRef.current===fid)setError((e as Error).message)}finally{setSearching(false)}}
  useEffect(()=>{setSelection(null)},[fid,target,page]);
  useEffect(()=>{
    const source=pendingSource.current;
    if(source&&structure?.run.id===source.identity.parse_run_id&&fid===source.identity.paper_file_id){
      setRegions(source.regions);setLocated(source.label);if(source.regions.length)setPage(source.regions[0].page_index+1);pendingSource.current=null;
    }
  },[structure,fid]);
  function locateChat(identity:Identity,rs:Region[],label:string){
    const file=paper.files.find(f=>f.id===identity.paper_file_id);
    if(identity.paper_id!==paper.id||!file||file.sha256!==identity.file_sha256){setError('引用来源身份不匹配');return}
    if(!leaveTranslation())return;
    setReaderMode('original');
    if(fid===identity.paper_file_id&&target===identity.parse_run_id){locate(rs,label);return}
    setSelection(null);pendingSource.current={identity,regions:rs,label};setFid(identity.paper_file_id);setViewRun(identity.parse_run_id);
  }
  const busy=job&&['queued','running'].includes(job.status);
  const activeStructure=structure?.run.id===target&&structure.run.paper_file_id===fid?structure:null;
  const displayMode=activeStructure?readerMode:'original';
  const sections=[...(activeStructure?.sections||[])].sort((a,b)=>a.reading_order-b.reading_order);
  function showOriginal(rs:Region[],label:string){
    if(!leaveTranslation())return;
    setReaderMode('original');locate(rs,label);
  }
  function jumpToSection(section:Structure['sections'][number]){
    setSelectedSection(section.id);
    if(displayMode==='original'){locate(section.regions,section.title);return;}
    const first=activeStructure?.blocks.filter(b=>b.section_id===section.id).sort((a,b)=>a.reading_order-b.reading_order)[0];
    const element=first&&document.getElementById(`reader-block-${first.id}`);
    if(element)element.scrollIntoView({block:'start'});
    else showOriginal(section.regions,section.title);
  }
  useEffect(()=>setSelectedSection(null),[target]);
  return <div className="reader v2-reader paper-reader">
    <div className="paper-reader-toolbar">
    <header className="paper-reader-header">
      <div className="paper-reader-title"><strong>PaperMind Reader</strong><span title={paper.title||''}>{paper.title||'未命名论文'}</span></div>
      <div className="paper-reader-actions">
        <button type="button" onClick={()=>{if(leaveTranslation())onBack()}}>论文库</button>
        <button type="button" onClick={()=>{setSavedMessage(null);setNotesOpen(true)}}>笔记</button>
      </div>
    </header>
    <nav className="paper-modes" aria-label="阅读模式">
      {readerModes.map(mode=><button key={mode.id} type="button" aria-pressed={displayMode===mode.id}
        disabled={mode.id!=='original'&&!activeStructure} onClick={()=>{if(mode.id!=='original'||leaveTranslation())setReaderMode(mode.id)}}>{mode.label}</button>)}
    </nav>
    <details className="paper-reader-settings"><summary>阅读设置</summary>
    <div className="reader-tools"><select aria-label="文件版本" value={fid} onChange={e=>{if(leaveTranslation())setFid(e.target.value)}}>{paper.files.map(f=><option key={f.id} value={f.id}>文件版本 {f.version}{f.arxiv_version?` · arXiv v${f.arxiv_version}`:''}</option>)}</select>
    <button disabled={!doc||page<=1} onClick={()=>setPage(p=>p-1)}>上一页</button><label>页码 <input aria-label="页码" type="number" min={1} max={doc?.numPages||1} value={page} onChange={e=>setPage(Math.max(1,Math.min(doc?.numPages||1,Number(e.target.value)||1)))}/></label><span>/ {doc?.numPages||'—'}</span><button disabled={!doc||page>=doc.numPages} onClick={()=>setPage(p=>p+1)}>下一页</button>
    <button disabled={scale<=.4} onClick={()=>setScale(s=>Math.max(.4,s-.2))}>−</button><span>{Math.round(scale*100)}%</span><button disabled={scale>=3} onClick={()=>setScale(s=>Math.min(3,s+.2))}>＋</button><button onClick={()=>setRotation(r=>(r+90)%360)}>旋转 90°</button></div>
    </details>
    </div>
    {notesOpen&&<NotesPanel paperId={paper.id} fileId={fid} parseId={target} messageId={savedMessage} onClose={()=>setNotesOpen(false)} onLocate={(id,r,label)=>locateChat({...id,paper_id:paper.id,file_sha256:paper.files.find(f=>f.id===id.paper_file_id)?.sha256||''},r,label)}/>}
    {error&&<p role="alert" className="error">{error}</p>}
    <div className="paper-reader-grid">
    <aside className="paper-outline" aria-label="论文目录">
      <h2>论文目录</h2>
      {sections.length ? <nav aria-label="论文章节">
        {sections.map(section=><button key={section.id} type="button" aria-current={(selectedSection||sections[0]?.id)===section.id?'location':undefined}
          style={{paddingInlineStart:8+Math.max(0,Math.min(section.level-1,4))*9}}
          onClick={()=>jumpToSection(section)}>{section.title}</button>)}
      </nav> : <p>{activeStructure?'当前解析未识别到章节。':'解析完成后显示章节。'}</p>}
      <details className="paper-parse-controls"><summary>解析与查找</summary><div className="parse-controls"><select aria-label="解析模式" value={mode} onChange={e=>setMode(e.target.value)}><option value="docling">Docling 结构解析</option><option value="native">原生降级（能力有限）</option></select><label style={{fontSize:11}}><input aria-label="公式增强" type="checkbox" checked={formulas} disabled={mode!=='docling'} onChange={e=>setFormulas(e.target.checked)}/> 公式增强（本地模型）</label><button className="primary" disabled={!!busy||submitting} onClick={()=>void parse(false)}>启动解析</button><button disabled={!!busy||submitting} onClick={()=>void parse(true)}>重新解析（保留历史）</button></div>
    {job&&<div className="parse-job" role="status">最新任务：{job.status} · 尝试 {job.attempts}/{job.max_attempts}<p>{job.status==='succeeded'?'解析已完成':(job.error||job.checkpoint?.message||'等待 Worker')}</p>{job.status==='running'&&job.checkpoint&&<small>当前阶段：{job.checkpoint.stage||'阶段内处理中'}<br/>{job.checkpoint.elapsed_seconds===undefined?'阶段内处理中':`累计 ${job.checkpoint.elapsed_seconds} 秒`}{job.checkpoint.stage_elapsed_seconds!==undefined&&<> · 阶段 {job.checkpoint.stage_elapsed_seconds} 秒</>}{job.checkpoint.completed_pages!==undefined&&<> · 已处理 {job.checkpoint.completed_pages} 页</>}{job.checkpoint.completed_formulas!==undefined&&<> · 已处理 {job.checkpoint.completed_formulas} 个公式</>}</small>}{job.status==='failed'&&<button onClick={()=>void retry()}>重试解析</button>}</div>}
    <div className="parse-job"><label><input aria-label="源文件优先" type="checkbox" checked={sourcePreferred} disabled={mode!=='docling'} onChange={e=>setSourcePreferred(e.target.checked)}/> 优先使用对应版本源文件</label><p>{source?.status==='available'?(source.objects===0?'源包只有PDF包装，解析时使用PDF路线':`源文件已绑定 arXiv v${source.arxiv_version} · ${source.archive_sha256?.slice(0,12)}`):'没有可用的对应版本源文件，解析时使用PDF路线'}</p><button disabled={!paper.arxiv_id||!paper.files.find(f=>f.id===fid)?.arxiv_version||!!sourceJob&&['queued','running'].includes(sourceJob.status)} onClick={()=>void fetchSource()}>获取对应版本源文件</button>{sourceJob&&<p role="status">源文件任务：{sourceJob.status} · {sourceJob.attempts}/{sourceJob.max_attempts}{sourceJob.error&&<> · {sourceJob.error}</>}</p>}</div>
    <label>运行历史 <select aria-label="解析运行历史" value={target||''} onChange={e=>{if(leaveTranslation())setViewRun(e.target.value||null)}}><option value="">当前成功结果</option>{runs.map(r=><option key={r.id} value={r.id} disabled={r.status!=='succeeded'}>{r.parser} · {r.status} · {r.id.slice(0,8)}</option>)}</select></label>
    {structure&&<p><a href={`/api/v1/parse-runs/${structure.run.id}/markdown`} target="_blank" rel="noreferrer">Markdown ↗</a> · <a href={`/api/v1/parse-runs/${structure.run.id}/json`} target="_blank" rel="noreferrer">结构 JSON ↗</a></p>}
    <form className="search-form" onSubmit={search}><input aria-label="文件内搜索" placeholder="搜索当前 PDF 原生文字" required value={query} onChange={e=>setQuery(e.target.value)}/><button disabled={searching}>搜索</button></form>
    {query&&<p>{hits.length} 个搜索结果（扫描页无原生文字时不可搜索）</p>}<div className="search-hits">{hits.map((h,n)=><button key={n} onClick={()=>showOriginal(h.regions,h.text)}>第 {h.page_label} 页 · {h.text.slice(0,70)}</button>)}</div>
    <StructurePanel structure={activeStructure} onLocate={showOriginal}/></details></aside>
    <section className="paper-content" aria-label="论文正文">
    {displayMode!=='original'&&activeStructure&&<TranslationPanel key={activeStructure.run.id} structure={activeStructure} paperId={paper.id}
      bilingual={displayMode==='bilingual'} onLocate={showOriginal} onDirty={setTranslationDirty}/>}
    {displayMode==='original'&&<div className="reading-area">{activeStructure?.run.warnings?.map((w,n)=><p className="parse-warning" key={n}>{w}</p>)}
    {located&&<div className="located" role="status">定位：{located.slice(0,120)}{regions.map((r,n)=><button key={n} onClick={()=>setPage(r.page_index+1)}>区域 {n+1} · 第 {r.page_index+1} 页</button>)}</div>}
    {selection&&<output className="selected-text" aria-label="选中文字">已选择：{selection.text.slice(0,300)}</output>}
    <div className="pdf-stage">{doc?<PdfPage doc={doc} page={page} scale={scale} rotation={rotation} regions={regions} onSelection={setSelection} identity={{paper_file_id:fid,parse_run_id:target||'',file_sha256:paper.files.find(f=>f.id===fid)?.sha256||''}}/>:<p>正在加载 PDF…</p>}</div></div>}</section>
    <div className="paper-ai">
    <nav className="paper-ai-tabs" aria-label="AI 工作区">
      <button type="button" aria-pressed={showReading&&sideMode==='reading'} onClick={()=>{setSideMode('reading');setShowReading(true)}}>AI 精读</button>
      {chatVisible&&<button type="button" aria-pressed={showReading&&sideMode==='chat'} onClick={()=>{setSideMode('chat');setShowReading(true)}}>问答</button>}
    </nav>
    {showReading&&(sideMode==='reading'?<ReadingPanel key={fid+':'+target} parseId={target} fileId={fid} onLocate={showOriginal} onNote={id=>{sessionStorage.setItem('note-selected-'+paper.id,id);setSavedMessage(null);setNotesOpen(true)}} compact/>:<ChatPanel onSaveAnswer={id=>{setSavedMessage(id);setNotesOpen(true)}} paperId={paper.id} fileId={fid} parseId={target} pageIndex={page-1} selection={selection} onClear={()=>setSelection(null)} onLocate={locateChat}/>)}</div></div></div>;
}
