import type {Block,Region,Structure} from '../services/api';
import type {ReactNode} from 'react';

export function StructurePanel({structure,onLocate}:{structure:Structure|null;onLocate:(regions:Region[],label:string)=>void}){
  if(!structure)return <div className="structure-empty">尚无成功的结构解析。可先启动 Docling；原生模式会明确标记能力缺失。</div>;
  const byId=new Map(structure.blocks.map(b=>[b.id,b]));
  function assets(b:Block){return b.data.assets?.map(a=><a key={a} href={`/api/v1/parse-runs/${structure!.run.id}/assets/${a}`} target="_blank" rel="noreferrer">原文区域资源 ↗ </a>)}
  function children(b:Block,path:string[]=[]):ReactNode{
    if(path.includes(b.id)||path.length>3)return null;
    const items=(b.data.children||[]).map(id=>byId.get(id)).filter((v):v is Block=>!!v);
    if(!items.length)return null;
    return <details className="source-children"><summary>定位子项 · {items.length}</summary>{items.map(c=><div key={c.id} data-block-id={c.id} className="source-child"><button disabled={!c.regions.length} onClick={()=>onLocate(c.regions,c.text)}>{c.type==='algorithm_step'?c.data.step_kind==='input'?'输入':c.data.step_kind==='output'?'输出':c.data.step_kind==='input_continuation'?'输入续行':`步骤 ${c.data.source_step_number??c.data.step_number}`:c.data.role==='panel_title'?'面板标题':c.data.role==='algorithm_caption'?'算法说明':c.type==='formula'?'行内公式':'子项'} · {c.text.slice(0,160)||c.type}</button>{c.data.group_role&&c.data.group_role!=='unspecified'&&<small>分组：{c.data.group_role==='training'?'训练':c.data.group_role==='inference'?'推理':c.data.group_role} · 内容待核验</small>}{assets(c)}{children(c,[...path,b.id])}</div>)}</details>
  }
  return <><div className="parse-warning">{structure.run.parser==='native'?'原生降级 · 无表格/公式语义识别':`Docling结构 · 公式增强${structure.run.config.formulas?'开启':'关闭'}${structure.run.config.formula_backend==='pdf_math_layout+RapidLaTeXOCR'?'（字形布局 + 图像候选）':''} · 内容质量待核验`}</div>
    {structure.run.config.source&&<p className="parse-warning">已关联源文件对象 {structure.blocks.filter(b=>b.data.source_object_id).length} 个 · 内容和PDF定位均待核验</p>}
    <details open><summary>章节目录 · {structure.sections.length}</summary><div className="section-tree">{structure.sections.map(s=>{
      const regions=s.regions.length?s.regions:structure.blocks.find(b=>b.section_id===s.id&&b.regions.length)?.regions||[];
      return <button style={{paddingLeft:12+Math.min(s.level,4)*10}} key={s.id} disabled={!regions.length} onClick={()=>onLocate(regions,s.title)}>{s.title||'未命名章节'}</button>
    })}</div>{!structure.sections.length&&<p>没有识别到章节；未生成占位章节。</p>}</details>
    <details open><summary>文本与证据块 · {structure.blocks.length}</summary><div className="block-list">{structure.blocks.filter(b=>!b.data.parent_block_id).map(b=><div className="block-item" key={b.id} data-block-id={b.id}>
      <button disabled={!b.regions.length} onClick={()=>onLocate(b.regions,b.text||b.type)}><small>{b.type} · {b.regions.map(r=>r.page_index+1).join(', ')||'无定位'} 页</small><span>{b.text.slice(0,180)||b.data.caption||'无可提取文本'}</span></button>
      <small className="quality-flags">{b.quality_flags.join(' · ')}</small>
      {!!b.data.children?.length&&<button onClick={()=>onLocate(b.regions,b.text||b.type)}>定位整体</button>}
      {b.data.association_status&&<small>关联候选，待核验</small>}
      {b.data.original_object_label==='figure'&&<small>原文标为 Figure · 按表格内容组织</small>}{b.data.table_model&&<small>结构化单元格：{b.data.table_model.num_rows} 行 × {b.data.table_model.num_columns} 列，待核验</small>}
      {b.data.table_model?.cells&&<details><summary>单元格与表头关系 · 未核验</summary>{b.data.table_model.cells.map((c,n)=><div key={n}><button disabled={!c.regions.length} onClick={()=>onLocate(c.regions,c.text)}>行 {c.row+1} · 列 {c.column+1} · {c.text}</button><small>列头：{c.column_headers?.map(h=>h.text).join(' → ')||'未知'} · 行头：{c.row_headers?.map(h=>h.text).join(' → ')||'未知'} · 跨 {c.row_span} 行/{c.column_span} 列</small>{c.math_structure!==undefined&&<small>已保存数学关系树，内容仍待核验</small>}{c.boolean_value!==undefined&&<small>属性值：{c.boolean_value?'是':'否'} · 字体证据推定，未核验</small>}{c.source_cells?.map((s,i)=><small key={i}>源表：{s.file}:{s.line} · 源行{s.row+1}/列{s.column+1} · 未核验</small>)}</div>)}</details>}
      {b.data.source_table&&<details><summary>源表关联 · 未核验</summary><p>{b.data.source_table.file}:{b.data.source_table.line} · {b.data.source_table.object_id}</p><button onClick={()=>onLocate(b.regions,b.data.source_table!.object_id)}>定位源表对应区域</button><details><summary>原始源定义</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:240,overflow:'auto'}}>{b.data.source_table.raw_definition}</pre></details>{b.data.source_table.cells.map(c=><div key={c.source_cell_index}><button onClick={()=>onLocate(c.regions,c.source_text)}>源行{c.source_row+1}/列{c.source_column+1} → PDF行{c.pdf_row+1}/列{c.pdf_column+1} · {c.pdf_text}</button></div>)}{!!b.data.source_table.differences.length&&<small>{b.data.source_table.differences.length} 项源单元格差异或未知，未强制覆盖PDF主数据</small>}</details>}
      {b.data.math&&<details><summary>识别候选 · 未核验</summary>{b.data.math.candidates?.map((c,n)=><div key={n}><small>{c.source} · {c.checks?.join(' / ')||'仅语法检查'}</small><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:180,overflow:'auto'}}>{c.normalized_latex}</pre></div>)}</details>}
      {b.data.caption&&<p>Caption：{b.data.caption}</p>}
      {assets(b)}{children(b)}
    </div>)}</div></details>
  </>;
}
