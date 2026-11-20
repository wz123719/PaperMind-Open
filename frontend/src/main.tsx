import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {api,type Paper,type Job} from './services/api';
import {Reader} from './components/Reader';
import './style.css';
import {NotesPanel} from './components/NotesPanel';
import './notes.css';
function App(){
  const [notesOpen,setNotesOpen]=useState(false);
  const [papers,setPapers]=useState<Paper[]>([]), [jobs,setJobs]=useState<Job[]>([]), [selected,setSelected]=useState<Paper|null>(null);
  const [input,setInput]=useState(''),[message,setMessage]=useState(''),[error,setError]=useState(''),[uploading,setUploading]=useState(false),[importing,setImporting]=useState(false);
  const streams=useRef(new Map<string,EventSource>());
  const restoreReader=useRef(true);
  const refresh=async()=>{const [p,j]=await Promise.all([api<Paper[]>('/papers'),api<Job[]>('/jobs')]);setPapers(p);if(restoreReader.current){restoreReader.current=false;const saved=sessionStorage.getItem('paper-reader');if(saved)setSelected(p.find(x=>x.id===saved)||null)}setJobs(j.filter(job=>job.type==='arxiv_import'))};
  useEffect(()=>{refresh().catch(e=>setError(e.message));const timer=setInterval(()=>refresh().catch(e=>setError(e.message)),5000);return()=>{clearInterval(timer);streams.current.forEach(s=>s.close())}},[]);
  useEffect(()=>{
    jobs.forEach(j=>{
      const existing=streams.current.get(j.id);
      if(['failed','succeeded'].includes(j.status)){existing?.close();streams.current.delete(j.id);return}
      if(existing)return;
      const s=new EventSource('/api/jobs/'+j.id+'/events');streams.current.set(j.id,s);
      ['queued','running','progress','succeeded','failed'].forEach(kind=>s.addEventListener(kind,()=>{
        if(kind==='succeeded'||kind==='failed'){s.close();streams.current.delete(j.id)}
        void refresh().catch(e=>setError(e.message))
      }));
      // EventSource reconnects with its last received event ID automatically.
      s.onerror=()=>{};
    });
  },[jobs]);
  async function upload(file:File){
    setUploading(true);setError('');setMessage('');
    try{const data=new FormData();data.append('file',file);const r=await api<{duplicate:boolean}>('/papers',{method:'POST',body:data});setMessage(r.duplicate?'该 PDF 已存在，已返回原记录。':'PDF 已保存到论文库。');await refresh()}catch(e){setError((e as Error).message)}finally{setUploading(false)}
  }
  async function submit(e:React.FormEvent){e.preventDefault();setImporting(true);setError('');try{await api('/papers/imports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({input})});setInput('');setMessage('导入任务已排队，关闭页面后仍会继续。');await refresh()}catch(e){setError((e as Error).message)}finally{setImporting(false)}}
  async function retry(id:string){try{await api('/jobs/'+id+'/retry',{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}}
  if(notesOpen)return <NotesPanel onClose={()=>setNotesOpen(false)}/>;
  if(selected)return <Reader paper={selected} onBack={()=>{sessionStorage.removeItem('paper-reader');setSelected(null)}}/>;
  const active=jobs.filter(j=>!['succeeded','failed'].includes(j.status)).length;
  return <div className="workspace"><aside><div className="brand"><span className="logo">P</span> PaperMind</div><span className="workspace-label">LOCAL WORKSPACE</span><div className="nav-item">▤　论文库 <span>{papers.length}</span></div><div className="aside-bottom"><i/> 本地存储 · 私有工作台<small>V1 · 导入与阅读</small></div></aside>
  <main><div className="topline"><span>工作空间 / 论文库</span><span className="badge">本地优先</span></div><section className="heading"><div><span className="eyebrow">YOUR RESEARCH, IN ONE PLACE</span><h1>论文库</h1><p>收集论文，回到原文，让研究从这里开始。</p></div><div className="counts"><strong>{papers.length}</strong><span>篇论文</span><b>{active}</b><span>项导入中</span></div></section>
  <section className="import-panel"><div><h2>添加研究资料</h2><p>上传 PDF，或从 arXiv 导入论文</p></div><div className="import-controls"><label className={'upload button '+(uploading?'disabled':'')}>{uploading?'正在上传…':'＋ 上传 PDF'}<input aria-label="上传 PDF" type="file" accept=".pdf,application/pdf" disabled={uploading} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value=''}}/></label><span className="or">或</span><form onSubmit={submit}><input aria-label="arXiv ID 或链接" placeholder="arXiv ID 或 https://arxiv.org/abs/…" value={input} onChange={e=>setInput(e.target.value)} required/><button className="primary" disabled={importing}>{importing?'提交中…':'导入论文 →'}</button></form></div><small>支持最高 50 MB 的 PDF · 相同文件自动去重 · 保留已知论文的文件版本</small></section>
  {message&&<div role="status" className="notice">{message}</div>}{error&&<div role="alert" className="error">{error}</div>}
  <button onClick={()=>setNotesOpen(true)}>全部知识笔记</button><div className="section-title"><h2>全部论文 <span>{papers.length}</span></h2><span>按添加时间排序</span></div>
  {papers.length===0?<div className="empty"><div>▤</div><h3>你的第一篇论文，从这里开始</h3><p>上传本地 PDF 或粘贴 arXiv 链接，建立自己的论文库。</p></div>:<div className="paper-list">{papers.map(p=><button className="paper-card" key={p.id} onClick={()=>{sessionStorage.setItem('paper-reader',p.id);setSelected(p)}}><div className="file-icon">PDF</div><div className="paper-info"><h3>{p.title||'未命名论文'}</h3><p>{p.authors?.join(' · ')||'作者未知'}{p.year?` · ${p.year}`:''}</p><small>{p.arxiv_id?`arXiv:${p.arxiv_id}`:p.doi?`DOI:${p.doi}`:'本地 PDF'} · {p.files[0]?.pages} 页 · {p.files.length} 个文件版本</small></div><span className="read-link">阅读 →</span></button>)}</div>}
  <div className="section-title"><h2>导入任务</h2><span>独立 Worker · 自动恢复</span></div>{jobs.length===0?<p className="muted">暂无 arXiv 导入任务。</p>:<div className="job-list">{jobs.map(j=><div className="job" key={j.id}><span className={'status '+j.status}>{({queued:'排队中',running:'导入中',succeeded:'已完成',failed:'失败'} as Record<string,string>)[j.status]}</span><div><strong>arXiv:{j.payload.canonical}</strong><p>{j.status==='succeeded'?'PDF 已保存':(j.error||j.checkpoint?.message||'等待 Worker 处理')}</p><small>尝试 {j.attempts}/{j.max_attempts}</small></div>{j.status==='failed'&&<button onClick={()=>void retry(j.id)}>重试</button>}</div>)}</div>}
  </main></div>
}
createRoot(document.getElementById('root')!).render(<App/>);
