import {useEffect,useRef,useState} from 'react';
import {api,type Region} from '../services/api';
import type {PaperSelection} from '../services/selection';
import {reduceEvent,questionIssue,type Session,type Message,type Turn,type Candidate,type Identity,type StreamState} from '../services/chat';

export function ChatPanel({paperId,fileId,parseId,pageIndex,selection,onClear,onLocate,onSaveAnswer}:{onSaveAnswer?:(id:string)=>void;paperId:string;fileId:string;parseId:string|null;pageIndex:number;selection:PaperSelection|null;onClear:()=>void;onLocate:(identity:Identity,r:Region[],text:string)=>void}){
  const [sessions,setSessions]=useState<Session[]>([]),[sid,setSid]=useState(()=>sessionStorage.getItem('chat-'+paperId)||'');
  const [messages,setMessages]=useState<Message[]>([]),[question,setQuestion]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [mapping,setMapping]=useState<Candidate[]>([]),[mapped,setMapped]=useState(''),[confirmed,setConfirmed]=useState<Candidate|null>(null);
  const [reuse,setReuse]=useState<{turn:string;text:string}|null>(null);
  const [refresh,setRefresh]=useState(0),[sourceNote,setSourceNote]=useState('');
  const sidRef=useRef(sid);sidRef.current=sid;const liveSelection=useRef(selection);liveSelection.current=selection;
  const pending=useRef<{key:string;body:string}|null>(null);
  useEffect(()=>{setMapping([]);setMapped('');setConfirmed(null);if(selection)setReuse(null)},[selection,fileId,parseId]);
  useEffect(()=>{setReuse(null)},[fileId,parseId,pageIndex,sid]);
  useEffect(()=>{let live=true;void api<Session[]>(`/v1/chat-sessions?paper_id=${paperId}`).then(r=>{if(live){setSessions(r);if(sid&&!r.some(s=>s.id===sid))setSid('')}}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[paperId,refresh]);
  useEffect(()=>{sessionStorage.setItem('chat-'+paperId,sid)},[sid,paperId]);
  useEffect(()=>{
    setMessages([]);setSourceNote('');setError('');if(!sid)return;let live=true;const streams=new Map<string,EventSource>();
    function subscribe(message:Message){
      let state:StreamState={lastId:0,attempt:0,content:'',status:'draft',claims:[],error:''};
      const events=new EventSource(`/api/v1/chat-turns/${message.turn_id}/events`);streams.set(message.turn_id,events);
      ['start','delta','references','completed','failed','retrying'].forEach(kind=>events.addEventListener(kind,event=>{
        if(!live)return;const e=event as MessageEvent;const data=JSON.parse(e.data) as Record<string,unknown>;
        state=reduceEvent(state,Number(e.lastEventId),kind,data);
        setMessages(rows=>rows.map(m=>m.id===message.id?{...m,content:state.content,status:state.status,data:{...m.data,attempt:state.attempt,claims:state.claims,error:state.error,identity:state.identity,source_version:state.sourceVersion}}:m));
        if(kind==='completed'){events.close();void loadNote(message.turn_id)}
        if(kind==='failed'&&data.terminal)void api<Turn>(`/v1/chat-turns/${message.turn_id}`).then(t=>{if(t.status==='failed'){events.close();if(live)setSourceNote('本轮已失败，草稿未完成；手动重试会新增三次额度。')}});
      }));
      events.onerror=()=>{if(live)setSourceNote('连接恢复中，按事件ID继续回放；刷新不会重新发送问题。')};
    }
    async function loadNote(tid:string){const turn=await api<Turn>('/v1/chat-turns/'+tid);if(live)setSourceNote(`上一轮上下文：${turn.snapshot.retrieval.mode} · ${turn.snapshot.retrieval.hits}个来源片段 · 历史省略${turn.snapshot.history_omitted_messages}条；结论待核验`)}
    void api<Message[]>(`/v1/chat-sessions/${sid}/messages`).then(rows=>{if(!live)return;setMessages(rows);rows.filter(m=>m.role==='assistant'&&m.status==='draft').forEach(subscribe);const last=rows.filter(m=>m.role==='assistant').at(-1);if(last)void loadNote(last.turn_id)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false;streams.forEach(s=>s.close())};
  },[sid,refresh]);
  const session=sessions.find(s=>s.id===sid),mismatch=!!session&&(session.paper_file_id!==fileId||session.parse_run_id!==parseId);
  const generating=messages.some(m=>m.role==='assistant'&&m.status==='draft');
  async function map(){if(!selection||!parseId)return;const requested=selection;setError('');try{const r=await api<{status:string;candidates:Candidate[]}>(`/v1/parse-runs/${parseId}/selection-map`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(selection)});if(liveSelection.current!==requested)return;setMapping(r.candidates);setMapped(r.status);setConfirmed(null)}catch(e){setError((e as Error).message)}}
  async function newSession(){if(!parseId)return;const created=await api<Session>('/v1/chat-sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parse_run_id:parseId})});setSessions(p=>[created,...p]);setSid(created.id);return created.id}
  async function send(e:React.FormEvent){e.preventDefault();if(!parseId||!question.trim()||busy)return;setBusy(true);setError('');try{
    const issue=questionIssue(question);if(issue)throw new Error(issue);
    if(selection&&!confirmed)throw new Error('请先映射并确认选文来源，或移除选文后发送');
    const target=sid||await newSession();if(!target)return;
    const body=JSON.stringify({question,selection:selection&&confirmed?{...selection,candidate_id:confirmed.candidate_id}:null,reuse_selection_turn_id:reuse?.turn||null});
    if(!pending.current||pending.current.body!==body)pending.current={body,key:crypto.randomUUID()};
    await api<Turn>(`/v1/chat-sessions/${target}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...JSON.parse(body),idempotency_key:pending.current.key})});
    pending.current=null;setQuestion('');setRefresh(n=>n+1);
  }catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function retry(tid:string){try{await api(`/v1/chat-turns/${tid}/retry`,{method:'POST'});setRefresh(n=>n+1)}catch(e){setError((e as Error).message)}}
  return <aside className="ai-reading-panel chat-panel" aria-label="论文问答"><h2>论文问答</h2><p className="reading-caution">解析质量尚未整体通过。流式正文先作为草稿，引用匹配仍需核对论断。</p>
    <button disabled={!parseId||busy} onClick={()=>void newSession().catch(e=>setError(e.message))}>新建对话</button><label>会话历史<select aria-label="问答会话历史" value={sid} onChange={e=>{setSid(e.target.value);pending.current=null}}><option value="">选择或新建对话</option>{sessions.map(s=><option key={s.id} value={s.id}>{s.title} · {s.id.slice(0,8)}</option>)}</select></label>
    {mismatch&&<p className="reading-caution">此对话绑定另一文件/解析版本。<button onClick={()=>onLocate(session,[],'切换到对话来源')}>打开对话来源</button>切回后才可发送。</p>}
    <p>模型配置沿用“AI精读→模型服务配置”。点击发送才向配置服务提交问题、历史窗口和本轮原文片段，可能计费。</p>
    {selection?<div className="selection-card"><strong>本次附带选文 · 第{selection.page_index+1}页</strong><blockquote>{selection.text}</blockquote><button disabled={!parseId} onClick={()=>void map()}>映射选文来源</button><button onClick={()=>{onClear();setConfirmed(null)}}>移除选文</button>{mapped==='unmatched'&&<p role="alert">没有可靠匹配，请重新选择或移除；不会绑定最近块。</p>}{mapping.map((c,n)=><div key={c.candidate_id}><p>{c.preview}</p><button onClick={()=>{setConfirmed(c)}}>确认来源 {n+1}</button></div>)}{confirmed&&<p role="status">来源已确认；后续追问继续携带此选文，直到移除或切页。</p>}</div>:reuse?<div className="selection-card"><strong>本次沿用已保存选文</strong><blockquote>{reuse.text}</blockquote><button onClick={()=>setReuse(null)}>移除沿用选文</button></div>:<p>本次不附带选文，使用当前论文内关键词检索。</p>}
    {error&&<p role="alert" className="error">{error}</p>}<p className="chat-scope">{sourceNote}</p>
    <div className="chat-messages">{messages.map(m=><article className={'chat-message '+m.role} key={m.id}><strong>{m.role==='user'?'你':m.status==='completed'?'回答 · 待核验':m.status==='failed'?'失败草稿 · 未完成':`生成草稿 · 尝试${m.data.attempt||0}`}</strong>{m.role==='assistant'&&m.status==='completed'&&<small>来源校验：{m.data.source_version||'chat-source-1（旧版，未按符号保留规则复核）'}</small>}<div className="chat-body" data-message-status={m.status}>{m.content}</div>{m.role==='assistant'&&m.status==='completed'&&onSaveAnswer&&<button onClick={()=>onSaveAnswer(m.id)}>保存到笔记</button>}{m.role==='user'&&!!m.data.selection&&<button onClick={()=>{onClear();setReuse({turn:m.turn_id,text:(m.data.selection as {text:string}).text})}}>沿用这轮选文</button>}{m.data.error&&<p role="status">{m.data.error}</p>}{m.status==='failed'&&<button onClick={()=>void retry(m.turn_id)}>重试回答（新增三次额度）</button>}{m.status==='completed'&&m.data.claims?.map((c,n)=><div className="reading-claim" key={n}><small>{({fact:'论文事实',inference:'AI推断',advice:'工程建议'} as Record<string,string>)[c.kind]} · {({unreviewed:'引文匹配·待核验',unsupported:'证据不足',inferred:'推断·待核验',conflicted:'存在矛盾'} as Record<string,string>)[c.verification]}</small><p>{c.text}</p>{c.evidence.map((e,i)=><div key={i}><blockquote>{e.quote}</blockquote><button disabled={!e.matched||!m.data.identity} onClick={()=>m.data.identity&&onLocate(m.data.identity,e.regions,e.quote)}>{e.matched?'查看回答证据':'引用无法匹配'}</button></div>)}</div>)}</article>)}</div>
    <form className="chat-question" onSubmit={send}><label>问题<textarea aria-label="论文问题" required value={question} onChange={e=>setQuestion(e.target.value)} placeholder="解释选文，或询问论文中的方法与实验…"/></label><small>{Array.from(question).length}/4000个Unicode字符</small>{Array.from(question).length>4000&&<p role="alert">问题超出预算，请缩小；不会自动截断。</p>}<button className="primary" disabled={!parseId||mismatch||generating||busy||!!questionIssue(question)}>发送问题</button></form>
  </aside>;
}
