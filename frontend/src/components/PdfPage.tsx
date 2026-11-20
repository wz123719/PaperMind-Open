import {useEffect,useRef,useState} from 'react';
import {TextLayer,type PDFDocumentProxy,type PageViewport} from 'pdfjs-dist';
import type {Region} from '../services/api';
import {regionToViewport} from '../services/coordinates';
import {captureSelection,type PaperSelection,type SelectionIdentity} from '../services/selection';
import 'pdfjs-dist/web/pdf_viewer.css';

export function PdfPage({doc,page,scale,rotation,regions,onSelection,identity}:{doc:PDFDocumentProxy;page:number;scale:number;rotation:number;regions:Region[];identity:SelectionIdentity;onSelection:(s:PaperSelection|null)=>void}){
  const canvas=useRef<HTMLCanvasElement>(null),text=useRef<HTMLDivElement>(null),shell=useRef<HTMLDivElement>(null);
  const [layout,setLayout]=useState<{view:number[];viewport:PageViewport}|null>(null),[error,setError]=useState('');
  useEffect(()=>{
    let alive=true;
    let render:ReturnType<Awaited<ReturnType<PDFDocumentProxy['getPage']>>['render']>|undefined;
    let layer:TextLayer|undefined;
    setError('');setLayout(null);
    doc.getPage(page).then(async p=>{
      if(!alive||!canvas.current||!text.current)return;
      const viewport=p.getViewport({scale,rotation:(p.rotate+rotation)%360});
      const el=canvas.current,ratio=window.devicePixelRatio||1;
      el.width=viewport.width*ratio;el.height=viewport.height*ratio;
      el.style.width=viewport.width+'px';el.style.height=viewport.height+'px';
      const container=text.current;
      container.replaceChildren();
      container.style.setProperty('--scale-factor',String(viewport.scale));
      container.style.setProperty('--total-scale-factor',String(viewport.scale));
      setLayout({view:p.view,viewport});
      render=p.render({canvas:el,canvasContext:el.getContext('2d')!,viewport,transform:[ratio,0,0,ratio,0,0]});
      await render.promise;
      if(!alive)return;
      const content=await p.getTextContent();
      if(!alive)return;
      layer=new TextLayer({textContentSource:content,container,viewport});
      await layer.render();
    }).catch(e=>{if(alive&&e.name!=='RenderingCancelledException'&&e.name!=='AbortException')setError('页面或文字层加载失败')});
    return()=>{alive=false;render?.cancel();layer?.cancel()};
  },[doc,page,scale,rotation]);
  useEffect(()=>{shell.current?.querySelector('.region-highlight')?.scrollIntoView({block:'center',inline:'center'})},[regions,layout]);
  function selected(){
    if(!text.current||!layout||!shell.current){onSelection(null);return}
    const value=captureSelection(text.current,identity,page-1);
    if(value){
      const origin=shell.current.getBoundingClientRect(),range=window.getSelection()?.getRangeAt(0);
      const [x0,y0,x1,y1]=layout.view,w=x1-x0,h=y1-y0;
      value.client_regions=Array.from(range?.getClientRects()||[]).filter(r=>r.width&&r.height).slice(0,200).map(r=>{
        const corners=[[r.left,r.top],[r.right,r.top],[r.left,r.bottom],[r.right,r.bottom]].map(([x,y])=>layout.viewport.convertToPdfPoint(x-origin.left,y-origin.top));
        const xs=corners.map(c=>(c[0]-x0)/w),ys=corners.map(c=>(y1-c[1])/h);
        return {page_index:page-1,bbox:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]};
      });
    }
    onSelection(value);
  }
  return <>{error&&<p className="error" role="alert">{error}</p>}<div ref={shell} className="page-shell" style={layout?{width:layout.viewport.width,height:layout.viewport.height}:undefined}>
    <canvas ref={canvas} aria-label={`PDF 第 ${page} 页`}/>
    <div className="highlight-layer" aria-label="定位高亮">{layout&&regions.filter(r=>r.page_index===page-1).map((r,n)=><div key={n} className="region-highlight" data-testid="region-highlight" style={regionToViewport(r,layout.view,layout.viewport)}/>)}</div>
    <div ref={text} className="textLayer" aria-label="PDF 可选文字层" onMouseUp={selected} onKeyUp={selected}/>
  </div></>;
}
