"""Bounded physical rule evidence, including monochrome inline-image rules."""
import pymupdf as fitz

def rule_segments(page,clip):
    result=[]
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]=='l':
                a,b=item[1:3]
                if abs(a.y-b.y)<.3 and abs(a.x-b.x)>3:
                    result.append({'bbox':[min(a.x,b.x),min(a.y,b.y)-.2,max(a.x,b.x),max(a.y,b.y)+.2],'axis':'horizontal','source':'vector_line'})
                elif abs(a.x-b.x)<.3 and abs(a.y-b.y)>3:
                    result.append({'bbox':[min(a.x,b.x)-.2,min(a.y,b.y),max(a.x,b.x)+.2,max(a.y,b.y)],'axis':'vertical','source':'vector_line'})
            elif item[0]=='re':
                r=item[1]
                if r.height<=1 and r.width>3:result.append({'bbox':list(r),'axis':'horizontal','source':'vector_rectangle'})
                elif r.width<=1 and r.height>3:result.append({'bbox':list(r),'axis':'vertical','source':'vector_rectangle'})
                elif r.width>=100 and r.height>35:
                    for bb,axis in [([r.x0,r.y0-.2,r.x1,r.y0+.2],'horizontal'),([r.x0,r.y1-.2,r.x1,r.y1+.2],'horizontal'),
                                    ([r.x0-.2,r.y0,r.x0+.2,r.y1],'vertical'),([r.x1-.2,r.y0,r.x1+.2,r.y1],'vertical')]:
                        result.append({'bbox':bb,'axis':axis,'source':'vector_closed_rectangle'})
    # Some DVI/Ghostscript PDFs encode rules as stretched 1-bit 1x1 masks.
    # Reject photos, multi-pixel scans, large rectangles and white/empty masks.
    for info in page.get_image_info():
        if (info.get('width'),info.get('height'),info.get('bpc'),info.get('colorspace'))!=(1,1,1,0):continue
        r=fitz.Rect(info['bbox']);axis='horizontal' if r.height<=1 and r.width>3 else 'vertical' if r.width<=1 and r.height>3 else None
        if axis is None or not r.intersects(clip) or r.width<=0 or r.height<=0:continue
        inset=r+(.05,.05,-.05,-.05)
        if inset.is_empty:continue
        pix=page.get_pixmap(matrix=fitz.Matrix(4,4),clip=inset,colorspace=fitz.csGRAY,alpha=False)
        if not pix.samples or sum(v<180 for v in pix.samples)/len(pix.samples)<.5:continue
        result.append({'bbox':list(r),'axis':axis,'source':'monochrome_1bit_inline_mask','image_number':info['number'],'image_dimensions':[1,1]})
    return [r for r in result if fitz.Rect(r['bbox']).intersects(clip)]
