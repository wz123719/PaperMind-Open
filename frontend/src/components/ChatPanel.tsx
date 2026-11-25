import {useEffect,useRef,useState} from 'react';
import {api,type Region} from '../services/api';
import type {PaperSelection} from '../services/selection';
import {reduceEvent,questionIssue,type Session,type Message,type Turn,type Candidate,type Identity,type StreamState} from '../services/chat';
import {InlineRichText} from './MarkdownPreview';

export function ChatPanel({paperId,fileId,parseId,pageIndex,selection,onClear,onLocate,onSaveAnswer}:{onSaveAnswer?:(id:string)=>void;paperId:string;fileId:string;parseId:string|null;pageIndex:number;selection:PaperSelection|null;onClear:()=>void;onLocate:(identity:Identity,r:Region[],text:string)=>void}){
  const [sessions,setSessions]=useState<Session[]>([]),[sid,setSid]=useState(()=>sessionStorage.getItem('chat-'+paperId)||'');
  const [messages,setMessages]=useState<Message[]>([]),[question,setQuestion]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [mapping,setMapping]=useState<Candidate[]>([]),[mapped,setMapped]=useState(''),[confirmed,setConfirmed]=useState<Candidate|null>(null);
  const [reuse,setReuse]=useState<{turn:string;text:string}|null>(null);
  const [refresh,setRefresh]=useState(0),[sourceNote,setSourceNote]=useState('');
  const sidRef=useRef(sid);const prevSid=useRef(sid);sidRef.current=sid;
  const liveSelection=useRef(selection);liveSelection.current=selection;
  const pending=useRef<{key:string;body:string}|null>(null);

  useEffect(()=>{
    setMapping([]);setMapped('');setConfirmed(null);
    if(!selection||!parseId)return;
    setReuse(null);
    const requested=selection;
    void api<{status:string;candidates:Candidate[]}>(`/v1/parse-runs/${parseId}/selection-map`,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection),
    }).then(r=>{
      if(liveSelection.current!==requested)return;
      setMapping(r.candidates);setMapped(r.status);
      if(r.candidates.length===1)setConfirmed(r.candidates[0]);
    }).catch(()=>{});
  },[selection,fileId,parseId]);

  useEffect(()=>{setReuse(null)},[fileId,parseId,pageIndex,sid]);
  useEffect(()=>{let live=true;void api<Session[]>(`/v1/chat-sessions?paper_id=${paperId}`).then(r=>{if(live){setSessions(r);if(sid&&!r.some(s=>s.id===sid))setSid('')}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[paperId,refresh]);
  useEffect(()=>{sessionStorage.setItem('chat-'+paperId,sid)},[sid,paperId]);

  useEffect(()=>{
    if(prevSid.current!==sid){setMessages([]);setSourceNote('');prevSid.current=sid}
    setError('');if(!sid)return;let live=true;const streams=new Map<string,EventSource>();
    function subscribe(message:Message){
      let state:StreamState={lastId:0,attempt:0,content:'',status:'draft',claims:[],error:''};
      const events=new EventSource(`/api/v1/chat-turns/${message.turn_id}/events`);streams.set(message.turn_id,events);
      ['start','delta','references','completed','failed','retrying'].forEach(kind=>events.addEventListener(kind,event=>{
        if(!live)return;
        try{
          const e=event as MessageEvent;const data=JSON.parse(e.data) as Record<string,unknown>;
          state=reduceEvent(state,Number(e.lastEventId),kind,data);
          setMessages(rows=>rows.map(m=>m.id===message.id?{...m,content:state.content,status:state.status,data:{...m.data,attempt:state.attempt,claims:state.claims,error:state.error,identity:state.identity,source_version:state.sourceVersion}}:m));
          if(kind==='completed'){events.close();void loadNote(message.turn_id)}
          if(kind==='failed'&&data.terminal)void api<Turn>(`/v1/chat-turns/${message.turn_id}`).then(t=>{if(t.status==='failed'){events.close();if(live)setSourceNote('本轮已失败，草稿未完成；手动重试会新增三次额度。')}}).catch(()=>{});
        }catch{}
      }));
      events.onerror=()=>{if(live)setSourceNote('流式连接重连中…')};
    }
    async function loadNote(tid:string){
      try{const turn=await api<Turn>('/v1/chat-turns/'+tid);if(live)setSourceNote(`检索模式：${turn.snapshot.retrieval.mode} · 命中 ${turn.snapshot.retrieval.hits} 处原文片段`)}catch{}
    }
    void api<Message[]>(`/v1/chat-sessions/${sid}/messages`).then(rows=>{if(!live)return;setMessages(rows);rows.filter(m=>m.role==='assistant'&&m.status==='draft').forEach(subscribe);const last=rows.filter(m=>m.role==='assistant').at(-1);if(last)void loadNote(last.turn_id)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false;streams.forEach(s=>s.close())};
  },[sid,refresh]);

  const session=sessions.find(s=>s.id===sid),mismatch=!!session&&(session.paper_file_id!==fileId||session.parse_run_id!==parseId);
  const generating=messages.some(m=>m.role==='assistant'&&m.status==='draft');
  async function map(){if(!selection||!parseId)return;const requested=selection;setError('');try{const r=await api<{status:string;candidates:Candidate[]}>(`/v1/parse-runs/${parseId}/selection-map`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection)});if(liveSelection.current!==requested)return;setMapping(r.candidates);setMapped(r.status);setConfirmed(r.candidates.length===1?r.candidates[0]:null)}catch(e){setError((e as Error).message)}}
  async function newSession(){if(!parseId)return;const created=await api<Session>('/v1/chat-sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parse_run_id:parseId})});setSessions(p=>[created,...p]);setSid(created.id);return created.id}
  async function send(e:React.FormEvent){e.preventDefault();if(!parseId||!question.trim()||busy)return;setBusy(true);setError('');try{
    const issue=questionIssue(question);if(issue)throw new Error(issue);
    if(selection&&!confirmed)throw new Error('选文存在多处候选或未能匹配，请确认候选来源或点击「移除选文」后发送');
    const target=sid||await newSession();if(!target)return;
    const body=JSON.stringify({question,selection:selection&&confirmed?{...selection,candidate_id:confirmed.candidate_id}:null,reuse_selection_turn_id:reuse?.turn||null});
    if(!pending.current||pending.current.body!==body)pending.current={body,key:crypto.randomUUID()};
    await api<Turn>(`/v1/chat-sessions/${target}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...JSON.parse(body),idempotency_key:pending.current.key})});
    pending.current=null;setQuestion('');setRefresh(n=>n+1);
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function retry(tid:string){try{await api(`/v1/chat-turns/${tid}/retry`,{method:'POST'});setRefresh(n=>n+1)}catch(e){setError((e as Error).message)}}
  const qLen=Array.from(question).length;

  return <aside className="ai-reading-panel chat-panel" aria-label="论文问答">
    <div className="reading-actions"><button disabled={!parseId||busy} onClick={()=>void newSession().catch(e=>setError(e.message))}>＋ 新建对话</button>
      {sessions.length>0&&<select aria-label="问答会话历史" value={sid} onChange={e=>{setSid(e.target.value);pending.current=null}}><option value="">切换历史对话…</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.title}</option>)}</select>}
    </div>
    {mismatch&&<p className="reading-caution">此对话绑定另一解析版本。<button onClick={()=>onLocate(session,[],'切换到对话来源')}>切回对应版本</button></p>}
    {selection?<div className="selection-card"><strong>附带第 {selection.page_index+1} 页划词选文</strong><blockquote>{selection.text.slice(0,220)}</blockquote>
      <div className="reading-actions">
        {confirmed?<span className="badge">已自动绑定原文区域</span>:<button type="button" disabled={!parseId} onClick={()=>void map()}>重新匹配来源</button>}
        <button type="button" onClick={()=>{onClear();setConfirmed(null)}}>移除选文</button>
      </div>
      {mapped==='unmatched'&&<p role="alert">未能精确匹配解析块，可移除选文直接用跨语言全文检索提问。</p>}
      {mapping.length>1&&mapping.map((c,n)=><div key={c.candidate_id}><p>{c.preview.slice(0,100)}</p><button type="button" onClick={()=>setConfirmed(c)}>{confirmed?.candidate_id===c.candidate_id?'✓ 已选来源':'选择来源 '+(n+1)}</button></div>)}
    </div>:reuse?<div className="selection-card"><strong>沿用已存选文</strong><blockquote>{reuse.text.slice(0,180)}</blockquote><button type="button" onClick={()=>setReuse(null)}>取消沿用</button></div>:<p className="chat-scope">支持直接用中文询问英文论文（自动跨语言学术术语扩展 + FTS5 检索）。</p>}
    {error&&<p role="alert" className="error">{error}</p>}{sourceNote&&<p className="chat-scope">{sourceNote}</p>}
    <div className="chat-messages">{messages.map(m=><article className={'chat-message '+m.role} key={m.id}>
      <strong>{m.role==='user'?'你':m.status==='completed'?'回答 · 附原文溯源':m.status==='failed'?'生成失败':`正在生成…`}</strong>
      <div className="chat-body" data-message-status={m.status}>{m.content.split('\n').map((ln,idx)=>ln.trim()?<p key={idx}><InlineRichText text={ln}/></p>:null)}</div>
      <div className="reading-actions">
        {m.role==='assistant'&&m.status==='completed'&&onSaveAnswer&&<button onClick={()=>onSaveAnswer(m.id)}>保存到笔记</button>}
        {m.role==='user'&&!!m.data.selection&&<button onClick={()=>{onClear();setReuse({turn:m.turn_id,text:(m.data.selection as {text:string}).text})}}>沿用此轮选文</button>}
        {m.status==='failed'&&<button onClick={()=>void retry(m.turn_id)}>重试回答</button>}
      </div>
      {m.data.error&&<p role="status" className="error">{m.data.error}</p>}
      {m.status==='completed'&&m.data.claims?.map((c,n)=><div className="reading-claim" key={n}>
        <small>{({fact:'论文事实',inference:'AI推断',advice:'工程建议'} as Record<string,string>)[c.kind]} · {({unreviewed:'引文已核对',unsupported:'证据不足',inferred:'推断结论',conflicted:'存在矛盾'} as Record<string,string>)[c.verification]}</small>
        <p><InlineRichText text={c.text}/></p>
        {c.evidence.filter(e=>e.matched).map((e,i)=><button key={i} title={e.quote} disabled={!m.data.identity} onClick={()=>m.data.identity&&onLocate(m.data.identity,e.regions,e.quote)}>定位原文证据{i>0?' '+(i+1):''}</button>)}
      </div>)}
    </article>)}</div>
    <form className="chat-question" onSubmit={send}>
      <textarea aria-label="论文问题" rows={3} required value={question} onChange={e=>setQuestion(e.target.value)} placeholder="直接用中文提问，例如：本文的核心架构和损失函数是什么？消融实验验证了哪些模块？"/>
      <div className="reading-actions"><small>{qLen}/4000</small><button className="primary" disabled={!parseId||mismatch||generating||busy||!!questionIssue(question)}>发送问题</button></div>
    </form>
  </aside>;
}
