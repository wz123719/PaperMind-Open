import {useEffect,useRef,useState} from 'react';
import {noteApi,NoteError,operationKey,type NoteRow,type NoteRevision,type Asset,type ExportRecord} from '../services/notes';
import {MarkdownPreview} from './MarkdownPreview';
import type {Region} from '../services/api';
import {isKnowledgeReading,readingDate} from '../services/reading';

type Reading={id:string;status:string;pipeline_version?:string;created_at?:number};
type Suggestion={changes:{section_id:string;current:string;proposed:string;diff:string}[];warning:string};
type Vault={root:string;subdir:string;revision:string|null;configured:boolean};

export function NotesPanel({paperId,fileId,parseId,messageId,onClose,onLocate}:{paperId?:string;fileId?:string;parseId?:string|null;messageId?:string|null;onClose:()=>void;onLocate?:(id:{paper_file_id:string;parse_run_id:string},r:Region[],label:string)=>void}){
  const [list,setList]=useState<NoteRow[]>([]),[rev,setRev]=useState<NoteRevision|null>(null),[sid,setSid]=useState(''),[text,setText]=useState('');
  const [error,setError]=useState(''),[detail,setDetail]=useState<Record<string,unknown>|null>(null),[status,setStatus]=useState(''),[busy,setBusy]=useState(false);
  const [runs,setRuns]=useState<Reading[]>([]),[reading,setReading]=useState(''),[suggestion,setSuggestion]=useState<Suggestion|null>(null),[selected,setSelected]=useState<string[]>([]);
  const [versions,setVersions]=useState<{id:string;operation:string}[]>([]),[old,setOld]=useState(''),[diff,setDiff]=useState(''),[assets,setAssets]=useState<Asset[]>([]);
  const [answer,setAnswer]=useState<{markdown:string;warning:string}|null>(null),[replace,setReplace]=useState(false),[showPreview,setShowPreview]=useState(true),[fullPreviewOpen,setFullPreviewOpen]=useState(false);
  const [evidence,setEvidence]=useState<{quote:string;source_version:string;verification:string;matched?:boolean;regions:Region[]}[]>([]);
  const [vault,setVault]=useState<Vault>({root:'',subdir:'PaperMind',revision:null,configured:false}),[plan,setPlan]=useState<ExportRecord|null>(null),[fork,setFork]=useState(false),[reviewAck,setReviewAck]=useState(false);
  const [bundlePdf,setBundlePdf]=useState(false);
  const current=rev?.snapshot.sections.find(s=>s.id===sid),dirty=!!rev&&!!current&&text!==current.markdown;
  const [exports,setExports]=useState<{id:string;revision_id:string;status:string}[]>([]);
  const retry=useRef<{signature:string;key:string}|null>(null);
  const busyRef=useRef(false),operationEpoch=useRef(0),acceptedEpoch=useRef(0);
  const keyFor=(body:unknown)=>{const signature=JSON.stringify(body);if(retry.current?.signature!==signature)retry.current={signature,key:operationKey()};return retry.current!.key};

  async function refreshList(){setList(await noteApi<NoteRow[]>('/notes'+(paperId?'?paper_id='+paperId:'')))}
  function accept(r:NoteRevision,preferredSid?:string){
    const token=++acceptedEpoch.current;
    function associated<T>(request:Promise<T>,save:(v:T)=>void){void request.then(v=>{if(acceptedEpoch.current===token)save(v)}).catch(()=>{})}
    const targetSid=(preferredSid&&r.snapshot.sections.some(s=>s.id===preferredSid))?preferredSid:(r.snapshot.sections.some(s=>s.id===sid)?sid:(r.snapshot.sections[0]?.id||''));
    setRev(r);setSid(targetSid);setDiff('');sessionStorage.setItem('note-selected-'+(paperId||'all'),r.note_id);
    setText(r.snapshot.sections.find(s=>s.id===targetSid)?.markdown||'');setPlan(null);setSuggestion(null);setAnswer(null);setReviewAck(false);retry.current=null;
    setExports([]);setVersions([]);setAssets([]);setEvidence([]);
    associated(noteApi<typeof exports>(`/notes/${r.note_id}/exports`),setExports);
    associated(noteApi<typeof versions>(`/notes/${r.note_id}/revisions`),setVersions);
    associated(noteApi<Asset[]>(`/notes/${r.note_id}/assets`),setAssets);
    associated(noteApi<{evidence:typeof evidence}>(`/notes/${r.note_id}/evidence?revision_id=${r.id}`),v=>setEvidence(v.evidence));
    void refreshList().catch(()=>{});
  }
  async function work(fn:()=>Promise<void>){
    if(busyRef.current)return;
    const token=++operationEpoch.current;busyRef.current=true;setBusy(true);setError('');setDetail(null);
    try{await fn()}catch(e){if(operationEpoch.current===token){setError((e as Error).message);if(e instanceof NoteError)setDetail(e.detail)}}
    finally{if(operationEpoch.current===token){busyRef.current=false;setBusy(false)}}
  }
  function leave(){return !dirty||window.confirm('此章节有未保存改动。确定放弃这些改动？')}

  useEffect(()=>{
    let live=true;const token=++operationEpoch.current;busyRef.current=true;setBusy(true);
    const saved=sessionStorage.getItem('note-selected-'+(paperId||'all'));
    void Promise.all([
      noteApi<NoteRow[]>('/notes'+(paperId?'?paper_id='+paperId:'')),
      noteApi<Vault>('/vault-settings'),
      saved?noteApi<NoteRevision>('/notes/'+saved).catch(()=>null):Promise.resolve(null),
    ]).then(async([rows,config,note])=>{
      if(!live||operationEpoch.current!==token)return;
      setList(rows);setVault(config);
      if(note)accept(note);
      else if(rows[0]){const first=await noteApi<NoteRevision>('/notes/'+rows[0].id).catch(()=>null);if(live&&first)accept(first)}
    }).catch(e=>{if(live&&operationEpoch.current===token)setError(e.message)})
      .finally(()=>{if(live&&operationEpoch.current===token){busyRef.current=false;setBusy(false)}});
    return()=>{live=false;++acceptedEpoch.current;if(operationEpoch.current===token){++operationEpoch.current;busyRef.current=false}};
  },[paperId]);

  useEffect(()=>{let live=true;setRuns([]);if(parseId)void noteApi<Reading[]>(`/parse-runs/${parseId}/reading-runs`).then(r=>{if(live)setRuns(r.filter(x=>x.status==='succeeded'&&isKnowledgeReading(x)))}).catch(()=>{});return()=>{live=false}},[parseId]);
  useEffect(()=>{function protect(e:BeforeUnloadEvent){if(dirty){e.preventDefault();e.returnValue=''}}window.addEventListener('beforeunload',protect);return()=>window.removeEventListener('beforeunload',protect)},[dirty]);
  useEffect(()=>{function onKey(e:KeyboardEvent){if(e.key==='Escape'&&!dirty)onClose()}window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[dirty,onClose]);

  function expected(){if(!rev)throw Error('请先选择笔记');return {expected_revision:rev.id}}
  async function open(id:string){if(!id||!leave())return;const value=await noteApi<NoteRevision>('/notes/'+id);accept(value);setStatus('已载入笔记')}
  async function save(){if(!rev)return;const b={...expected(),section_id:sid,markdown:text};const r=await noteApi<NoteRevision>(`/notes/${rev.note_id}/sections`,{...b,operation_key:keyFor(b)},'PATCH');accept(r,sid);setStatus('章节已保存')}
  async function syncObsidian(forceOverwrite=false){
    if(!rev)return;
    const res=await noteApi<ExportRecord>(`/notes/${rev.note_id}/sync-obsidian`,{bundle_pdf:bundlePdf,force_overwrite:forceOverwrite});
    setPlan(res);
    const updated=await noteApi<NoteRevision>(`/notes/${rev.note_id}`);
    accept(updated,sid);
    setStatus(`已同步至 Obsidian 同名笔记：${res.full_path||res.plan.target}`);
  }
  async function copyMarkdown(){
    if(!rev)return;
    await navigator.clipboard.writeText(rev.markdown);
    setStatus('已复制完整 Markdown（含标准 $$ 数学块与 Callout，可直接粘贴至 Obsidian）');
  }
  async function removeNote(){
    if(!rev||!window.confirm('确定删除当前知识笔记吗？（已同步到 Obsidian 的文件不会被删除）'))return;
    await noteApi(`/notes/${rev.note_id}`,{},'DELETE');
    sessionStorage.removeItem('note-selected-'+(paperId||'all'));
    setRev(null);await refreshList();setStatus('笔记已删除');
  }

  return <section className="notes-workspace" role="dialog" aria-modal="true" aria-label="知识笔记" aria-busy={busy}>
    <fieldset className="note-operation-fields" disabled={busy}>
      <header><h2>知识笔记工作台</h2><div className="reading-actions">{rev&&<button type="button" onClick={()=>void work(copyMarkdown)}>复制完整 Markdown</button>}<button type="button" onClick={()=>{if(leave())onClose()}}>返回工作台 (Esc)</button></div></header>
      <div className="notes-toolbar">
        <label>笔记列表<select aria-label="笔记列表" value={rev?.note_id||''} onChange={e=>void work(()=>open(e.target.value))}><option value="">选择笔记…</option>{list.map(n=><option value={n.id} key={n.id}>{n.title||'未命名论文'}{n.created_at?' · '+readingDate(n.created_at):''}</option>)}</select></label>
        {fileId&&<>
          <label>导入精读报告<select aria-label="成功精读运行" value={reading} onChange={e=>setReading(e.target.value)}><option value="">空白模板</option>{runs.map((r,i)=><option value={r.id} key={r.id}>{readingDate(r.created_at)||('综合精读 '+(runs.length-i))}</option>)}</select></label>
          <button type="button" disabled={busy} onClick={()=>void work(async()=>{if(!leave())return;const b={paper_file_id:fileId,parse_run_id:parseId,reading_run_id:reading||null};const r=await noteApi<NoteRevision>('/notes',{...b,operation_key:keyFor(b)});accept(r);setStatus('笔记已创建')})}>＋ 新建笔记</button>
        </>}
        {rev&&<button type="button" disabled={busy} onClick={()=>void work(removeNote)}>删除当前笔记</button>}
      </div>
      {error&&<div role="alert" className="error">{error}{detail?.target?<div style={{marginTop:8}}><button type="button" onClick={()=>void work(()=>syncObsidian(true))}>确认覆盖更新 Obsidian 同名文件 ({String(detail.target)})</button></div>:null}</div>}
      {status&&<p role="status" className="notice">{status}</p>}

      {rev&&<>
        <section className="note-publish" style={{marginBottom:16}}>
          <h3>一键同步到 Obsidian（同名 Markdown 笔记）</h3>
          <p>自动生成与论文标题同名的 <code>{rev.snapshot.metadata.title||'未命名论文'}.md</code>，公式已规范化为标准 <code>$$...$$</code> 与 <code>$...$</code>，再次同步原地更新不破坏双链，支持 OneDrive/iCloud 同步库。</p>
          <div className="notes-toolbar">
            <button type="button" className="primary" disabled={dirty||busy||!vault.configured} onClick={()=>void work(()=>syncObsidian(false))}>
              {vault.configured?'同步同名笔记到 Obsidian':'请先在下方配置 Obsidian 库目录'}
            </button>
            <label className="checkbox-inline"><input type="checkbox" checked={bundlePdf} onChange={e=>setBundlePdf(e.target.checked)}/> 同时附带拷贝原始 PDF 到 _resources</label>
          </div>
          <details open={!vault.configured}><summary>Obsidian 库（Vault）目录设置 {vault.configured?`· 当前：${vault.root}/${vault.subdir}`:'· 未配置'}</summary>
            <div className="notes-toolbar">
              <label>Vault 根目录（本地绝对路径）<input aria-label="Vault根目录" placeholder="例如 D:\Obsidian\MyResearchVault" value={vault.root} onChange={e=>setVault(v=>({...v,root:e.target.value}))}/></label>
              <label>存放子文件夹<input aria-label="Vault输出子目录" placeholder="PaperMind" value={vault.subdir} onChange={e=>setVault(v=>({...v,subdir:e.target.value}))}/></label>
              <button type="button" disabled={busy} onClick={()=>void work(async()=>{await noteApi('/vault-settings/validate',vault);setVault(await noteApi('/vault-settings',{...vault,expected_revision:vault.revision}));setStatus('Obsidian 库目录已验证并保存')})}>验证并保存库目录</button>
            </div>
          </details>
        </section>

        <div className="notes-toolbar">
          <label>编辑章节<select aria-label="目标章节" value={sid} onChange={e=>{if(leave()){setSid(e.target.value);setText(rev.snapshot.sections.find(s=>s.id===e.target.value)?.markdown||'');setAnswer(null)}}}>{rev.snapshot.sections.map(s=><option value={s.id} key={s.id}>{s.title}</option>)}</select></label>
          <button type="button" className="primary" disabled={busy||!dirty} onClick={()=>void work(save)}>保存章节修改</button>
          <button type="button" onClick={()=>setShowPreview(v=>!v)}>{showPreview?'收起实时预览':'展开实时预览'}</button>
        </div>
        <div className="note-editor-grid">
          <textarea aria-label="章节Markdown" value={text} onChange={e=>setText(e.target.value)}/>
          {showPreview&&<MarkdownPreview text={text} assets={assets}/>}
        </div>

        <details onToggle={e=>setFullPreviewOpen((e.currentTarget as HTMLDetailsElement).open)}><summary>预览整篇完整笔记（含全部章节与公式渲染）</summary>
          {fullPreviewOpen&&<MarkdownPreview text={rev.markdown} assets={assets}/>}
        </details>

        {messageId&&<div className="note-answer"><h3>将问答结果保存到当前章节</h3><button type="button" disabled={dirty||busy} onClick={()=>void work(async()=>setAnswer(await noteApi(`/notes/${rev.note_id}/answer-preview?message_id=${messageId}`)))}>预览待保存回答</button>{answer&&<><p className="reading-caution">{answer.warning}</p><MarkdownPreview text={answer.markdown}/><label><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>替换整个章节（默认追加）</label><button type="button" disabled={dirty||busy} onClick={()=>void work(async()=>{const b={...expected(),section_id:sid,message_id:messageId,mode:replace?'replace':'append'};accept(await noteApi(`/notes/${rev.note_id}/answers`,{...b,operation_key:keyFor(b)}),sid);setStatus('回答已保存到笔记')})}>确认保存回答</button></>}</div>}

        <details><summary>高级：证据追溯、历史版本回滚与分步审核记录</summary>
          {evidence.length>0&&<div><h4>原文证据定位 ({evidence.length})</h4>{evidence.slice(0,30).map((e,i)=><div key={i}><small>{e.verification}</small><blockquote>{e.quote}</blockquote><button type="button" disabled={!e.matched||!e.regions.length||!onLocate} onClick={()=>{if(leave()&&onLocate&&rev.note.parse_run_id){onLocate({paper_file_id:rev.note.paper_file_id,parse_run_id:rev.note.parse_run_id},e.regions,e.quote);onClose()}}}>在 PDF 中定位</button></div>)}</div>}
          <div className="notes-toolbar"><label>历史版本<select aria-label="历史笔记版本" value={old} onChange={e=>setOld(e.target.value)}><option value="">选择历史版本…</option>{versions.map(v=><option value={v.id} key={v.id}>{v.operation} · {v.id.slice(0,8)}</option>)}</select></label>
            <button type="button" disabled={!old||busy} onClick={()=>void work(async()=>setDiff((await noteApi<{diff:string}>(`/notes/${rev.note_id}/diff?a=${rev.id}&b=${old}`)).diff))}>查看差异</button>
            <button type="button" disabled={!old||dirty||busy} onClick={()=>void work(async()=>{const b={...expected(),revision_id:old};accept(await noteApi(`/notes/${rev.note_id}/restore`,{...b,operation_key:keyFor(b)}));setStatus('已恢复为该历史版本')})}>恢复此版本</button>
          </div>
          {diff&&<pre>{diff}</pre>}
          <div>
            <label><input aria-label="确认人工审核" type="checkbox" checked={reviewAck} onChange={e=>setReviewAck(e.target.checked)}/>标记当前版本已人工复核</label>
            <button type="button" disabled={dirty||busy||!reviewAck} onClick={()=>void work(async()=>{accept(await noteApi(`/notes/${rev.note_id}/review`,{revision_id:rev.id,content_hash:rev.content_hash}),sid);setStatus('已标记为人工审核')})}>确认审核</button>
            <label><input type="checkbox" aria-label="保留外部文件另存" checked={fork} onChange={e=>{setFork(e.target.checked);setPlan(null)}}/>另存副本</label>
            <button type="button" disabled={!rev.reviewed||dirty||busy||!vault.configured} onClick={()=>void work(async()=>{const b={revision_id:rev.id,content_hash:rev.content_hash,fork};setPlan(await noteApi(`/notes/${rev.note_id}/export-preview`,{...b,operation_key:keyFor(b)}));setStatus('已生成冻结预览')})}>生成预览</button>
            {plan&&<button type="button" disabled={dirty||busy||plan.status==='succeeded'} onClick={()=>void work(async()=>{setPlan(await noteApi(`/note-exports/${plan.id}/commit`,{}));setStatus('分步发布完成')})}>提交预览发布</button>}
          </div>
        </details>
      </>}
    </fieldset>
  </section>;
}
