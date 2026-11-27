import {memo,type ReactNode} from 'react';
import {renderMathHtml,safeNoteUrl,type Asset} from '../services/notes';

type TextHighlight={text:string;color:string};

function renderWithHighlights(segment:string,highlights:TextHighlight[],keyPrefix:string):ReactNode{
  if(!highlights.length||segment.length<2)return <span key={keyPrefix}>{segment}</span>;
  const spans:{start:number;end:number;color:string}[]=[];
  const sorted=[...highlights].filter(h=>h.text&&h.text.trim().length>=2).sort((a,b)=>b.text.length-a.text.length);
  for(const hl of sorted){
    const needle=hl.text.trim();
    let pos=0;
    while(pos<segment.length){
      const idx=segment.indexOf(needle,pos);
      if(idx===-1)break;
      const end=idx+needle.length;
      if(!spans.some(s=>idx<s.end&&end>s.start)){
        spans.push({start:idx,end,color:hl.color});
      }
      pos=end;
    }
  }
  if(!spans.length)return <span key={keyPrefix}>{segment}</span>;
  spans.sort((a,b)=>a.start-b.start);
  const nodes:ReactNode[]=[];
  let cursor=0;
  spans.forEach((sp,idx)=>{
    if(sp.start>cursor)nodes.push(<span key={`${keyPrefix}-t-${idx}`}>{segment.slice(cursor,sp.start)}</span>);
    nodes.push(<mark key={`${keyPrefix}-h-${idx}`} className={`inline-hl hl-${sp.color}`}>{segment.slice(sp.start,sp.end)}</mark>);
    cursor=sp.end;
  });
  if(cursor<segment.length)nodes.push(<span key={`${keyPrefix}-tail`}>{segment.slice(cursor)}</span>);
  return <span key={keyPrefix}>{nodes}</span>;
}

export function InlineRichText({text,assets=[],highlights=[]}:{text:string;assets?:Asset[];highlights?:TextHighlight[]}){
  const parts=text.split(/(!?\[[^\]]*\]\([^)]+\)|\[\[[^\]]+\]\]|`[^`]+`|\*\*[^*]+\*\*|\$\$[^$\n]+\$\$|\$(?:\\.|[^$\n])+\$|\\\([^\n]+?\\\))/g);
  return <>{parts.map((t,i)=>{
    if(!t)return null;
    const image=/^!\[([^\]]*)\]\(([^)]+)\)$/.exec(t);
    if(image){
      const asset=assets.find(a=>'asset:'+a.id===image[2]);
      return asset?<img key={i} src={asset.url} alt={image[1]}/>:<span key={i} className="reading-caution">[图片未加载：只允许受控本地资源] {image[1]}</span>;
    }
    const link=/^\[([^\]]*)\]\(([^)]+)\)$/.exec(t);
    if(link){
      const href=safeNoteUrl(link[2]);
      return href?<a key={i} href={href} target="_blank" rel="noreferrer">{link[1]}</a>:<span key={i}>{link[1]} [链接已阻止]</span>;
    }
    if(t.startsWith('[[')&&t.endsWith(']]'))return <span key={i} className="obsidian-wikilink">{t}</span>;
    if(t.startsWith('`')&&t.endsWith('`'))return <code key={i}>{t.slice(1,-1)}</code>;
    if(t.startsWith('**')&&t.endsWith('**'))return <strong key={i}>{t.slice(2,-2)}</strong>;
    const isDisplay=t.startsWith('$$')&&t.endsWith('$$')&&t.length>4;
    const isParen=t.startsWith('\\(')&&t.endsWith('\\)');
    const isDollar=!isDisplay&&t.startsWith('$')&&t.endsWith('$')&&t.length>2;
    if(isDisplay||isParen||isDollar){
      const raw=isDisplay?t.slice(2,-2):isParen?t.slice(2,-2):t.slice(1,-1);
      const html=renderMathHtml(raw,isDisplay);
      return html?<span key={i} className="math-rendered" dangerouslySetInnerHTML={{__html:html}}/>:<code className="note-math" key={i}>{t}</code>;
    }
    return renderWithHighlights(t,highlights,String(i));
  })}</>;
}

export const MarkdownPreview=memo(function MarkdownPreview({text,assets=[]}:{text:string;assets?:Asset[]}){
  const inline=(value:string):ReactNode=><InlineRichText text={value} assets={assets}/>;
  const lines=text.split('\n'),out:ReactNode[]=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i],key=i;
    if(line.startsWith('```')||line.trim()==='$$'||line.trim()==='\\['||(i===0&&line==='---')){
      const isFence=line.startsWith('```'),isFront=i===0&&line==='---',isBracket=line.trim()==='\\[';
      const end=isFence?'```':isFront?'---':isBracket?'\\]':'$$',code:string[]=[];let j=i+1;
      for(;j<lines.length&&!lines[j].trim().startsWith(end);j++)code.push(lines[j]);
      if(!isFence&&!isFront){
        const body=code.join('\n');
        const html=renderMathHtml(body,true);
        out.push(html?<div key={key} className="note-math math-block" dangerouslySetInnerHTML={{__html:html}}/>:<pre key={key} className="note-math"><code>{'$$\n'+body+'\n$$'}</code></pre>);
      }else if(!isFront){
        out.push(<pre key={key}><code>{code.join('\n')}</code></pre>);
      }
      i=j;continue;
    }
    const singleMath=/^\s*\$\$(.+)\$\$\s*$/.exec(line);
    if(singleMath){
      const html=renderMathHtml(singleMath[1],true);
      out.push(html?<div key={key} className="note-math math-block" dangerouslySetInnerHTML={{__html:html}}/>:<pre key={key} className="note-math"><code>{line}</code></pre>);
      continue;
    }
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      const cells=(s:string)=>s.trim().replace(/^\||\|$/g,'').split(/(?<!\\)\|/).map(c=>c.replace(/\\\|/g,'|').trim());
      const rows:string[][]=[];let j=i+2;
      for(;j<lines.length&&lines[j].includes('|');j++)rows.push(cells(lines[j]));
      out.push(<table key={key}><thead><tr>{cells(line).map((c,n)=><th key={n}>{inline(c)}</th>)}</tr></thead><tbody>{rows.map((row,n)=><tr key={n}>{row.map((c,m)=><td key={m}>{inline(c)}</td>)}</tr>)}</tbody></table>);
      i=j-1;continue;
    }
    const heading=/^(#{1,6})\s+(.*)$/.exec(line);
    if(heading){
      const lv=heading[1].length;
      const Tag=(lv===1?'h1':lv===2?'h2':lv===3?'h3':lv===4?'h4':'h5') as 'h1'|'h2'|'h3'|'h4'|'h5';
      out.push(<Tag key={key}>{inline(heading[2])}</Tag>);continue;
    }
    if(/^[-*] /.test(line)){out.push(<div className="note-list-line" key={key}>• {inline(line.slice(2))}</div>);continue}
    const ordered=/^(\d+)\.\s+(.*)$/.exec(line);
    if(ordered){out.push(<div className="note-list-line" key={key}>{ordered[1]}. {inline(ordered[2])}</div>);continue}
    if(line.startsWith('>')&&(line.length===1||line[1]===' ')){
      const quoted=[line.slice(line.startsWith('> ')?2:1)];let j=i+1;
      while(j<lines.length&&lines[j].startsWith('>')&&(lines[j].length===1||lines[j][1]===' ')){
        quoted.push(lines[j].slice(lines[j].startsWith('> ')?2:1));j++;
      }
      const callout=/^\[!(abstract|important|note|tip|warning|quote)\]\s*(.*)$/i.exec(quoted[0]);
      out.push(<blockquote key={key} className={callout?`callout callout-${callout[1].toLowerCase()}`:''}>
        {callout&&<strong>{inline(callout[2]||callout[1])}</strong>}
        {(callout?quoted.slice(1):quoted).filter(q=>q.trim()!=='').map((q,n)=><p key={n}>{inline(q)}</p>)}
      </blockquote>);
      i=j-1;continue;
    }
    if(!line.trim()){continue}
    out.push(<p key={key}>{inline(line)}</p>);
  }
  return <div className="markdown-preview" aria-label="Markdown预览">{out}</div>;
});
