"""Embedded compound panels: labels + caption references + actual ink gutters."""
import re
from PIL import Image
import pymupdf as fitz
from .native_math import characters,group_lines,bounds
from .geometry import region

def clip(page,r):
    b=r['bbox'];return fitz.Rect(b[0]*page.rect.width,b[1]*page.rect.height,b[2]*page.rect.width,b[3]*page.rect.height)

def title_parts(page,block):
    cs=[]
    for r in block['regions']:
        for line in group_lines(characters(page,clip(page,r))):cs+=sorted(line['chars'],key=lambda c:c['bbox'][0])
    text=''.join(c['c'] for c in cs)
    markers=list(re.finditer(r'\(([a-z])\)',text))
    if len(markers)<2 or len(markers)>6 or [m[1] for m in markers]!=[chr(97+i) for i in range(len(markers))]:return []
    out=[]
    for i,m in enumerate(markers):
        end=markers[i+1].start() if i+1<len(markers) else len(text)
        part=cs[m.start():end]
        if len(re.findall(r'[A-Za-z]{2,}',text[m.end():end]))<2:return []
        out.append({'label':m[1],'text':text[m.start():end].strip(),'glyphs':part,'bbox':bounds(part)})
    return out

def panel_rectangles(page,rect,parts):
    centers=[(p['bbox'][0]+p['bbox'][2])/2 for p in parts]
    if centers!=sorted(centers) or any(not rect.x0<x<rect.x1 for x in centers):return []
    scale=min(2,2000/max(rect.width,rect.height));pix=page.get_pixmap(matrix=fitz.Matrix(scale,scale),clip=rect,alpha=False)
    image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
    empty=[]
    for x in range(image.width):
        if all(min(pixel)>=245 for pixel in image.crop((x,0,x+1,image.height)).getdata()):empty.append((pix.x+x)/scale)
    cuts=[]
    for a,b in zip(centers,centers[1:]):
        middle=(a+b)/2;options=[x for x in empty if abs(x-middle)<(b-a)*.22]
        if not options:return []
        cut=min(options,key=lambda x:abs(x-middle));cuts.append(cut)
    xs=[rect.x0]+cuts+[rect.x1]
    return [fitz.Rect(a,rect.y0,b,rect.y1) for a,b in zip(xs,xs[1:])]


def internal_title_parts(page,picture):
    rect=clip(page,picture['regions'][0]);candidates=[]
    for line in group_lines(characters(page,rect)):
        cs=sorted(line['chars'],key=lambda c:c['bbox'][0]);text=''.join(c['c'] for c in cs)
        markers=list(re.finditer(r'\(([a-z])\)',text))
        if not 2<=len(markers)<=6 or [m[1] for m in markers]!=[chr(97+i) for i in range(len(markers))]:continue
        if line['baseline']<rect.y0+rect.height*.65:continue
        parts=[]
        for i,m in enumerate(markers):
            end=markers[i+1].start() if i+1<len(markers) else len(text);own=cs[m.start():end]
            parts.append({'label':m[1],'text':text[m.start():end].strip(),'glyphs':own,'bbox':bounds(own)})
        candidates.append(parts)
    return candidates[0] if len(candidates)==1 else []


def caption_panel_labels(text):
    labels=set()
    for m in re.finditer(r'\(\s*([a-z](?:\s*[,;]\s*[a-z])*)\s*\)',text):
        labels.update(re.findall(r'[a-z]',m[1]))
    return labels

def embedded_panel_groups(pdf,blocks,rid,next_id):
    result=list(blocks)
    for picture in blocks:
        if picture['type']!='picture' or picture['data'].get('parent_block_id') or len(picture['regions'])!=1:continue
        rr=picture['regions'][0];pi=rr['page_index'];page=pdf[pi]
        following=[b for b in blocks if b['reading_order']>picture['reading_order'] and len(b['regions'])==1
                   and b['regions'][0]['page_index']==pi and b['regions'][0]['bbox'][1]>=rr['bbox'][3]-.002
                   and min(b['regions'][0]['bbox'][2],rr['bbox'][2])>max(b['regions'][0]['bbox'][0],rr['bbox'][0])]
        following.sort(key=lambda b:b['reading_order'])
        # Require adjacent panel-title evidence then the unique figure caption.
        rotation=page.rotation;page.set_rotation(0)
        try:internal=internal_title_parts(page,picture)
        finally:page.set_rotation(rotation)
        if internal and following and following[0]['type']=='caption':band=None;caption=following[0]
        else:
            if len(following)<2:continue
            band,caption=following[:2]
            if band['type'] not in ('text','list_item') or caption['type']!='caption':continue
        match=re.match(r'(?i)^Figure\s+(\d+)\s*[:.]',caption['text'])
        if not match:continue
        competing=[b for b in following if b is not caption and b['type']=='caption'
            and abs(b['regions'][0]['bbox'][1]-caption['regions'][0]['bbox'][1])<.01]
        if competing:
            picture['data']['association_status']='unknown_competing_captions';continue
        rotation=page.rotation;page.set_rotation(0)
        try:
            parts=internal if band is None else title_parts(page,band)
            if not parts:continue
            number=match[1]
            if not all(p['label'] in caption_panel_labels(caption['text']) for p in parts):continue
            # Other figures/captions or body text in the same band make it unknown.
            intervening=[b for b in blocks if b not in (picture,band,caption) and len(b['regions'])==1 and b['regions'][0]['page_index']==pi
                and rr['bbox'][3]<=b['regions'][0]['bbox'][1]<caption['regions'][0]['bbox'][1]
                and min(b['regions'][0]['bbox'][2],rr['bbox'][2])>max(b['regions'][0]['bbox'][0],rr['bbox'][0])]
            if intervening:
                picture['data']['association_status']='unknown_intervening_objects';continue
            panel_clip=clip(page,rr)
            if band is None:panel_clip.y1=min(p['bbox'][1] for p in parts)-.5
            rects=panel_rectangles(page,panel_clip,parts)
            if len(rects)!=len(parts):
                picture['data']['association_status']='unknown_panel_partition';continue
            def bid():
                nonlocal next_id
                value=f'{rid}:b{next_id:06}';next_id+=1;return value
            gid=bid();panels=[];titles=[]
            for p,rect in zip(parts,rects):
                pid,tid=bid(),bid()
                titles.append({'id':tid,'type':'figure_panel_title','text':p['text'],'reading_order':band['reading_order'] if band else picture['reading_order'],
                    'section_id':picture['section_id'],'regions':[region(pi,p['bbox'],page.rect.width,page.rect.height)],
                    'source':'pdf_panel_label_glyphs','quality_flags':['figure_relation_unverified'],
                    'data':{'parent_block_id':pid,'role':'panel_title','label':p['label'],'glyphs':p['glyphs'],'assets':[]}})
                panels.append({'id':pid,'type':'figure_panel','text':p['text'],'reading_order':picture['reading_order'],
                    'section_id':picture['section_id'],'regions':[region(pi,list(rect),page.rect.width,page.rect.height)],
                    'source':'pdf_ink_gutter_partition','quality_flags':['figure_relation_unverified'],
                    'data':{'parent_block_id':picture['id'],'role':'panel','label':p['label'],'children':[tid],'assets':[],'verification':'unverified'}})
            picture['data'].update(parent_block_id=gid,children=[p['id'] for p in panels],caption=caption['text'])
            for b in (band,caption):
                if b:b['data']['parent_block_id']=gid
            group={'id':gid,'type':'figure_group','text':caption['text'],'reading_order':picture['reading_order'],
                'section_id':picture['section_id'],'regions':[r for p in panels+titles+[caption] for r in p['regions']],
                'source':'label_caption_ink_relations','quality_flags':['figure_relation_unverified'],
                'data':{'children':[picture['id']]+([band['id']] if band else [])+[caption['id']],'panels':[p['id'] for p in panels],
                    'caption':caption['text'],'caption_block_id':caption['id'],'association_status':'candidate',
                    'association_evidence':{'panel_labels':[p['label'] for p in parts],'caption_number':number,
                        'title_band_id':band['id'] if band else picture['id'],'title_location':'external' if band else 'inside_picture','partition':'source_raster_empty_gutters','no_intervening_objects':True},
                    'assets':picture['data'].get('assets',[]),'verification':'unverified'}}
            result.insert(result.index(picture),group);result.extend(panels+titles)
        finally:page.set_rotation(rotation)
    return result
