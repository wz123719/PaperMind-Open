"""Source-derived structure refinement. Original Docling blocks stay in raw evidence."""
import re
import statistics
import unicodedata
from pathlib import Path
import pymupdf as fitz
from .geometry import region
from .native_math import characters,group_lines,bounds,formatted_line,horizontal_bars
from .inline_math import fraction_candidates,display_line_candidates,merge_candidates
from .math_regions import crop_math


def source_clip(page,r):
    x0,y0,x1,y1=r['bbox'];return fitz.Rect(x0*page.rect.width,y0*page.rect.height,x1*page.rect.width,y1*page.rect.height)


def render_segments(segments):
    result=''
    for s in segments:
        if s['type']=='math':
            if s['glyphs'] and s['glyphs'][0]['c'].isspace() and result and not result[-1].isspace():result+=' '
            result+='$'+s['text']+'$'
        else:result+=s['text']
    return result


def decoded_symbol_text(page,clip,original):
    from .native_math import DINGBATS
    groups=group_lines(characters(page,clip));cs=[c for g in groups for c in sorted(g['chars'],key=lambda c:c['bbox'][0])]
    mapped=[c for c in cs if 'dingbat' in c['font'].lower() and c['glyph'] in DINGBATS and c.get('pdf_encoding_code')]
    if not mapped:return None
    def key(t):return re.sub(r'[\s“”‘’\'"`]+','',unicodedata.normalize('NFKC',t))
    raw=' '.join(''.join(chr(c['pdf_encoding_code']) if c in mapped else c['c'] for c in sorted(g['chars'],key=lambda c:c['bbox'][0])) for g in groups)
    if key(raw)!=key(original):return {'status':'unknown_source_text_conflict','glyphs':mapped}
    value=' '.join(''.join(c['token'] if c in mapped else c['c'] for c in sorted(g['chars'],key=lambda c:c['bbox'][0])) for g in groups)
    return {'status':'candidate_embedded_font_encoding','text':value,'raw_text':original,'glyphs':mapped,'verification':'unverified'}


def paragraph_text(page,clip,replacements=(),only_replacements=False):
    cs=characters(page,clip)
    for item in replacements:
        removed={(c['c'],round(c['origin'][0],3),round(c['origin'][1],3)) for c in item['glyphs']}
        originals=[c for c in cs if (c['c'],round(c['origin'][0],3),round(c['origin'][1],3)) in removed]
        if not originals:continue
        anchor=min(originals,key=lambda c:c['bbox'][0])
        cs=[c for c in cs if (c['c'],round(c['origin'][0],3),round(c['origin'][1],3)) not in removed]
        atom=dict(anchor);atom.update(c='◊',token=item['latex'],font='CM_INLINE',bbox=item['bbox'],span_text='',span=-999)
        cs.append(atom)
    if only_replacements:
        return ' '.join(''.join(('$'+c['token']+'$') if c['font']=='CM_INLINE' else c['c'] for c in sorted(g['chars'],key=lambda c:c['bbox'][0])) for g in group_lines(cs))
    return ' '.join(render_segments(formatted_line(g['chars'],horizontal_bars(page,clip))) for g in group_lines(cs))


def algorithm_steps(pdf,block,rid,next_id):
    children=[];all_lines=[];block['data'].setdefault('raw_text',block['text'])
    for r in block['regions']:
        page=pdf[r['page_index']];clip=source_clip(page,r)
        chars=characters(page,clip+(-1,-1,1,1));groups=group_lines(chars)
        starts=[]
        for g in groups:
            x=min(c['bbox'][0] for c in g['chars'] if c['c'].strip())
            if not any(abs(x-v)<2 for v in starts):starts.append(x)
        starts.sort();lines=[]
        bars=horizontal_bars(page,clip)
        for g in groups:
            cs=g['chars'];bb=bounds(cs);size=statistics.median(c['size'] for c in cs)
            bb[1]=max(bb[1],g['baseline']-size*1.05);bb[3]=min(bb[3],g['baseline']+size*.4)
            segments=formatted_line(cs,bars);indent=min(range(len(starts)),key=lambda n:abs(starts[n]-bb[0]))
            text=render_segments(segments)
            bid=f'{rid}:b{next_id:06}';next_id+=1
            math=[s['text'] for s in segments if s['type']=='math']
            child={'id':bid,'type':'algorithm_step','text':text,'reading_order':0,'section_id':block['section_id'],
                'regions':[region(r['page_index'],bb,page.rect.width,page.rect.height)],'source':'pdf_glyph_layout',
                'quality_flags':['content_unverified'],'data':{'parent_block_id':block['id'],'indent_level':indent,
                    'step_number':len(children)+1,'segments':segments,'math_latex':math,'verification':'unverified','assets':[]}}
            children.append(child);lines.append({'block_id':bid,'text':text,'indent_level':indent,'math_latex':math})
        all_lines+=lines
    if not all_lines:
        block.setdefault('quality_flags',[]).append('algorithm_native_layout_unavailable')
        return []
    block['data']['algorithm']={'source':'pdf_glyph_layout','steps':all_lines,'verification':'unverified'}
    block['text']='\n'.join('    '*l['indent_level']+l['text'] for l in all_lines)
    block['data']['children']=[c['id'] for c in children]
    return children


def refine_order(blocks):
    # Only swap an overlapping formula and its immediately following introduction,
    # when source baselines show the introduction preceding the formula itself.
    for index in range(1,len(blocks)):
        first,second=blocks[index-1:index+1]
        if first['type']!='formula' or second['type']!='text':continue
        if not re.search(r'(?i)\b(following|below)\b',second['text']):continue
        if len(first['regions'])!=1 or len(second['regions'])!=1:continue
        a,b=first['regions'][0],second['regions'][0]
        if a['page_index']==b['page_index'] and b['bbox'][1]<a['bbox'][1] and min(a['bbox'][2],b['bbox'][2])>max(a['bbox'][0],b['bbox'][0]):
            first['data']['reading_order_adjustment']={'before':second['id'],'reason':'preceding_source_introduction'}
            blocks[index-1],blocks[index]=second,first
    for index,b in enumerate(blocks):b['reading_order']=index


def refine_structure(pdf,blocks,rid,session=None,report=None,work=None):
    next_id=max((int(b['id'].split(':b')[-1]) for b in blocks),default=-1)+1
    from .algorithm_layout import recover_algorithms
    blocks,next_id=recover_algorithms(pdf,blocks,rid,next_id)
    from .reading_layout import split_metadata_body,column_order
    blocks,next_id=split_metadata_body(pdf,blocks,rid,next_id)
    result=[]
    for b in blocks:
        result.append(b)
        if b['type'] in ('text','caption','list_item') and len(b['regions'])==1:
            page=pdf[b['regions'][0]['page_index']];rotation=page.rotation;page.set_rotation(0)
            try:symbols=decoded_symbol_text(page,source_clip(page,b['regions'][0]),b['text'])
            finally:page.set_rotation(rotation)
            if symbols:
                b['data']['symbol_decoding']=symbols
                if 'text' in symbols:b['data'].setdefault('raw_text',b['text']);b['text']=symbols['text']
        if report:report({'stage':'structure_refinement','completed_blocks':len(result),'message':'细化数学、表格与来源子项：阶段内处理中'})
        if b['type']=='table' and len(b['regions'])==1:
            from .table_structure import refine_table
            refine_table(pdf[b['regions'][0]['page_index']],b)
        if b['type']=='text' and session is not None:
            new=[];rendered=[]
            for r in b['regions']:
                replacement=[]
                page=pdf[r['page_index']];rotation=page.rotation;page.set_rotation(0)
                try:
                    clip=source_clip(page,r)
                    candidates=merge_candidates(fraction_candidates(page,clip),display_line_candidates(page,clip))
                    for fraction in candidates:
                        if fraction.get('checks'):
                            b['data'].setdefault('inline_math_rejections',[]).append(fraction)
                            if 'inline_math_layout_requires_review' not in b['quality_flags']:b['quality_flags'].append('inline_math_layout_requires_review')
                            continue
                        from .local_math_backend import recognize_region
                        # This run already excludes surrounding prose and owns a
                        # complete glyph set. Do not re-query/crop a single ink
                        # band and accidentally import adjacent paragraph glyphs.
                        from PIL import Image
                        area=fitz.Rect(fraction['bbox'])+(-.7,-.7,.7,.7)
                        pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5),clip=area,alpha=False)
                        localized={'image':Image.frombytes('RGB',(pix.width,pix.height),pix.samples),'bbox':list(area),
                            'glyphs':fraction['glyphs'],'crop_evidence':{'source':'complete_inline_glyph_run','original_candidate_bbox':fraction['bbox'],'verification':'unverified'}}
                        math=recognize_region(page,localized,session)
                        bid=f'{rid}:b{next_id:06}';next_id+=1
                        new.append({'id':bid,'type':'formula','text':math['latex'],'section_id':b['section_id'],
                            'reading_order':0,'source':'pdf_math_layout+image_candidate',
                            'regions':[region(r['page_index'],localized['bbox'],page.rect.width,page.rect.height)],
                            'quality_flags':['inline_math_content_unverified'],'data':{'parent_block_id':b['id'],
                                'math':math,'role':'inline_formula','assets':[]}})
                        replacement.append({**fraction,'latex':math['latex']})
                    rendered.append(paragraph_text(page,clip,replacement,only_replacements=True))
                finally:page.set_rotation(rotation)
            if new:
                b['data'].setdefault('raw_text',b['text']);b['text']=' '.join(rendered)
                b['data']['children']=[c['id'] for c in new];b['data']['inline_math']=[c['id'] for c in new];result+=new
        if b['type']=='code':
            page=pdf[b['regions'][0]['page_index']];rotation=page.rotation;page.set_rotation(0)
            try:steps=algorithm_steps(pdf,b,rid,next_id)
            finally:page.set_rotation(rotation)
            next_id+=len(steps);result+=steps
            index=blocks.index(b)
            if index and re.match(r'(?i)^algorithm\s+\d+',blocks[index-1]['text']):
                caption=blocks[index-1]
                if caption['regions'] and caption['regions'][0]['page_index']==b['regions'][0]['page_index']:
                    page=pdf[caption['regions'][0]['page_index']];rotation=page.rotation;page.set_rotation(0)
                    try:
                        caption['data']['raw_text']=caption['text'];caption['text']=paragraph_text(page,source_clip(page,caption['regions'][0]))
                    finally:page.set_rotation(rotation)
                    caption['data']['parent_block_id']=b['id'];caption['data']['role']='algorithm_caption'
                    b['data']['caption_block_id']=caption['id'];b['data']['children'].insert(0,caption['id'])
                    b['regions']=caption['regions']+b['regions']
    by_ref={b['data'].get('docling_ref'):b for b in result if b['type']=='caption'}
    for b in result:
        captions=[by_ref[r]['text'] for r in b['data'].get('caption_refs',[]) if r in by_ref]
        if captions:b['data']['caption']=' '.join(captions)
    from .figure_structure import figure_groups
    result,removed_sections=figure_groups(pdf,result,rid,next_id)
    refine_order(result)
    result=column_order(result)
    if work is None:return result,removed_sections
    for b in result:
        if b['type'] not in ('formula','algorithm','algorithm_step','figure_panel_title') or b['data'].get('assets'):continue
        for n,r in enumerate(b['regions']):
            page=pdf[r['page_index']];rotation=page.rotation;page.set_rotation(0)
            try:
                asset=b['id'].split(':')[-1]+f'-r{n}.png'
                page.get_pixmap(matrix=fitz.Matrix(2,2),clip=source_clip(page,r)).save(Path(work)/asset)
                b['data'].setdefault('assets',[]).append(asset)
            finally:page.set_rotation(rotation)
    return result,removed_sections
