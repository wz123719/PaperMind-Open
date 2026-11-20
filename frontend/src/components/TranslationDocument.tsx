import type {Block, TableCell} from '../services/api';

type Table = {cells: Pick<TableCell, 'row'|'column'|'row_span'|'column_span'|'text'>[]};
export type TranslationResult = {id:string;block_id:string;result:{text:string;status:string;reason?:string;manual?:boolean;table?:Table;terms?:{english:string;chinese:string;source_block_id:string;start:number;end:number}[]}};

const gaps: Record<string, string> = {
  failed: '翻译失败 · 显示原文',
  needs_review: '待复核 · 显示原文',
};

export function TranslationDocument({blocks, results, parseId, status, bilingual=false, onEdit, onLocate}:{
  blocks:Block[]; results:TranslationResult[]; parseId:string; status:string; bilingual?:boolean;
  onEdit:(id:string)=>void; onLocate?:(regions:Block['regions'], label:string)=>void;
}) {
  const byBlock = new Map(results.map(row => [row.block_id, row.result]));
  const ordered = [...blocks].sort((a, b) => a.reading_order - b.reading_order);
  const active = status === 'queued' || status === 'running';

  return <article className="translation-document" aria-label="连续译文">
    {ordered.map(block => {
      const result = byBlock.get(block.id);
      const translated = result?.status === 'translated' || result?.manual;
      const text = translated ? result.text : block.text;
      const gap = result?.manual ? '人工修改 · 待复核' : result ? gaps[result.status] : active ? '等待翻译 · 显示原文' : '暂无译文 · 显示原文';
      const isFigure = ['figure', 'picture', 'image'].includes(block.type);
      const isEquation = block.type === 'formula' || block.type === 'equation';
      const assets = isFigure || isEquation ? block.data.assets || [] : [];
      const table = result?.table || block.data.table_model;
      const tableRows = new Map<number, Table['cells']>();
      for (const cell of table?.cells || []) {
        const row = tableRows.get(cell.row) || [];
        row.push(cell);
        tableRows.set(cell.row, row);
      }

      const heading = ['title','heading','section_header'].includes(block.type);
      const page = block.regions[0]?.page_index;
      return <section className={`translation-passage${isEquation?' equation-passage':''}`} key={block.id} id={`reader-block-${block.id}`}>
        {bilingual && translated && !heading && !isFigure && !tableRows.size && block.text && <div className="parallel-original" lang="en">
          <small>Original{page===undefined?'':` · Page ${page+1}`}</small><p>{block.text}</p>
        </div>}
        {bilingual && translated && !heading && !isFigure && <small className="parallel-label">中文译文{page===undefined?'':` · 第 ${page+1} 页`}</small>}
        {gap && <small className="translation-gap">{gap}</small>}
        {assets.map(asset => <img key={asset} loading="lazy" alt={isEquation ? block.text : block.data.caption || '原文插图'}
          src={`/api/v1/parse-runs/${encodeURIComponent(parseId)}/assets/${encodeURIComponent(asset)}`}/>)}
        {tableRows.size > 0 ? <div className="translation-table"><table><tbody>
          {[...tableRows].sort(([a], [b]) => a-b).map(([row, cells]) => <tr key={row}>
            {cells.sort((a,b) => a.column-b.column).map(cell => <td key={cell.column}
              rowSpan={cell.row_span || 1} colSpan={cell.column_span || 1}>
              {bilingual && translated && <span className="parallel-cell-original">{block.data.table_model?.cells?.find(original=>original.row===cell.row&&original.column===cell.column)?.text}</span>}
              {cell.text}
            </td>)}
          </tr>)}
        </tbody></table></div> : block.type === 'title' ? <h3>{bilingual?block.text:text}</h3>
          : heading ? <h4>{bilingual?block.text:text}</h4>
          : isEquation && assets.length ? <details><summary>公式源码</summary><pre>{text}</pre></details>
          : isEquation || ['code','table'].includes(block.type) ? <pre>{text}</pre>
          : text && <p>{text}</p>}
        {gap && <button type="button" className="translation-gap-action" onClick={() => onEdit(block.id)}>查看此处</button>}
        {bilingual && page!==undefined && onLocate && <button type="button" className="parallel-locate" onClick={()=>onLocate(block.regions,block.text || '原文位置')}>原文定位 · 第 {page+1} 页</button>}
      </section>;
    })}
  </article>;
}
