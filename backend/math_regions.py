"""Localize formula ink from source glyphs; segment long additive displays by layout."""
import re
import statistics
from collections import defaultdict
from PIL import Image
import pymupdf as fitz
from .native_math import characters,bounds,horizontal_bars


def body_characters(page,clip):
    cs=characters(page,clip+(-.5,-.5,.5,.5));lines=defaultdict(list)
    for c in cs:lines[c['line']].append(c)
    body=[];labels=[]
    for line in lines.values():
        text=''.join(c['c'] for c in line).strip();bb=bounds(line)
        words=re.findall(r'[A-Za-z]{3,}',text)
        math=sum(c['font'].startswith(('CM','MSAM','MSBM')) for c in line)/len(line)
        if len(words)>4 and math<.6:continue
        if re.fullmatch(r'\(\s*\d+[a-z]?\s*\)',text) and bb[0]>clip.x0+clip.width*.7:
            labels.append({'text':text,'bbox':bb});continue
        body+=line
    return body,labels


def crop_math(page,clip,*,scale=2.5):
    cs,labels=body_characters(page,clip)
    if not cs:return None
    bb=fitz.Rect(bounds(cs)) & (clip+(-1,-1,1,1))
    source=bb+(-1,-1,1,1)
    pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=source,alpha=False)
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    gray=image.convert('L');ink=[]
    for y in range(gray.height):
        row=gray.crop((0,y,gray.width,y+1))
        if min(row.getdata())<150:ink.append(y)
    if not ink:return None
    groups=[];start=previous=ink[0]
    for y in ink[1:]:
        if y-previous>max(2,round(scale*2.2)):
            groups.append((start,previous+1));start=y
        previous=y
    groups.append((start,previous+1))
    relations=[c for c in cs if c['token'] in ('=',r'\le',r'\ge','<','>') and c['bbox'][0]<clip.x0+clip.width*.5]
    anchor=min(relations,key=lambda c:c['bbox'][0]) if relations else None
    if anchor:
        y=(anchor['origin'][1]-anchor['size']*.3)*scale-pix.y
        chosen=min(groups,key=lambda g:0 if g[0]<=y<=g[1] else min(abs(y-g[0]),abs(y-g[1])))
    else:chosen=max(groups,key=lambda g:g[1]-g[0])
    y0=max(0,chosen[0]-1);y1=min(image.height,chosen[1]+1)
    # Disconnected ink above/below a large operator is not another equation.
    # Admit only small glyphs spatially anchored to a sum/product, including
    # bounded evidence just outside a detector's original box. Do not expand
    # to whole neighboring text lines or an arbitrary larger rectangle.
    operators=[c for c in cs if c['token'] in (r'\sum',r'\prod',r'\lim',r'\max',r'\min')]
    attached=[]
    if operators:
        base=statistics.median(c['size'] for c in cs if c['c'].strip())
        baseline=anchor['origin'][1] if anchor else statistics.median(c['origin'][1] for c in cs if c['size']>=base*.9)
        nearby=characters(page,clip+(-1,-base*1.7,1,base*1.7))
        for c in nearby:
            if not c['c'].strip() or c['size']>base*.85 or abs(c['origin'][1]-baseline)>base*2:continue
            if any(abs((c['bbox'][0]+c['bbox'][2]-op['bbox'][0]-op['bbox'][2])/2)<base*1.5 for op in operators):attached.append(c)
        if attached:
            # Re-render from source so expanded limits cannot be clipped by the
            # old raster bounds. Glyph evidence still decides the precise box.
            old=fitz.Rect(pix.x/scale,(pix.y+y0)/scale,(pix.x+pix.width)/scale,(pix.y+y1)/scale)
            old|=fitz.Rect(bounds(attached))+(-.5,-.5,.5,.5)
            pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=old,alpha=False)
            image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            y0=0;y1=image.height
            seen={(c['c'],tuple(c['origin'])) for c in cs}
            cs += [c for c in attached if (c['c'],tuple(c['origin'])) not in seen]
    image=image.crop((0,y0,image.width,y1))
    rect=fitz.Rect(pix.x/scale,(pix.y+y0)/scale,(pix.x+pix.width)/scale,(pix.y+y1)/scale)
    kept=[c for c in cs if rect.y0-2<c['origin'][1]<rect.y1+2 or fitz.Rect(c['bbox']).intersects(rect)]
    return {'image':image,'bbox':list(rect),'glyphs':kept,'equation_labels':labels,
            'crop_evidence':{'operator_satellites':len(attached),'original_detector_box':list(clip),'verification':'unverified'}}


def additive_parts(page,localized):
    rect=fitz.Rect(localized['bbox']);cs=localized['glyphs']
    if rect.width/rect.height<8:return []
    relations=[c for c in cs if c['token'] in ('=',r'\le',r'\ge') and c['bbox'][0]<rect.x0+rect.width*.25]
    if not relations:return []
    relation=min(relations,key=lambda c:c['bbox'][0]);baseline=relation['origin'][1];size=relation['size']
    top=[c for c in cs if abs(c['origin'][1]-baseline)<size*.18 and c['size']>=size*.85]
    if sum(c['token'] in ('=',r'\le',r'\ge') for c in top)>1:return []
    depth=0;breaks=[]
    for c in sorted(top,key=lambda c:c['bbox'][0]):
        if c['token'] in ('(', '[','{'):depth+=1
        elif c['token'] in (')',']','}'):depth=max(0,depth-1)
        elif c['token']=='+' and depth==0 and c['bbox'][0]>relation['bbox'][2]+size:
            breaks.append(c)
    if len(breaks)<2:return []
    points=[rect.x0]+[(c['bbox'][0]+c['bbox'][2])/2 for c in breaks]+[rect.x1]
    parts=[]
    for n,(x0,x1) in enumerate(zip(points,points[1:])):
        if n:x0=breaks[n-1]['bbox'][2]+.3
        if n<len(breaks):x1=breaks[n]['bbox'][0]-.3
        part=crop_math(page,fitz.Rect(x0,rect.y0,x1,rect.y1))
        if not part:return []
        parts.append(part)
    return parts
