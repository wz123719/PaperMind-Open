import {useEffect,useRef,useState} from 'react';
import {noteApi,NoteError,operationKey,type NoteRow,type NoteRevision,type Asset,type ExportRecord} from '../services/notes';
import {MarkdownPreview} from './MarkdownPreview';
import type {Region} from '../services/api';
import {isKnowledgeReading,readingDate} from '../services/reading';

type Reading={id:string;status:string;pipeline_version?:string;created_at?:number};
type Suggestion={changes:{section_id:string;current:string;proposed:string;diff:string}[];warning:string};
type Vault={root:string;subdir:string;revision:string|null;configured:boolean};
export function NotesPanel({paperId,fileId,parseId,messageId,onClose,onLocate}:{paperId?:string;fileId?:string;parseId?:string|null;messageId?:string|null;onClose:()=>void;onLocate?:(id:{paper_file_id:string;parse_run_id:string},r:Region[],label:string)=>void}){
  const [list,setList]=useState<NoteRow[]>([]),[rev,setRev]=useState<NoteRevision|null>(null),[sid,setSid]=useState('s05'),[text,setText]=useState('');
  const [error,setError]=useState(''),[detail,setDetail]=useState<Record<string,unknown>|null>(null),[status,setStatus]=useState(''),[busy,setBusy]=useState(false);
  const [runs,setRuns]=useState<Reading[]>([]),[reading,setReading]=useState(''),[suggestion,setSuggestion]=useState<Suggestion|null>(null),[selected,setSelected]=useState<string[]>([]);
  const [versions,setVersions]=useState<{id:string;operation:string}[]>([]),[old,setOld]=useState(''),[diff,setDiff]=useState(''),[assets,setAssets]=useState<Asset[]>([]);
  const [answer,setAnswer]=useState<{markdown:string;warning:string}|null>(null),[replace,setReplace]=useState(false),[showPreview,setShowPreview]=useState(true);
  const [evidence,setEvidence]=useState<{quote:string;source_version:string;verification:string;matched?:boolean;regions:Region[]}[]>([]);
  const [vault,setVault]=useState<Vault>({root:'',subdir:'PaperMind',revision:null,configured:false}),[plan,setPlan]=useState<ExportRecord|null>(null),[fork,setFork]=useState(false),[reviewAck,setReviewAck]=useState(false);
  const current=rev?.snapshot.sections.find(s=>s.id===sid),dirty=!!rev&&text!==current?.markdown;
  const [exports,setExports]=useState<{id:string;revision_id:string;status:string}[]>([]);
  const retry=useRef<{signature:string;key:string}|null>(null);
  const busyRef=useRef(false),operationEpoch=useRef(0),acceptedEpoch=useRef(0);
  const keyFor=(body:unknown)=>{const signature=JSON.stringify(body);if(retry.current?.signature!==signature)retry.current={signature,key:operationKey()};return retry.current!.key};
  async function refreshList(){setList(await noteApi<NoteRow[]>('/notes'+(paperId?'?paper_id='+paperId:'')))}
  function accept(r:NoteRevision){
    const token=++acceptedEpoch.current;
    function associated<T>(request:Promise<T>,save:(v:T)=>void){void request.then(v=>{if(acceptedEpoch.current===token)save(v)}).catch(e=>{if(acceptedEpoch.current===token)setError(e.message)})}
    setRev(r);setDiff('');sessionStorage.setItem('note-selected-'+(paperId||'all'),r.note_id);
    setText(r.snapshot.sections.find(s=>s.id===sid)?.markdown||'');setPlan(null);setSuggestion(null);setAnswer(null);setReviewAck(false);retry.current=null;
    setExports([]);setVersions([]);setAssets([]);setEvidence([]);
    associated(noteApi<typeof exports>(`/notes/${r.note_id}/exports`),setExports);
    associated(noteApi<typeof versions>(`/notes/${r.note_id}/revisions`),setVersions);
    associated(noteApi<Asset[]>(`/notes/${r.note_id}/assets`),setAssets);
    associated(noteApi<{evidence:typeof evidence}>(`/notes/${r.note_id}/evidence?revision_id=${r.id}`),v=>setEvidence(v.evidence));
    void refreshList().catch(e=>setError(e.message));
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
    void Promise.all([noteApi<NoteRow[]>('/notes'+(paperId?'?paper_id='+paperId:'')),noteApi<Vault>('/vault-settings'),saved?noteApi<NoteRevision>('/notes/'+saved):Promise.resolve(null)])
      .then(([rows,config,note])=>{if(live&&operationEpoch.current===token){setList(rows);setVault(config);if(note)accept(note)}})
      .catch(e=>{if(live&&operationEpoch.current===token)setError(e.message)})
      .finally(()=>{if(live&&operationEpoch.current===token){busyRef.current=false;setBusy(false)}});
    return()=>{live=false;++acceptedEpoch.current;if(operationEpoch.current===token){++operationEpoch.current;busyRef.current=false}};
  },[paperId]);
  useEffect(()=>{let live=true;setRuns([]);if(parseId)void noteApi<Reading[]>(`/parse-runs/${parseId}/reading-runs`).then(r=>{if(live)setRuns(r.filter(x=>x.status==='succeeded'&&isKnowledgeReading(x)))}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[parseId]);
  useEffect(()=>{function protect(e:BeforeUnloadEvent){if(dirty){e.preventDefault();e.returnValue=''}}window.addEventListener('beforeunload',protect);return()=>window.removeEventListener('beforeunload',protect)},[dirty]);
  function expected(){if(!rev)throw Error('请先选择笔记');return {expected_revision:rev.id}}
  async function open(id:string){if(!leave())return;const value=await noteApi<NoteRevision>('/notes/'+id);accept(value);setStatus('已载入版本 '+value.id)}
  async function save(){if(!rev)return;const b={...expected(),section_id:sid,markdown:text};const r=await noteApi<NoteRevision>(`/notes/${rev.note_id}/sections`,{...b,operation_key:keyFor(b)},'PATCH');accept(r);setStatus('已保存：'+(r.snapshot.metadata.title||'未命名论文'))}
  return <section className="notes-workspace" aria-label="知识笔记" aria-busy={busy}><fieldset className="note-operation-fields" disabled={busy}><header><h2>知识笔记</h2><button onClick={()=>{if(leave())onClose()}}>返回工作台</button></header>
    {busy&&<p role="status">操作处理中，暂时锁定编辑、章节和版本切换；失败会保留当前文字。</p>}
    <p className="reading-caution">解析质量尚未整体通过；分章导览不等于跨章综合。人工审核表示接受指定笔记版本，不改变原始证据状态。保存与导出不会调用模型。</p>
    <div className="notes-toolbar"><label>笔记列表<select aria-label="笔记列表" value={rev?.note_id||''} onChange={e=>void work(()=>open(e.target.value))}><option value="">选择笔记</option>{list.map(n=><option value={n.id} key={n.id}>{n.title||'未命名论文'}{n.created_at ? ' · '+readingDate(n.created_at) : ''}</option>)}</select></label>
    <label>成功精读运行<select aria-label="成功精读运行" value={reading} onChange={e=>setReading(e.target.value)}><option value="">空模板/不导入</option>{runs.map((r,i)=><option value={r.id} key={r.id}>{readingDate(r.created_at)||('综合精读 '+(runs.length-i))}</option>)}</select></label>
    <button disabled={!fileId||busy} onClick={()=>void work(async()=>{if(!leave())return;const b={paper_file_id:fileId,parse_run_id:parseId,reading_run_id:reading||null};const r=await noteApi<NoteRevision>('/notes',{...b,operation_key:keyFor(b)});accept(r);setStatus('草稿已创建；未审核')})}>创建笔记草稿</button></div>
    {error&&<div role="alert" className="error">{error}</div>}{detail&&Object.keys(detail).length>1&&<details open><summary>冲突内容：你的编辑仍保留，请比较并人工合并</summary>{typeof detail.local==='string'&&<><h3>你的未保存内容</h3><pre>{String(detail.local)}</pre><h3>已保存内容</h3><pre>{String(detail.remote||'')}</pre><h3>差异</h3><pre>{String(detail.diff||'')}</pre></>}<details><summary>完整冲突数据</summary><pre>{JSON.stringify(detail,null,2)}</pre></details><button onClick={()=>void work(async()=>{if(!rev)return;const local=text;const latest=await noteApi<NoteRevision>('/notes/'+rev.note_id);accept(latest);setText(local);setStatus('已取得最新基线，你的文字保留在编辑器，请人工合并后保存')})}>保留我的文字并载入最新基线</button></details>}{status&&<p role="status">{status}</p>}
    {rev&&<><p><strong>{rev.snapshot.metadata.title||'未命名论文'}</strong> · {readingDate(rev.created_at)} · {rev.reviewed?'已人工审核':'待审核'} · {dirty?'有未保存改动':'已保存'}<br/>绑定文件 {rev.note.paper_file_id} · PDF {rev.note.file_sha256.slice(0,16)} · 解析 {rev.note.parse_run_id||'无'}</p>
      <div className="notes-toolbar"><label>目标章节<select aria-label="目标章节" value={sid} onChange={e=>{if(leave()){setSid(e.target.value);setText(rev.snapshot.sections.find(s=>s.id===e.target.value)?.markdown||'');setAnswer(null)}}}>{rev.snapshot.sections.map(s=><option value={s.id} key={s.id}>{s.title}</option>)}</select></label><button disabled={busy||!dirty} onClick={()=>void work(save)}>保存章节</button><button onClick={()=>setShowPreview(v=>!v)}>{showPreview?'收起预览':'展开预览'}</button></div>
      <p>{current?.manual?'手动修改：旧引文仅保留追溯，不自动支持编辑后文字。':'来源待人工审核。'} {current?.origins.map((o,i)=><span key={i}> {o.kind} · {o.source_version} </span>)}</p>
      <div className="note-editor-grid"><textarea aria-label="章节Markdown" value={text} onChange={e=>setText(e.target.value)}/>{showPreview&&<MarkdownPreview text={text} assets={assets}/>}</div>
      <p>支持标题、段落、表格、代码围栏、链接及wikilink文本。公式以LaTeX源码保留显示；不执行HTML或危险链接，不加载远程图片。</p>
      <details><summary>本地图片与原文追溯</summary>{assets.map(a=><div key={a.id}><code>{`![图片](asset:${a.id})`}</code><img src={a.url} alt={a.name}/></div>)}<pre>{JSON.stringify(rev.snapshot.sections.flatMap(s=>s.origins),null,2)}</pre>{rev.note.parse_run_id&&onLocate&&<button onClick={()=>{if(leave()){onLocate({paper_file_id:rev.note.paper_file_id,parse_run_id:rev.note.parse_run_id!},[],'笔记绑定来源');onClose()}}}>打开笔记绑定PDF版本</button>}</details>
      <details><summary>证据定位与来源状态</summary>{evidence.map((e,i)=><div key={i}><p>{e.source_version} · {e.verification}</p><blockquote>{e.quote}</blockquote><button disabled={!e.matched||!e.regions.length||!onLocate} onClick={()=>{if(leave()&&onLocate&&rev.note.parse_run_id){onLocate({paper_file_id:rev.note.paper_file_id,parse_run_id:rev.note.parse_run_id},e.regions,e.quote);onClose()}}}>定位此笔记证据</button></div>)}</details><details><summary>已保存完整笔记预览</summary><MarkdownPreview text={rev.markdown} assets={assets}/></details>
      {messageId&&<div className="note-answer"><h3>保存完整回答到指定章节</h3><button disabled={dirty||busy} onClick={()=>void work(async()=>setAnswer(await noteApi(`/notes/${rev.note_id}/answer-preview?message_id=${messageId}`)))}>预览待保存回答</button>{answer&&<><p className="reading-caution">{answer.warning}</p><MarkdownPreview text={answer.markdown}/><label><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/>明确替换整个目标章节（默认追加）</label><button disabled={dirty||busy} onClick={()=>void work(async()=>{const b={...expected(),section_id:sid,message_id:messageId,mode:replace?'replace':'append'};accept(await noteApi(`/notes/${rev.note_id}/answers`,{...b,operation_key:keyFor(b)}));setStatus('完整回答已保存；原消息未改变')})}>确认保存完整回答</button></>}</div>}
      <details><summary>重新导入精读：只生成建议</summary><button disabled={!reading||dirty||busy} onClick={()=>void work(async()=>{setSuggestion(await noteApi(`/notes/${rev.note_id}/reading-suggestions?reading_run_id=${reading}`));setSelected([])})}>查看导入建议与差异</button>{suggestion&&<><p>{suggestion.warning}</p>{suggestion.changes.map(s=><div key={s.section_id}><label><input type="checkbox" checked={selected.includes(s.section_id)} onChange={e=>setSelected(p=>e.target.checked?[...p,s.section_id]:p.filter(x=>x!==s.section_id))}/>应用 {rev.snapshot.sections.find(x=>x.id===s.section_id)?.title}</label><pre>{s.diff}</pre></div>)}{dirty&&<p role="status">当前章节有未保存文字，请先保存再应用建议；文字与已选建议均保留，尚未发送应用请求。</p>}<button disabled={!selected.length||busy||dirty} onClick={()=>{if(dirty)return;void work(async()=>{const b={...expected(),reading_run_id:reading,section_ids:selected};accept(await noteApi(`/notes/${rev.note_id}/apply-reading`,{...b,operation_key:keyFor(b)}));setStatus('仅所选章节已应用为新版本')})}}>确认应用所选章节</button></>}</details>
      <details><summary>版本、差异与恢复</summary><label>历史版本<select aria-label="历史笔记版本" value={old} onChange={e=>setOld(e.target.value)}><option value="">选择历史版本</option>{versions.map(v=><option value={v.id} key={v.id}>{v.operation} · {v.id}</option>)}</select></label><button disabled={!old||busy} onClick={()=>void work(async()=>setDiff((await noteApi<{diff:string}>(`/notes/${rev.note_id}/diff?a=${rev.id}&b=${old}`)).diff))}>查看版本差异</button><pre>{diff}</pre><button disabled={!old||dirty||busy} onClick={()=>void work(async()=>{const b={...expected(),revision_id:old};accept(await noteApi(`/notes/${rev.note_id}/restore`,{...b,operation_key:keyFor(b)}));setStatus('已恢复为新版本；全部后续历史仍保留，需重新审核')})}>恢复为新版本</button></details>
      <section className="note-publish"><h3>审核指定版本与手动发布</h3><label>历史发布记录<select aria-label="历史发布记录" value={plan?.id||''} onChange={e=>{if(e.target.value)void work(async()=>setPlan(await noteApi('/note-exports/'+e.target.value)))}}><option value="">选择已有发布记录（中断后可重试）</option>{exports.map(x=><option value={x.id} key={x.id}>{x.status} · {x.revision_id} · {x.id}</option>)}{plan&&!exports.some(x=>x.id===plan.id)&&<option value={plan.id}>{plan.status} · {plan.id}</option>}</select></label><label><input aria-label="确认人工审核" type="checkbox" checked={reviewAck} onChange={e=>setReviewAck(e.target.checked)}/>我已查看此已保存版本，接受其中待核验/旧来源提示</label><button disabled={dirty||busy||!reviewAck} onClick={()=>void work(async()=>{accept(await noteApi(`/notes/${rev.note_id}/review`,{revision_id:rev.id,content_hash:rev.content_hash}));setStatus('仅此精确版本已人工审核')})}>审核当前版本</button>
        <details><summary>Vault设置（需已存在目录）</summary><label>Vault根目录<input aria-label="Vault根目录" value={vault.root} onChange={e=>setVault(v=>({...v,root:e.target.value}))}/></label><label>限定输出子目录<input aria-label="Vault输出子目录" value={vault.subdir} onChange={e=>setVault(v=>({...v,subdir:e.target.value}))}/></label><p>只有点击验证才创建并清理一个临时写入探测文件。保存设置和发布预览不会写入Vault。</p><button disabled={busy} onClick={()=>void work(async()=>{await noteApi('/vault-settings/validate',vault);setStatus('Vault验证成功，临时探测文件已清理')})}>验证Vault目录</button><button disabled={busy} onClick={()=>void work(async()=>{setVault(await noteApi('/vault-settings',{...vault,expected_revision:vault.revision}));setPlan(null);setStatus('Vault配置已保存；尚未发布')})}>保存Vault配置</button></details>
        <label><input type="checkbox" aria-label="保留外部文件另存" checked={fork} onChange={e=>{setFork(e.target.checked);setPlan(null)}}/>保留外部文件，另存新文件（不覆盖外部修改）</label><button disabled={!rev.reviewed||dirty||busy||!vault.configured} onClick={()=>void work(async()=>{const b={revision_id:rev.id,content_hash:rev.content_hash,fork};setPlan(await noteApi(`/notes/${rev.note_id}/export-preview`,{...b,operation_key:keyFor(b)}));setStatus('发布预览已冻结；Vault尚未写入')})}>预览发布</button>
        {plan&&<div><p>目标：{plan.plan.config.root}/{plan.plan.config.subdir}/{plan.plan.target}</p><p>冻结版本 {plan.revision_id} · {plan.status} · {plan.error}</p><ul>{plan.plan.files.map(f=><li key={f.relative}>{f.kind} · {f.relative} · {f.sha256.slice(0,16)}</li>)}</ul><details><summary>冻结发布Markdown</summary><pre>{plan.plan.markdown}</pre></details><p>首次创建；每个版本独立文件。资源不可变，上次文件外部修改会冲突。多文件包不是整体原子事务。</p><button disabled={dirty||busy||plan.status==='succeeded'} onClick={()=>void work(async()=>{setPlan(await noteApi(`/note-exports/${plan.id}/commit`,{}));setStatus('发布完成，已核对Markdown、图片与离线PDF哈希')})}>确认发布此审核版本</button><button onClick={()=>void work(async()=>setPlan(await noteApi('/note-exports/'+plan.id)))}>刷新发布结果</button><p>中断后可按此记录重试：{plan.id}</p></div>}
      </section>
    </>}
  </fieldset></section>;
}
