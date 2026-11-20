import type {Region} from './api';
export type SelectionIdentity={paper_file_id:string;parse_run_id:string;file_sha256:string};
export type PaperSelection=SelectionIdentity&{page_index:number;text:string;layer_text:string;layer_start:number;layer_end:number;client_regions:Region[]};
export function codePointOffset(text:string,utf16:number){
  if(utf16<0||utf16>text.length)return null;
  if(utf16>0&&utf16<text.length&&/[\uD800-\uDBFF]/.test(text[utf16-1])&&/[\uDC00-\uDFFF]/.test(text[utf16]))return null;
  return Array.from(text.slice(0,utf16)).length;
}
/** PDF.js represents physical line ends as BR elements, not text nodes. */
export function layerText(node:Node):string{
  if(node.nodeType===3)return node.nodeValue||'';
  if(node.nodeName==='BR')return '\n';
  return Array.from(node.childNodes).map(layerText).join('');
}
export function captureSelection(layer:HTMLElement,identity:SelectionIdentity,pageIndex:number):PaperSelection|null{
  const selected=window.getSelection();
  if(!selected||selected.rangeCount!==1||selected.isCollapsed)return null;
  const range=selected.getRangeAt(0);
  if(!layer.contains(range.startContainer)||!layer.contains(range.endContainer))return null;
  const prefix=document.createRange();prefix.selectNodeContents(layer);prefix.setEnd(range.startContainer,range.startOffset);
  const through=document.createRange();through.selectNodeContents(layer);through.setEnd(range.endContainer,range.endOffset);
  const start=Array.from(layerText(prefix.cloneContents())).length,end=Array.from(layerText(through.cloneContents())).length;
  const text=layerText(range.cloneContents()),whole=layerText(layer);
  if(!text.trim()||Array.from(whole).slice(start,end).join('')!==text)return null;
  return {...identity,page_index:pageIndex,text,layer_text:whole,layer_start:start,layer_end:end,client_regions:[]};
}
