import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import 'katex/dist/katex.min.css';
import {api,type Paper,type Job} from './services/api';
import {Reader} from './components/Reader';
import './style.css';
import {NotesPanel} from './components/NotesPanel';
import {SettingsModal} from './components/SettingsModal';
import {fetchSettingsOverview,type SettingsOverview} from './services/preferences';
import './notes.css';

function App(){
  const [notesOpen,setNotesOpen]=useState(false);
  const [settingsOpen,setSettingsOpen]=useState(false);
  const [settingsTab,setSettingsTab]=useState<'parsing'|'llm'|'tasks'|'obsidian'>('parsing');
  const [overview,setOverview]=useState<SettingsOverview|null>(null);
  const [papers,setPapers]=useState<Paper[]>([]), [jobs,setJobs]=useState<Job[]>([]), [selected,setSelected]=useState<Paper|null>(null);
  const [search,setSearch]=useState(''), [dragging,setDragging]=useState(false);
  const [input,setInput]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[uploading,setUploading]=useState(false),[importing,setImporting]=useState(false);
  const streams=useRef(new Map<string,EventSource>());
  const restoreReader=useRef(true);

  const refresh=async()=>{
    const [p,j]=await Promise.all([api<Paper[]>('/papers'),api<Job[]>('/jobs')]);
    setPapers(p);
    if(restoreReader.current){
      restoreReader.current=false;
      const saved=sessionStorage.getItem('paper-reader');
      if(saved)setSelected(p.find(x=>x.id===saved)||null);
    }
    setJobs(j.filter(job=>job.type==='arxiv_import'));
  };

  useEffect(()=>{
    if(notesOpen||selected)return;
    void refresh().catch(e=>setError(e.message));
    void fetchSettingsOverview().then(setOverview).catch(()=>{});
    const timer=setInterval(()=>void refresh().catch(()=>{}),8000);
    return()=>{clearInterval(timer);streams.current.forEach(s=>s.close());streams.current.clear()};
  },[notesOpen,selected]);

  useEffect(()=>{
    if(notesOpen||selected)return;
    jobs.forEach(j=>{
      const existing=streams.current.get(j.id);
      if(['failed','succeeded','cancelled'].includes(j.status)){existing?.close();streams.current.delete(j.id);return}
      if(existing)return;
      const s=new EventSource('/api/jobs/'+j.id+'/events');streams.current.set(j.id,s);
      ['queued','running','progress','succeeded','failed','cancelled'].forEach(kind=>s.addEventListener(kind,()=>{
        if(['succeeded','failed','cancelled'].includes(kind)){s.close();streams.current.delete(j.id)}
        void refresh().catch(e=>setError(e.message));
      }));
      s.onerror=()=>{};
    });
  },[jobs,notesOpen,selected]);

  async function upload(file:File){
    setUploading(true);setError('');setMessage('');
    try{
      const data=new FormData();data.append('file',file);
      const r=await api<{duplicate:boolean;paper:Paper}>('/papers',{method:'POST',body:data});
      if(!r.duplicate&&!r.paper.title&&file.name){
        const stem=file.name.replace(/\.pdf$/i,'').trim();
        if(stem)await api(`/papers/${r.paper.id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:stem})}).catch(()=>{});
      }
      setMessage(r.duplicate?'该 PDF 已存在，已定位原记录。':'PDF 已保存到本地论文库。');
      await refresh();
    }catch(e){setError((e as Error).message)}finally{setUploading(false)}
  }

  async function submit(e:React.FormEvent){
    e.preventDefault();setImporting(true);setError('');
    try{
      await api('/papers/imports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input})});
      setInput('');setMessage('arXiv 导入任务已启动。');await refresh();
    }catch(e){setError((e as Error).message)}finally{setImporting(false)}
  }

  async function retry(id:string){try{await api('/jobs/'+id+'/retry',{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}}
  async function cancelImport(id:string){try{await api('/jobs/'+id+'/cancel',{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}}
  async function removePaper(e:React.MouseEvent,p:Paper){
    e.stopPropagation();
    if(!window.confirm(`确定从论文库删除「${p.title||'未命名论文'}」及其本地解析缓存吗？（已同步到 Obsidian 的文件不会删除）`))return;
    try{await api('/papers/'+p.id,{method:'DELETE'});await refresh()}catch(err){setError((err as Error).message)}
  }

  if(notesOpen)return <NotesPanel onClose={()=>setNotesOpen(false)}/>;
  if(selected)return <Reader paper={selected} onBack={()=>{sessionStorage.removeItem('paper-reader');setSelected(null)}}/>;

  const active=jobs.filter(j=>!['succeeded','failed','cancelled'].includes(j.status)).length;
  const kw=search.trim().toLowerCase();
  const filtered=kw?papers.filter(p=>[p.title,p.arxiv_id,p.doi,...(p.authors||[])].some(v=>v?.toLowerCase().includes(kw))):papers;

  return <div className="workspace">
    <aside>
      <div className="brand"><span className="logo">P</span> PaperMind</div>
      <span className="workspace-label">RESEARCH DESKTOP</span>
      <button type="button" className="nav-item" style={{width:'100%',textAlign:'left',border:'none',cursor:'pointer'}}>▤　论文库 <span>{papers.length}</span></button>
      <button type="button" className="nav-item" style={{width:'100%',textAlign:'left',border:'none',cursor:'pointer',marginTop:6,background:'transparent'}} onClick={()=>setNotesOpen(true)}>✎　知识笔记库</button>
      <button type="button" className="nav-item" style={{width:'100%',textAlign:'left',border:'none',cursor:'pointer',marginTop:6,background:'transparent'}} onClick={()=>{setSettingsTab('parsing');setSettingsOpen(true)}}>⚙　全局偏好设置</button>
      <div className="aside-bottom"><i/> 本地存储 · 隐私安全<small>独立科研桌面工作台</small></div>
    </aside>
    <main>
      <div className="topline">
        <span>工作空间 / 论文库</span>
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <span className="badge">本地优先 · Obsidian 联动</span>
          <button type="button" onClick={()=>{setSettingsTab('parsing');setSettingsOpen(true)}} style={{padding:'5px 12px',fontSize:12.5,fontWeight:600}}>⚙ 全局偏好设置</button>
        </div>
      </div>
      {overview&&!overview.llm.has_saved_key&&!overview.llm.key_env&&<div className="notice" style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}>
        <span>首次使用建议先完成一次全局偏好设置（解析引擎、大模型 API 密钥、Obsidian 路径）。</span>
        <button type="button" className="primary" onClick={()=>{setSettingsTab('llm');setSettingsOpen(true)}}>⚙ 立即配置</button>
      </div>}
      {settingsOpen&&<SettingsModal initialTab={settingsTab} onClose={()=>setSettingsOpen(false)} onSaved={ov=>setOverview(ov)}/>}
      <section className="heading">
        <div><span className="eyebrow">YOUR RESEARCH, IN ONE PLACE</span><h1>论文库</h1><p>导入论文、深度精读、公式还原、一键沉淀同名 Obsidian 笔记。</p></div>
        <div className="counts"><strong>{papers.length}</strong><span>篇论文</span><b>{active}</b><span>项导入中</span></div>
      </section>
      <section className={'import-panel'+(dragging?' drag-active':'')}
        onDragOver={e=>{e.preventDefault();setDragging(true)}}
        onDragLeave={()=>setDragging(false)}
        onDrop={e=>{e.preventDefault();setDragging(false);const files=Array.from(e.dataTransfer.files).filter(f=>f.name.toLowerCase().endsWith('.pdf'));files.forEach(f=>void upload(f))}}>
        <div><h2>添加研究论文</h2><p>支持直接拖拽 PDF 到此处，或输入 arXiv 编号/链接</p></div>
        <div className="import-controls">
          <label className={'upload button '+(uploading?'disabled':'')}>{uploading?'正在上传…':'＋ 选择或拖拽 PDF'}
            <input aria-label="上传 PDF" type="file" accept=".pdf,application/pdf" multiple disabled={uploading} onChange={e=>{const fs=Array.from(e.target.files||[]);fs.forEach(f=>void upload(f));e.target.value=''}}/>
          </label>
          <span className="or">或</span>
          <form onSubmit={submit}><input aria-label="arXiv ID 或链接" placeholder="例如 2401.01234 或 https://arxiv.org/abs/…" value={input} onChange={e=>setInput(e.target.value)} required/><button className="primary" disabled={importing}>{importing?'提交中…':'arXiv 导入 →'}</button></form>
        </div>
        <small>支持最高 50 MB 的 PDF · SHA-256 自动去重 · 多通道后台并发处理</small>
      </section>
      {message&&<div role="status" className="notice">{message}</div>}{error&&<div role="alert" className="error">{error}</div>}
      <div className="section-title">
        <h2>全部论文 <span>{filtered.length}</span></h2>
        <input aria-label="搜索论文库" placeholder="搜索标题、作者、arXiv 或 DOI…" value={search} onChange={e=>setSearch(e.target.value)} style={{maxWidth:280,padding:'6px 10px',borderRadius:8,border:'1px solid #d5ded8'}}/>
      </div>
      {filtered.length===0?<div className="empty"><div>▤</div><h3>{kw?'未找到匹配的论文':'你的第一篇论文，从这里开始'}</h3><p>{kw?'请尝试更换关键词。':'拖拽本地 PDF 或粘贴 arXiv 链接，建立自己的本地研究库。'}</p></div>:<div className="paper-list">{filtered.map(p=><div className="paper-card" role="button" tabIndex={0} key={p.id} onClick={()=>{sessionStorage.setItem('paper-reader',p.id);setSelected(p)}} onKeyDown={e=>{if(e.key==='Enter'){sessionStorage.setItem('paper-reader',p.id);setSelected(p)}}}><div className="file-icon">PDF</div><div className="paper-info"><h3>{p.title||'未命名论文'}</h3><p>{p.authors?.join(' · ')||'作者待补充'}{p.year?` · ${p.year}`:''}</p><small>{p.arxiv_id?`arXiv:${p.arxiv_id}`:p.doi?`DOI:${p.doi}`:'本地 PDF'} · {p.files[0]?.pages||0} 页 · {p.files.length} 个版本</small></div><div className="reading-actions"><span className="read-link">进入精读 →</span><button type="button" title="删除论文" onClick={e=>void removePaper(e,p)} style={{padding:'4px 8px',fontSize:12}}>删除</button></div></div>)}</div>}
      {jobs.length>0&&<><div className="section-title"><h2>导入任务</h2><span>多通道并发</span></div><div className="job-list">{jobs.map(j=><div className="job" key={j.id}><span className={'status '+j.status}>{({queued:'排队中',running:'导入中',succeeded:'已完成',failed:'失败',cancelled:'已取消'} as Record<string,string>)[j.status]||j.status}</span><div><strong>arXiv:{j.payload.canonical}</strong><p>{j.status==='succeeded'?'PDF 已保存':(j.error||j.checkpoint?.message||'等待处理')}</p><small>尝试 {j.attempts}/{j.max_attempts}</small></div>{j.status==='failed'&&<button onClick={()=>void retry(j.id)}>重试</button>}{['queued','running'].includes(j.status)&&<button onClick={()=>void cancelImport(j.id)}>取消</button>}</div>)}</div></>}
    </main>
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
