import katex from 'katex';

export type NoteSection={id:string;title:string;markdown:string;manual:boolean;origins:{kind:string;source_version:string}[]};
export type NoteRow={id:string;title:string|null;created_at?:number;paper_file_id:string;parse_run_id:string|null;current_revision:string};
export type NoteRevision={id:string;note_id:string;parent_id:string|null;content_hash:string;reviewed:boolean;operation:string;created_at:number;markdown:string;note:{paper_file_id:string;parse_run_id:string|null;file_sha256:string;current_revision:string};snapshot:{metadata:{title:string|null};identity:Record<string,unknown>;sections:NoteSection[];warnings:string[]}};
export type Asset={id:string;name:string;url:string};
export type ExportRecord={id:string;status:string;error:string|null;revision_id:string;full_path?:string;plan:{target:string;markdown:string;markdown_hash:string;warnings:string[];files:{relative:string;sha256:string;kind:string}[];config:{root:string;subdir:string}}};
export class NoteError extends Error {constructor(public detail:Record<string,unknown>){super(String(detail.message||'请求失败'))}}
export async function noteApi<T>(path:string,body?:unknown,method='POST'):Promise<T>{
  const response=await fetch('/api/v1'+path,{method:body===undefined?'GET':method,headers:{'X-PaperMind-Client':'workspace','Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  let data:Record<string,unknown>={};
  try{data=(await response.json()) as Record<string,unknown>}catch{throw new NoteError({message:`服务响应无效 (HTTP ${response.status})`})}
  if(!response.ok){throw new NoteError(data.detail&&typeof data.detail==='object'&&!Array.isArray(data.detail)?(data.detail as Record<string,unknown>):{message:typeof data.detail==='string'?data.detail:'请求失败'})}
  return data as T;
}
export const operationKey=()=>crypto.randomUUID();
export function safeNoteUrl(url:string){return /^(https?:\/\/|mailto:|#)/i.test(url)&&!/[\u0000-\u0020]/.test(url)?url:null}
export function renderMathHtml(latex:string,displayMode=false):string|null{
  const trimmed=(latex||'').trim();if(!trimmed)return null;
  try{return katex.renderToString(trimmed,{displayMode,throwOnError:false,strict:'ignore',trust:false,output:'htmlAndMathml'})}catch{return null}
}
