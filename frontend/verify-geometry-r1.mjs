import fs from 'node:fs';
import assert from 'node:assert/strict';
import {getDocument} from 'pdfjs-dist/legacy/build/pdf.mjs';
import {regionToViewport} from './src/services/coordinates.ts';

const refs=JSON.parse(fs.readFileSync('../evidence/v2/geometry-annotations.json','utf8'));
const data=new Uint8Array(fs.readFileSync('../storage/qa-inputs/geometry.pdf'));
const task=getDocument({data,useSystemFonts:true});
const doc=await task.promise;
let checks=0;
for(const r of refs){
  const page=await doc.getPage(r.page_index+1);
  for(const scale of [.6,1,1.4,2])for(const extraRotation of [0,90,180,270]){
    const angle=(page.rotate+extraRotation)%360;
    const viewport=page.getViewport({scale,rotation:angle});
    const actual=regionToViewport(r,page.view,viewport);
    const [x0,y0,x1,y1]=r.bbox;
    const w=(page.view[2]-page.view[0])*scale,h=(page.view[3]-page.view[1])*scale;
    const expected=angle===0?[x0*w,y0*h,(x1-x0)*w,(y1-y0)*h]:
      angle===90?[(1-y1)*h,x0*w,(y1-y0)*h,(x1-x0)*w]:
      angle===180?[(1-x1)*w,(1-y1)*h,(x1-x0)*w,(y1-y0)*h]:
      [y0*h,(1-x1)*w,(y1-y0)*h,(x1-x0)*w];
    ['left','top','width','height'].forEach((k,n)=>assert.ok(Math.abs(actual[k]-expected[n])<1e-6,`${r.id} ${angle} ${scale} ${k}`));
    checks++;
  }
}
await task.destroy();
const result={authored_regions:refs.length,automatic_transform_checks:checks,
  scales:[.6,1,1.4,2],embedded_rotations:[0,90,180,270],viewer_rotations:[0,90,180,270],
  cropboxes:2,result:'passed',semantic_quality:'not measured by geometry tests'};
fs.writeFileSync('../evidence/v2-r1/pdfjs-geometry.json',JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
