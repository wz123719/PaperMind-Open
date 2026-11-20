import type {ReactNode} from 'react';
import {safeNoteUrl,type Asset} from '../services/notes';

// Deliberately HTML-free: React escapes all text. No remote image requests, iframe or scripts.
export function MarkdownPreview({text,assets=[]}:{text:string;assets?:Asset[]}){
  function inline(value:string):ReactNode[]{
    return value.split(/(!?\[[^\]]*\]\([^)]+\)|\[\[[^\]]+\]\]|`[^`]+`|\*\*[^*]+\*\*|\$[^$\n]+\$)/g).map((t,i)=>{
      const image=/^!\[([^\]]*)\]\(([^)]+)\)$/.exec(t);
      if(image){const asset=assets.find(a=>'asset:'+a.id===image[2]);return asset?<img key={i} src={asset.url} alt={image[1]}/>:<span key={i} className="reading-caution">[图片未加载：只允许受控本地资源] {image[1]}</span>}
      const link=/^\[([^\]]*)\]\(([^)]+)\)$/.exec(t);
      if(link){const href=safeNoteUrl(link[2]);return href?<a key={i} href={href} target="_blank" rel="noreferrer">{link[1]}</a>:<span key={i}>{link[1]} [链接已阻止]</span>}
      if(t.startsWith('`')&&t.endsWith('`'))return <code key={i}>{t.slice(1,-1)}</code>;
      if(t.startsWith('**')&&t.endsWith('**'))return <strong key={i}>{t.slice(2,-2)}</strong>;
      if(t.startsWith('$')&&t.endsWith('$'))return <code className="note-math" key={i} aria-label="LaTeX公式源码">{t}</code>;
      return <span key={i}>{t}</span>;
    });
  }
  const lines=text.split('\n'),out:ReactNode[]=[];
  for(let i=0;i<lines.length;i++){
    const line=lines[i],key=i;
    if(line.startsWith('```')||line.trim()==='$$'||i===0&&line==='---'){
      const end=line.startsWith('```')?'```':line==='---'?'---':'$$',code=[];let j=i+1;
      for(;j<lines.length&&!lines[j].startsWith(end);j++)code.push(lines[j]);
      out.push(<pre key={key} className={end==='$$'?'note-math':''}><code>{end==='$$'?'$$\n'+code.join('\n')+'\n$$':code.join('\n')}</code></pre>);i=j;continue;
    }
    if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      const cells=(s:string)=>s.trim().replace(/^\||\|$/g,'').split('|').map(c=>c.trim());const rows=[];let j=i+2;
      for(;j<lines.length&&lines[j].includes('|');j++)rows.push(cells(lines[j]));
      out.push(<table key={key}><thead><tr>{cells(line).map((c,n)=><th key={n}>{inline(c)}</th>)}</tr></thead><tbody>{rows.map((row,n)=><tr key={n}>{row.map((c,m)=><td key={m}>{inline(c)}</td>)}</tr>)}</tbody></table>);i=j-1;continue;
    }
    const heading=/^(#{1,6})\s+(.*)$/.exec(line);
    if(heading){out.push(<h3 key={key}>{inline(heading[2])}</h3>);continue}
    if(/^[-*] /.test(line)){out.push(<div className="note-list-line" key={key}>• {inline(line.slice(2))}</div>);continue}
    if(line.startsWith('> ')){
      const quoted=[line.slice(2)];let j=i+1;
      while(j<lines.length&&lines[j].startsWith('> ')){quoted.push(lines[j].slice(2));j++}
      const callout=/^\[!(abstract|important)\]\s+(.+)$/.exec(quoted[0]);
      out.push(<blockquote key={key}>{callout&&<strong>{inline(callout[2])}</strong>}
        {(callout?quoted.slice(1):quoted).map((q,n)=><p key={n}>{inline(q)}</p>)}</blockquote>);i=j-1;continue
    }
    out.push(<p key={key}>{inline(line)||'\u00a0'}</p>);
  }
  return <div className="markdown-preview" aria-label="Markdown预览">{out}</div>;
}
