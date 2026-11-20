import type {PageViewport} from 'pdfjs-dist';
import type {Region} from './api';

/** Normalized unrotated CropBox/top-left -> PDF user space -> PDF.js viewport.
 * /Rotate, CropBox offsets, UserUnit and zoom are applied by the viewport once.
 */
export function regionToViewport(region:Region,view:readonly number[],viewport:Pick<PageViewport,'convertToViewportRectangle'>){
  const [x0,y0,x1,y1]=region.bbox;
  const w=view[2]-view[0],h=view[3]-view[1];
  const pdf=[view[0]+x0*w,view[3]-y1*h,view[0]+x1*w,view[3]-y0*h];
  const [a,b,c,d]=viewport.convertToViewportRectangle(pdf);
  return {left:Math.min(a,c),top:Math.min(b,d),width:Math.abs(c-a),height:Math.abs(d-b)};
}
