import type {Region} from './api';
export function questionIssue(text:string){return !text.trim()?'请输入问题':Array.from(text).length>4000?'问题超过4000个Unicode字符，请缩小后发送':''}
export type Identity={paper_id:string;paper_file_id:string;parse_run_id:string;file_sha256:string};
export type Session=Identity&{id:string;title:string};
export type Candidate={candidate_id:string;preview:string;regions:Region[];source:unknown[]};
export type Claim={text:string;kind:string;verification:string;evidence:{block_id:string;quote:string;matched:boolean;regions:Region[]}[]};
export type Message={id:string;session_id:string;turn_id:string;role:string;status:string;content:string;sequence:number;data:{attempt?:number;verification?:string;error?:string;retrying?:boolean;claims?:Claim[];identity?:Identity;selection?:unknown;source_version?:string}};
export type Turn={id:string;job_id:string;assistant_message_id:string;status:string;snapshot:{identity:Identity;retrieval:{mode:string;hits:number;scope?:string};history_omitted_messages:number}};
export type StreamState={lastId:number;attempt:number;content:string;status:string;claims:Claim[];error:string;identity?:Identity;sourceVersion?:string};
export function reduceEvent(state:StreamState,id:number,kind:string,data:Record<string,unknown>):StreamState{
  if(id<=state.lastId)return state;
  const attempt=Number(data.attempt);
  if(kind==='start')return {lastId:id,attempt,content:'',status:'draft',claims:[],error:''};
  if(kind==='failed'&&attempt>=state.attempt)return {...state,lastId:id,attempt,content:attempt>state.attempt?'':state.content,status:data.retrying?'draft':'failed',error:String(data.error||'生成失败')};
  if(attempt!==state.attempt)return {...state,lastId:id};
  if(kind==='delta')return {...state,lastId:id,content:state.content+String(data.text||''),status:'draft'};
  if(kind==='completed')return {...state,lastId:id,content:String(data.content||''),status:'completed',claims:data.claims as Claim[],identity:data.identity as Identity,sourceVersion:data.source_version as string,error:''};
  if(kind==='retrying')return {...state,lastId:id,status:'draft',error:'等待重试，旧草稿未核验'};
  return {...state,lastId:id};
}
