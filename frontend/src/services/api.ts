export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const r=await fetch('/api'+path,{...init,headers:{'X-PaperMind-Client':'workspace',...init?.headers}});
  const body=await r.json().catch(()=>{throw new Error('服务响应不完整，请确认 API 正在运行后重试')});
  if(!r.ok)throw new Error(typeof body.detail==='string'?body.detail:'请求失败，请检查输入');
  return body as T;
}
export type PaperFile={id:string;version:number;arxiv_version:number|null;pages:number;size:number;sha256:string;source:string};
export type Paper={id:string;title:string|null;authors:string[]|null;year:number|null;arxiv_id:string|null;doi:string|null;files:PaperFile[]};
export type Job={id:string;type:string;status:string;attempts:number;max_attempts:number;error:string|null;payload:{canonical?:string};checkpoint:{message?:string;stage?:string;elapsed_seconds?:number;stage_elapsed_seconds?:number;completed_pages?:number;completed_formulas?:number}|null;result:{paper_id?:string}|null};
export type Region={page_index:number;bbox:[number,number,number,number]};
export type SourceStatus={status:string;reason?:string;archive_sha256?:string;arxiv_id?:string;arxiv_version?:number;objects?:number;url?:string};
export type ParseRun={id:string;job_id:string;paper_file_id:string;status:string;parser:string;parser_version:string;config:{formulas:boolean;formula_backend?:string;source_preferred?:boolean;source?:SourceStatus};created_at:number;error:string|null;warnings:string[];pages:PageInfo[]|null};
export type PageInfo={page_index:number;page_label:string;rotation:number;pdf_view:number[];width_points:number;height_points:number};
export type Section={id:string;parent_id:string|null;title:string;level:number;reading_order:number;regions:Region[]};
export type SourceCell={source_object_id:string;file:string;line:number;cell_index:number;row:number;column:number;raw_text:string;verification:string};
export type TableCell={row:number;column:number;row_span:number;column_span:number;text:string;regions:Region[];column_headers?:{text:string}[];row_headers?:{text:string}[];math_latex?:string;math_structure?:unknown;source_cells?:SourceCell[];boolean_value?:boolean;symbol_status?:string};
export type SourceTable={object_id:string;file:string;line:number;raw_definition:string;expanded_definition:string;mapping_status:string;verification:string;differences:{source_cell_index:number;raw_text:string;status:string}[];cells:{source_cell_index:number;source_row:number;source_column:number;source_text:string;pdf_text:string;pdf_row:number;pdf_column:number;regions:Region[]}[]};
export type Block={id:string;section_id:string|null;type:string;text:string;reading_order:number;regions:Region[];source:string;quality_flags:string[];data:{assets?:string[];caption?:string|null;references?:{kind:string;target_block_id:string}[];children?:string[];parent_block_id?:string;role?:string;step_number?:number;source_step_number?:number|null;step_kind?:string;indent_level?:number;group_role?:string;original_object_label?:string;association_status?:string;source_object_id?:string;source_table?:SourceTable;math?:{source?:string;check_status?:string;verification?:string;candidates?:{source?:string;normalized_latex?:string;checks?:string[];source_file?:string;source_line?:number}[]};table_model?:{num_rows:number;num_columns:number;source:string;cells?:TableCell[]}}};
export type Structure={run:ParseRun;sections:Section[];blocks:Block[]};
