import {memo,useMemo} from 'react';
import type {Block, Region, TableCell} from '../services/api';
import type {Highlight} from '../services/highlights';
import {renderMathHtml} from '../services/notes';
import {InlineRichText} from './MarkdownPreview';

type Table = {cells: Pick<TableCell, 'row'|'column'|'row_span'|'column_span'|'text'>[]};
export type TranslationResult = {id:string;block_id:string;result:{text:string;status:string;reason?:string;manual?:boolean;table?:Table;terms?:{english:string;chinese:string;source_block_id:string;start:number;end:number}[]}};
export type PassageSelection = {text:string;page_index:number;regions:Region[]};

const gaps: Record<string, string> = {
  failed: '翻译失败 · 显示原文',
  needs_review: '待复核 · 显示原文',
};

export const TranslationDocument = memo(function TranslationDocument({blocks, results, parseId, status, bilingual=false, bilingualLayout='stacked', highlights=[], onSelectPassage, onHighlightClick, onEdit, onLocate}:{
  blocks:Block[]; results:TranslationResult[]; parseId:string; status:string; bilingual?:boolean; bilingualLayout?:'stacked'|'side';
  highlights?:Highlight[]; onSelectPassage?:(sel:PassageSelection|null)=>void; onHighlightClick?:(id:string|null)=>void;
  onEdit:(id:string)=>void; onLocate?:(regions:Block['regions'], label:string)=>void;
}) {
  const byBlock = useMemo(() => new Map(results.map(row => [row.block_id, row.result])), [results]);
  const byId = useMemo(() => new Map(blocks.map(b => [b.id, b])), [blocks]);
  const ordered = useMemo(() => [...blocks].sort((a, b) => a.reading_order - b.reading_order), [blocks]);
  const active = status === 'queued' || status === 'running';

  function handleSelection() {
    if (!onSelectPassage) return;
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) {
      return;
    }
    const text = sel.toString().trim();
    if (text.length < 2) return;
    const anchor = sel.anchorNode;
    const el = (anchor?.nodeType === 1 ? anchor : anchor?.parentElement) as HTMLElement | null;
    const sec = el?.closest<HTMLElement>('[data-block-id]');
    if (!sec) return;
    const bid = sec.dataset.blockId || '';
    const blk = byId.get(bid);
    const pageIndex = blk?.regions[0]?.page_index ?? 0;
    const regions = blk?.regions.length ? blk.regions : [{page_index: pageIndex, bbox: [0.05, 0.05, 0.95, 0.14] as [number,number,number,number]}];
    onSelectPassage({text: text.slice(0, 4000), page_index: pageIndex, regions});
  }

  return <article className={`translation-document${bilingual&&bilingualLayout==='side'?' side-by-side':''}`} aria-label="连续译文" onMouseUp={handleSelection} onKeyUp={handleSelection}>
    {ordered.map(block => {
      const result = byBlock.get(block.id);
      const translated = result?.status === 'translated' || result?.manual;
      const text = translated ? result.text : block.text;
      const gap = result?.manual ? '人工修改 · 待复核' : result ? gaps[result.status] : active ? '等待翻译 · 显示原文' : '暂无译文 · 显示原文';
      const isFigure = ['figure', 'picture', 'image'].includes(block.type);
      const isEquation = block.type === 'formula' || block.type === 'equation';
      const isAlgorithm = block.type === 'algorithm' || block.type === 'algorithm_step' || block.type === 'code' || result?.reason === 'algorithm_box_kept_as_pseudocode';
      const assets = isFigure || isEquation || isAlgorithm ? block.data.assets || [] : [];
      const table = result?.table || block.data.table_model;
      const origCellMap = new Map<string, string>();
      for (const c of block.data.table_model?.cells || []) {
        origCellMap.set(`${c.row}:${c.column}`, c.text);
      }
      const tableRows = new Map<number, Table['cells']>();
      for (const cell of table?.cells || []) {
        const row = tableRows.get(cell.row) || [];
        row.push(cell);
        tableRows.set(cell.row, row);
      }

      const heading = ['title','heading','section_header'].includes(block.type);
      const page = block.regions[0]?.page_index;
      const eqHtml = isEquation ? renderMathHtml(text, true) : null;
      const isParallelProse = bilingual && translated && !heading && !isFigure && !isEquation && !isAlgorithm && !tableRows.size && !['code','table'].includes(block.type) && !!block.text && !!text;
      return <section className={`translation-passage${isEquation?' equation-passage':''}${isParallelProse?' parallel-prose':''}`} key={block.id} id={`reader-block-${block.id}`} data-block-id={block.id}>
        {isParallelProse ? <div className="bilingual-pair">
          <div className="parallel-original" lang="en">
            <small>Original{page===undefined?'':` · Page ${page+1}`}</small>
            <p><InlineRichText text={block.text} highlights={highlights} onHighlightClick={onHighlightClick}/></p>
          </div>
          <div className="parallel-translated">
            <small className="parallel-label">中文译文{page===undefined?'':` · 第 ${page+1} 页`}</small>
            <p><InlineRichText text={text} highlights={highlights} onHighlightClick={onHighlightClick}/></p>
          </div>
        </div> : <>
          {bilingual && translated && !heading && !isFigure && !tableRows.size && block.text && <div className="parallel-original" lang="en">
            <small>Original{page===undefined?'':` · Page ${page+1}`}</small><p><InlineRichText text={block.text} highlights={highlights} onHighlightClick={onHighlightClick}/></p>
          </div>}
          {bilingual && translated && !heading && !isFigure && <small className="parallel-label">中文译文{page===undefined?'':` · 第 ${page+1} 页`}</small>}
          {gap && !isEquation && !isFigure && !isAlgorithm && <small className="translation-gap">{gap}</small>}
          {assets.map(asset => <img key={asset} loading="lazy" alt={isEquation ? block.text : isAlgorithm ? '算法伪代码原图' : block.data.caption || '原文插图'}
            src={`/api/v1/parse-runs/${encodeURIComponent(parseId)}/assets/${encodeURIComponent(asset)}`}/>)}
          {!isAlgorithm && tableRows.size > 0 ? <div className="translation-table"><table><tbody>
            {[...tableRows].sort(([a], [b]) => a-b).map(([row, cells]) => <tr key={row}>
              {cells.sort((a,b) => a.column-b.column).map(cell => <td key={cell.column}
                rowSpan={cell.row_span || 1} colSpan={cell.column_span || 1}>
                {bilingual && translated && <span className="parallel-cell-original">{origCellMap.get(`${cell.row}:${cell.column}`)}</span>}
                <InlineRichText text={cell.text}/>
              </td>)}
            </tr>)}
          </tbody></table></div> : block.type === 'title' ? <h3>{bilingual?block.text:text}</h3>
            : heading ? <h4>{bilingual?block.text:text}</h4>
            : isEquation ? <div className="equation-block">
                {eqHtml ? <div className="math-block" dangerouslySetInnerHTML={{__html: eqHtml}}/> : <pre>{text}</pre>}
                <details><summary>LaTeX 公式源码</summary><pre>{text}</pre></details>
              </div>
            : isAlgorithm && assets.length ? <details><summary>算法伪代码文本</summary><pre>{text}</pre></details>
            : isAlgorithm || ['code','table'].includes(block.type) ? <pre>{text}</pre>
            : text && <p><InlineRichText text={text} highlights={highlights} onHighlightClick={onHighlightClick}/></p>}
        </>}
        {gap && !isEquation && !isFigure && !isAlgorithm && <button type="button" className="translation-gap-action" onClick={() => onEdit(block.id)}>查看此处</button>}
        {bilingual && page!==undefined && onLocate && <button type="button" className="parallel-locate" onClick={()=>onLocate(block.regions,block.text || '原文位置')}>原文定位 · 第 {page+1} 页</button>}
      </section>;
    })}
  </article>;
});
