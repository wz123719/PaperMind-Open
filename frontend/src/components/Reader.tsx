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
const readerModes:{id:ReaderMode;label:string}[]=[{id:'original',label:'英文原文'},{id:'translation',label:'中文译文'},{id:'bilingual',label:'双语对照'}];
type SearchHit={text:string;page_label:string;regions:Region[]};

export function Reader({paper,onBack}:{paper:Paper;onBack:()=>void}){
  const [readerMode,setReaderMode]=useState<ReaderMode>('bilingual');
  const [selectedSection,setSelectedSection]=useState<string|null>(null);
  const [translationDirty,setTranslationDirty]=useState(false);
  function leaveTranslation(){return !translationDirty||window.confirm('译文有未保存修改，确定放弃这些修改？')}
  const [notesOpen,setNotesOpen]=useState(false),[savedMessage,setSavedMessage]=useState<string|null>(null);
  const chatVisible=import.meta.env.VITE_PAPERMIND_INTERACTIVE_READING!=='0';
  const [showOutline,setShowOutline]=useState(true),[showReading,setShowReading]=useState(true);
  const [sideMode,setSideMode]=useState<'reading'|'chat'>(()=>chatVisible&&sessionStorage.getItem('reader-side-'+paper.id)==='chat'?'chat':'reading');
  const [parseOpen,setParseOpen]=useState(false);
  const pendingSource=useRef<{identity:Identity;regions:Region[];label:string}|null>(null);
  const [fid,setFid]=useState(()=>paper.files.find(f=>f.id===sessionStorage.getItem('reader-file-'+paper.id))?.id||paper.files[0]?.id||'');
  const [doc,setDoc]=useState<PDFDocumentProxy|null>(null);
  const fileRef=useRef(fid);fileRef.current=fid;
  const [page,setPage]=useState(1),[scale,setScale]=useState(1.15),[rotation,setRotation]=useState(0),[error,setError]=useState('');
  const [runs,setRuns]=useState<ParseRun[]>([]),[current,setCurrent]=useState<string|null>(null),[viewRun,setViewRun]=useState<string|null>(()=>fid?sessionStorage.getItem('reader-run-'+fid):null);
  const [structure,setStructure]=useState<Structure|null>(null),[job,setJob]=useState<Job|null>(null),[mode,setMode]=useState('docling');
  const [formulas,setFormulas]=useState(true);
  const [sourcePreferred,setSourcePreferred]=useState(true),[source,setSource]=useState<SourceStatus|null>(null),[sourceJob,setSourceJob]=useState<Job|null>(null);
  const [regions,setRegions]=useState<Region[]>([]),[located,setLocated]=useState(''),[selection,setSelection]=useState<PaperSelection|null>(null);
  const [query,setQuery]=useState(''),[hits,setHits]=useState<SearchHit[]>([]),[searching,setSearching]=useState(false),[submitting,setSubmitting]=useState(false);

  useEffect(()=>{window.scrollTo(0,0)},[]);
  useEffect(()=>{if(showReading)sessionStorage.setItem('reader-side-'+paper.id,sideMode);else sessionStorage.removeItem('reader-side-'+paper.id)},[showReading,sideMode,paper.id]);
  useEffect(()=>{if(fid)sessionStorage.setItem('reader-file-'+paper.id,fid)},[fid,paper.id]);
  useEffect(()=>{if(structure?.run.paper_file_id===fid&&structure.run.id===(viewRun||current))sessionStorage.setItem('reader-run-'+fid,structure.run.id)},[structure,fid,viewRun,current]);

  async function refreshParseState(targetFid:string){
    const [r,src]=await Promise.all([
      api<{runs:ParseRun[];current_run_id:string|null}>(`/v1/files/${targetFid}/parse-runs`),
      api<SourceStatus>(`/v1/files/${targetFid}/source`),
    ]);
    if(fileRef.current!==targetFid)return;
    setSource(src);setRuns(r.runs);setCurrent(r.current_run_id);
    const latest=r.runs[0];
    if(latest){
      const j=await api<Job>('/jobs/'+latest.job_id);
      if(fileRef.current===targetFid)setJob(j);
    }
  }

  useEffect(()=>{
    if(!fid)return;
    setDoc(null);setPage(1);setRegions([]);setStructure(null);
    setViewRun(pendingSource.current?.identity.paper_file_id===fid?pendingSource.current.identity.parse_run_id:sessionStorage.getItem('reader-run-'+fid));
    setCurrent(null);setRuns([]);setJob(null);setSource(null);setSourceJob(null);setError('');setSelection(null);setHits([]);setLocated('');
    let live=true;
    const task=getDocument('/api/files/'+fid+'/content');
    task.promise.then(d=>{if(live)setDoc(d)}).catch(()=>{if(live)setError('PDF 无法打开')});
    void refreshParseState(fid).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false;void task.destroy()};
  },[fid]);

  const busy=!!job&&['queued','running'].includes(job.status);
  useEffect(()=>{
    if(!fid||!busy)return;
    let live=true;
    const timer=setInterval(()=>{if(live)void refreshParseState(fid).catch(()=>{})},1800);
    return()=>{live=false;clearInterval(timer)};
  },[fid,busy,job?.id]);

  useEffect(()=>{
    if(!sourceJob||!['queued','running'].includes(sourceJob.status))return;
    let live=true;const id=sourceJob.id;
    const timer=setInterval(()=>{void api<Job>('/jobs/'+id).then(j=>{if(live){setSourceJob(j);if(j.status==='succeeded'&&fid)void refreshParseState(fid)}}).catch(()=>{})},1800);
    return()=>{live=false;clearInterval(timer)};
  },[fid,sourceJob?.id,sourceJob?.status]);

  useEffect(()=>{
    function onKey(e:KeyboardEvent){
      if(notesOpen)return;
      const tag=(e.target as HTMLElement)?.tagName;
      if(tag==='INPUT'||tag==='TEXTAREA'||tag==='SELECT')return;
      if(e.key==='ArrowLeft'&&doc&&page>1){e.preventDefault();setPage(p=>p-1)}
      if(e.key==='ArrowRight'&&doc&&page<doc.numPages){e.preventDefault();setPage(p=>p+1)}
    }
    window.addEventListener('keydown',onKey);
    return()=>window.removeEventListener('keydown',onKey);
  },[doc,page,notesOpen]);

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
  async function cancelParse(){if(!job)return;try{setJob(await api<Job>(`/jobs/${job.id}/cancel`,{method:'POST'}))}catch(e){setError((e as Error).message)}}
  function locate(rs:Region[],label:string){setRegions(rs);setLocated(label);setSelection(null);if(rs.length)setPage(rs[0].page_index+1)}
  async function search(e:React.FormEvent){e.preventDefault();setSearching(true);setError('');try{const r=await api<{results:SearchHit[];truncated:boolean}>(`/v1/files/${fid}/search?q=${encodeURIComponent(query)}`);if(fileRef.current!==fid)return;setHits(r.results);if(r.results.length)locate(r.results[0].regions,query)}catch(e){if(fileRef.current===fid)setError((e as Error).message)}finally{setSearching(false)}}
  useEffect(()=>{setSelection(null)},[fid,target,page]);
  useEffect(()=>{
    const src=pendingSource.current;
    if(src&&structure?.run.id===src.identity.parse_run_id&&fid===src.identity.paper_file_id){
      setRegions(src.regions);setLocated(src.label);if(src.regions.length)setPage(src.regions[0].page_index+1);pendingSource.current=null;
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

  const activeStructure=structure?.run.id===target&&structure.run.paper_file_id===fid?structure:null;
  const displayMode=activeStructure?readerMode:'original';
  const sections=[...(activeStructure?.sections||[])].sort((a,b)=>a.reading_order-b.reading_order);
  function showOriginal(rs:Region[],label:string){if(!leaveTranslation())return;setReaderMode('original');locate(rs,label)}
  function jumpToSection(section:Structure['sections'][number]){
    setSelectedSection(section.id);
    if(displayMode==='original'){locate(section.regions,section.title);return;}
    const first=activeStructure?.blocks.filter(b=>b.section_id===section.id).sort((a,b)=>a.reading_order-b.reading_order)[0];
    const element=first&&document.getElementById(`reader-block-${first.id}`);
    if(element)element.scrollIntoView({block:'start'});
    else showOriginal(section.regions,section.title);
  }
  useEffect(()=>setSelectedSection(null),[target]);

  if(!fid)return <div className="reader"><p role="alert" className="error">该论文记录下暂无可用 PDF 文件。</p><button onClick={onBack}>返回论文库</button></div>;

  const gridCols=`${showOutline?'220px ':'0px '}minmax(0,1fr)${showReading?' 390px':' 0px'}`;
  return <div className="reader v2-reader paper-reader">
    <div className="paper-reader-toolbar">
      <header className="paper-reader-header">
        <div className="paper-reader-title">
          <button type="button" onClick={()=>{if(leaveTranslation())onBack()}}>← 论文库</button>
          <strong title={paper.title||''}>{paper.title||'未命名论文'}</strong>
        </div>
        <div className="paper-reader-actions">
          <button type="button" onClick={()=>setShowOutline(v=>!v)}>{showOutline?'隐藏目录':'显示目录'}</button>
          <button type="button" onClick={()=>setShowReading(v=>!v)}>{showReading?'专注阅读':'打开AI栏'}</button>
          <button type="button" className="primary" onClick={()=>{setSavedMessage(null);setNotesOpen(true)}}>✎ 知识笔记 / Obsidian</button>
        </div>
      </header>
      <div className="reader-subbar">
        <nav className="paper-modes" aria-label="阅读模式">
          {readerModes.map(m=><button key={m.id} type="button" aria-pressed={displayMode===m.id}
            disabled={m.id!=='original'&&!activeStructure} onClick={()=>{if(m.id!=='original'||leaveTranslation())setReaderMode(m.id)}}>{m.label}</button>)}
        </nav>
        {displayMode==='original'&&<div className="reader-tools">
          {paper.files.length>1&&<select aria-label="文件版本" value={fid} onChange={e=>{if(leaveTranslation())setFid(e.target.value)}}>{paper.files.map(f=><option key={f.id} value={f.id}>v{f.version}{f.arxiv_version?` (arXiv v${f.arxiv_version})`:''}</option>)}</select>}
          <button type="button" disabled={!doc||page<=1} onClick={()=>setPage(p=>p-1)} title="上一页 (←)">◀</button>
          <input aria-label="页码" type="number" min={1} max={doc?.numPages||1} value={page} onChange={e=>setPage(Math.max(1,Math.min(doc?.numPages||1,Number(e.target.value)||1)))} style={{width:52}}/>
          <span>/ {doc?.numPages||'—'}</span>
          <button type="button" disabled={!doc||page>=doc.numPages} onClick={()=>setPage(p=>p+1)} title="下一页 (→)">▶</button>
          <button type="button" disabled={scale<=.5} onClick={()=>setScale(s=>Math.round(Math.max(.5,s-.15)*100)/100)}>−</button>
          <button type="button" onClick={()=>setScale(1.15)} title="重置缩放">{Math.round(scale*100)}%</button>
          <button type="button" disabled={scale>=3} onClick={()=>setScale(s=>Math.round(Math.min(3,s+.15)*100)/100)}>＋</button>
          <button type="button" onClick={()=>setRotation(r=>(r+90)%360)} title="旋转页面">↻</button>
        </div>}
      </div>
    </div>
    {notesOpen&&<NotesPanel paperId={paper.id} fileId={fid} parseId={target} messageId={savedMessage} onClose={()=>setNotesOpen(false)} onLocate={(id,r,label)=>locateChat({...id,paper_id:paper.id,file_sha256:paper.files.find(f=>f.id===id.paper_file_id)?.sha256||''},r,label)}/>}
    {error&&<p role="alert" className="error">{error}</p>}
    <div className="paper-reader-grid" style={{gridTemplateColumns:gridCols}}>
      {showOutline?<aside className="paper-outline" aria-label="论文目录">
        <h2>论文目录</h2>
        {!activeStructure&&!busy&&<div className="parse-callout">
          <p>尚未解析结构。启动解析后可解锁章节导航、AI 精读、全文双语翻译与跨语言问答。</p>
          <div className="parse-controls">
            <select aria-label="解析模式" value={mode} onChange={e=>setMode(e.target.value)}>
              <option value="docling">Docling 深度解析（含章节/表格/公式）</option>
              <option value="native">快速原生提取（无需模型，秒级完成）</option>
            </select>
            <button className="primary" disabled={submitting} onClick={()=>void parse(false)}>立即启动解析</button>
          </div>
        </div>}
        {sections.length ? <nav aria-label="论文章节">
          {sections.map(section=><button key={section.id} type="button" aria-current={(selectedSection||sections[0]?.id)===section.id?'location':undefined}
            style={{paddingInlineStart:8+Math.max(0,Math.min(section.level-1,4))*9}}
            onClick={()=>jumpToSection(section)}>{section.title}</button>)}
        </nav> : activeStructure&&<p>当前解析模式未提取到独立章节标题。</p>}

        <details className="paper-parse-controls" open={busy} onToggle={e=>setParseOpen((e.currentTarget as HTMLDetailsElement).open)}>
          <summary>解析设置与全文查找</summary>
          <div className="parse-controls">
            <select aria-label="解析模式" value={mode} onChange={e=>setMode(e.target.value)}><option value="docling">Docling 结构解析</option><option value="native">快速原生模式</option></select>
            <label style={{fontSize:12}}><input aria-label="公式增强" type="checkbox" checked={formulas} disabled={mode!=='docling'} onChange={e=>setFormulas(e.target.checked)}/> 视觉公式识别 (CodeFormulaV2)</label>
            <button className="primary" disabled={busy||submitting} onClick={()=>void parse(false)}>启动解析</button>
            <button disabled={busy||submitting} onClick={()=>void parse(true)}>重新解析</button>
          </div>
          {job&&<div className="parse-job" role="status">状态：{job.status} · 尝试 {job.attempts}/{job.max_attempts}
            <p>{job.status==='succeeded'?'解析已完成':(job.error||job.checkpoint?.message||'等待 Worker')}</p>
            {job.status==='running'&&job.checkpoint&&<small>阶段：{job.checkpoint.stage||'处理中'}{job.checkpoint.elapsed_seconds!==undefined&&` · 已用 ${job.checkpoint.elapsed_seconds}s`}{job.checkpoint.completed_pages!==undefined&&` · ${job.checkpoint.completed_pages}页`}{job.checkpoint.completed_formulas!==undefined&&` · ${job.checkpoint.completed_formulas}公式`}</small>}
            <div className="reading-actions">
              {job.status==='failed'&&<button onClick={()=>void retry()}>重试解析</button>}
              {['queued','running'].includes(job.status)&&<button onClick={()=>void cancelParse()}>取消解析</button>}
            </div>
          </div>}
          {paper.arxiv_id&&<div className="parse-job">
            <label style={{fontSize:12}}><input aria-label="源文件优先" type="checkbox" checked={sourcePreferred} disabled={mode!=='docling'} onChange={e=>setSourcePreferred(e.target.checked)}/> 优先对齐 arXiv LaTeX 源码（100% 精确公式）</label>
            <p>{source?.status==='available'?`已绑定源码 v${source.arxiv_version}`:'可下载对应版本 TeX 源码提升公式与表格精度'}</p>
            <button disabled={!paper.files.find(f=>f.id===fid)?.arxiv_version||!!sourceJob&&['queued','running'].includes(sourceJob.status)} onClick={()=>void fetchSource()}>获取 TeX 源码</button>
          </div>}
          {runs.length>1&&<label>历史解析版本 <select aria-label="解析运行历史" value={target||''} onChange={e=>{if(leaveTranslation())setViewRun(e.target.value||null)}}><option value="">最新成功结果</option>{runs.map(r=><option key={r.id} value={r.id} disabled={r.status!=='succeeded'}>{r.parser} · {r.status} · {r.id.slice(0,8)}</option>)}</select></label>}
          <form className="search-form" onSubmit={search}><input aria-label="文件内搜索" placeholder="在 PDF 中查找关键词…" required value={query} onChange={e=>setQuery(e.target.value)}/><button disabled={searching}>查找</button></form>
          {query&&<small>{hits.length} 处匹配</small>}
          <div className="search-hits">{hits.map((h,n)=><button key={n} onClick={()=>showOriginal(h.regions,h.text)}>第 {h.page_label} 页 · {h.text.slice(0,60)}</button>)}</div>
          {parseOpen&&<StructurePanel structure={activeStructure} onLocate={showOriginal}/>}
        </details>
      </aside>:<div/>}

      <section className="paper-content" aria-label="论文正文">
        {displayMode!=='original'&&activeStructure&&<TranslationPanel key={activeStructure.run.id} structure={activeStructure} paperId={paper.id}
          bilingual={displayMode==='bilingual'} onLocate={showOriginal} onDirty={setTranslationDirty}/>}
        {displayMode==='original'&&<div className="reading-area">
          {located&&<div className="located" role="status"><span>定位：{located.slice(0,90)}</span>{regions.map((r,n)=><button key={n} onClick={()=>setPage(r.page_index+1)}>区域 {n+1} · 第 {r.page_index+1} 页</button>)}<button onClick={()=>{setRegions([]);setLocated('')}}>清除高亮</button></div>}
          {selection&&<output className="selected-text" aria-label="选中文字">已划选：{selection.text.slice(0,160)} <button type="button" onClick={()=>{setSideMode('chat');setShowReading(true)}}>针对选段提问 →</button></output>}
          <div className="pdf-stage">{doc?<PdfPage doc={doc} page={page} scale={scale} rotation={rotation} regions={regions} onSelection={setSelection} identity={{paper_file_id:fid,parse_run_id:target||'',file_sha256:paper.files.find(f=>f.id===fid)?.sha256||''}}/>:<p>正在加载 PDF…</p>}</div>
        </div>}
      </section>

      {showReading?<div className="paper-ai">
        <nav className="paper-ai-tabs" aria-label="AI 工作区">
          <button type="button" aria-pressed={sideMode==='reading'} onClick={()=>setSideMode('reading')}>AI 综合精读</button>
          {chatVisible&&<button type="button" aria-pressed={sideMode==='chat'} onClick={()=>setSideMode('chat')}>论文问答</button>}
        </nav>
        {sideMode==='reading'
          ?<ReadingPanel key={fid+':'+target} parseId={target} fileId={fid} onLocate={showOriginal} onNote={id=>{sessionStorage.setItem('note-selected-'+paper.id,id);setSavedMessage(null);setNotesOpen(true)}} compact/>
          :<ChatPanel onSaveAnswer={id=>{setSavedMessage(id);setNotesOpen(true)}} paperId={paper.id} fileId={fid} parseId={target} pageIndex={page-1} selection={selection} onClear={()=>setSelection(null)} onLocate={locateChat}/>}
      </div>:<div/>}
    </div>
  </div>;
}
