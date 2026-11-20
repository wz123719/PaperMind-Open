"""Algorithm regions require caption + closed physical box + step evidence."""
import re,statistics
import pymupdf as fitz
from .pdf_rules import rule_segments
from .native_math import characters,bounds,layout_latex,horizontal_bars,is_math,group_lines
from .geometry import region

def boxed_algorithms(page):
    captions=[]
    for b in page.get_text('dict')['blocks']:
        for line in b.get('lines',[]):
            text=''.join(s['text'] for s in line['spans']).strip()
            if re.match(r'^Algorithm\s+\d+\s*[:.]',text,re.I):captions.append((fitz.Rect(line['bbox']),text))
    if not captions:return []
    rules=rule_segments(page,page.rect);h=[fitz.Rect(r['bbox']) for r in rules if r['axis']=='horizontal'];v=[fitz.Rect(r['bbox']) for r in rules if r['axis']=='vertical']
    results=[]
    for cap,text in captions:
        candidates=[]
        for bottom in h:
            if not -3<=cap.y0-bottom.y1<=18 or bottom.width<100 or bottom.x0>cap.x0+20:continue
            for top in h:
                if not 35<bottom.y0-top.y0<page.rect.height*.7 or abs(top.x0-bottom.x0)>2 or abs(top.x1-bottom.x1)>2:continue
                if not all(any(abs(side.x0-edge)<2 and side.y0<=top.y1+1 and side.y1>=bottom.y0-1 for side in v) for edge in (top.x0,top.x1)):continue
                rect=fitz.Rect(top.x0,top.y0,bottom.x1,bottom.y1)
                raw=page.get_textbox(rect)
                if not re.search(r'\bInput\s*:',raw,re.I) or not re.search(r'\bOutput\s*:',raw,re.I):continue
                cs=characters(page,rect)
                if sum(c['token']==r'\leftarrow' for c in cs)<2 and len(re.findall(r'(?m)^\s*\d+\s*:',raw))<3:continue
                candidates.append(rect)
        if len(candidates)==1:results.append({'rect':candidates[0],'caption_bbox':cap,'caption_text':text,'evidence':'caption_input_output_steps_and_closed_physical_rules'})
    return results

def primary_lines(cs):
    body=statistics.median(c['size'] for c in cs if c['c'].strip());groups=[]
    for c in cs:
        if not c['c'].strip() or c['size']<body*.86 or c['font'].startswith('CMEX'):continue
        g=next((g for g in groups if abs(g['y']-c['origin'][1])<body*.16),None)
        if g is None:g={'y':c['origin'][1],'chars':[]};groups.append(g)
        g['chars'].append(c)
    for g in groups:
        labels=[c for c in cs if c not in g['chars'] and c['size']<body*.86
                and abs(c['origin'][1]-g['y'])<.5 and c['bbox'][0]<min(x['bbox'][0] for x in cs)+20
                and not is_math(c) and (c['c'].isdigit() or c['c']==':')]
        g['chars']+=labels
    return sorted(groups,key=lambda g:g['y'])


def spaced_text(chars):
    out='';previous=None
    for c in sorted(chars,key=lambda c:c['bbox'][0]):
        if previous and out and not out[-1].isspace() and not c['c'].startswith((' ','.',',',';',':',')',']')):
            if c['bbox'][0]-previous['bbox'][2]>min(c['size'],previous['size'])*.12:out+=' '
        out+=c['c'];previous=c
    return out

def math_runs(page,cs):
    """CM evidence with Roman named math operators, separated by actual prose."""
    main=[c for c in cs if c['c'].strip()]
    if not main:return []
    # Non-math native spans are prose separators, except standard function names.
    roman_math=set()
    def keep_word(word):
        if re.fullmatch(r'(?:[A-Z]{1,5}|Var|Cov|Norm|max|min|log|exp)',''.join(c['c'] for c in word)):
            roman_math.update(id(c) for c in word)
    for row in group_lines(cs):
        word=[]
        for c in sorted(row['chars'],key=lambda c:c['bbox'][0]):
            if is_math(c) or not c['c'].isascii() or not c['c'].isalpha():keep_word(word);word=[];continue
            if word and (c['bbox'][0]-word[-1]['bbox'][2]>c['size']*.2 or abs(c['origin'][1]-word[-1]['origin'][1])>.5):keep_word(word);word=[]
            word.append(c)
        keep_word(word)
    excluded=[c for c in main if not is_math(c) and id(c) not in roman_math
              and not re.fullmatch(r'(?:[A-Z]{1,5}|Var|Cov|Norm|max|min|log|exp)[\[\]().,]*',c.get('span_text','').strip())]
    math=[c for c in main if c not in excluded and (is_math(c) or c['c'].strip())]
    if not math or not any(not c['font'].startswith('CMEX') for c in math):return []
    # A relation at a separate vertical baseline defines a new display line.
    base=max(c['size'] for c in math if not c['font'].startswith('CMEX'));ys=[]
    for c in math:
        if c['token'] not in ('=',r'\leftarrow',r'\le',r'\ge') or c['size']<base*.86:continue
        if not any(abs(c['origin'][1]-y)<base*.9 for y in ys):ys.append(c['origin'][1])
    ys.sort()
    if not ys:
        for g in primary_lines([c for c in math if c['size']>=base*.86 and not c['font'].startswith('CMEX')]):
            if not ys or g['y']-ys[-1]>base*.95:ys.append(g['y'])
    def ordinate(c):
        if c['font'].startswith('CMEX') and c['token'] in ('(',')','[',']'):
            # CMEX delimiters use a font origin above their typeset math axis.
            return c['origin'][1]+c['size']*.8
        return c['origin'][1]
    bands=[math] if len(ys)<2 else [[c for c in math if (i==0 or ordinate(c)>=(ys[i-1]+y)/2) and (i==len(ys)-1 or ordinate(c)<(y+ys[i+1])/2)] for i,y in enumerate(ys)]
    results=[]
    for band in bands:
        # Prose occupying a horizontal interval separates independent expressions.
        ordered=sorted(band,key=lambda c:c['bbox'][0]);parts=[];current=[]
        for c in ordered:
            if current:
                edge=max(x['bbox'][2] for x in current)
                between=[p for p in excluded if edge<=p['bbox'][0] and p['bbox'][2]<=c['bbox'][0] and abs(p['origin'][1]-c['origin'][1])<base*1.5]
                if between or c['bbox'][0]-edge>base*4:parts.append(current);current=[]
            current.append(c)
        if current:parts.append(current)
        for part in parts:
            if not any(is_math(c) for c in part):continue
            bb=bounds(part);text=layout_latex(part,horizontal_bars(page,fitz.Rect(bb)))
            results.append({'latex':text,'glyphs':part,'bbox':bb,'verification':'unverified'})
    return results

def step_bands(page,rect):
    cs=characters(page,rect+(.7,.7,-.7,-.7));lines=primary_lines(cs)
    if not lines:return []
    numbered=[];headers=[]
    for g in lines:
        chars=sorted(g['chars'],key=lambda c:c['bbox'][0]);text=''.join(c['c'] for c in chars)
        if chars[0]['bbox'][0]>rect.x0+55:continue
        if re.match(r'^\d+\s*:',text):numbered.append(g)
        if re.match(r'^(Input|Output)\s*:',text,re.I):headers.append(g)
    if numbered:anchors=sorted(headers+numbered,key=lambda g:g['y'])
    else:
        arrowys=[g for g in lines if any(c['token']==r'\leftarrow' and c['bbox'][0]<rect.x0+rect.width*.5 for c in g['chars'])]
        if len(arrowys)<2 or not headers:return []
        first=arrowys[0]['y'];intro=[g for g in lines if headers[0]['y']<=g['y']<first-8]
        anchors=intro+arrowys
    anchors=sorted({round(g['y'],1):g for g in anchors}.values(),key=lambda g:g['y']);steps=[]
    numbered_layout=bool(numbered);body=statistics.median(c['size'] for c in cs if c['c'].strip())
    for i,g in enumerate(anchors):
        boundary=lambda a,b:b['y']-body*.55 if numbered_layout else (a['y']+b['y'])/2
        lo=rect.y0 if i==0 else boundary(anchors[i-1],g)
        hi=rect.y1 if i==len(anchors)-1 else boundary(g,anchors[i+1])
        own=[c for c in cs if lo<=c['origin'][1]<hi]
        if not own:continue
        raw=' '.join(''.join(c['c'] for c in sorted(row['chars'],key=lambda c:c['bbox'][0])) for row in group_lines(own)).strip()
        anchor_text=''.join(c['c'] for c in sorted(g['chars'],key=lambda c:c['bbox'][0]))
        number=re.match(r'^\s*(\d+)\s*:',anchor_text)
        # The left-side source step label is prose, not a numeric math operand.
        math_cs=list(own)
        if number:
            label_chars=sorted(g['chars'],key=lambda c:c['bbox'][0])[:len(number[0])]
            math_cs=[c for c in own if c not in label_chars]
        comment=[c for c in own if c['c']=='/' and not is_math(c)]
        if comment and min(c['bbox'][0] for c in comment)>rect.x0+rect.width*.5:
            edge=min(c['bbox'][0] for c in comment);math_cs=[c for c in math_cs if c['bbox'][0]<edge]
        runs=math_runs(page,math_cs)
        kind='input' if re.match(r'^Input\s*:',raw,re.I) else 'output' if re.match(r'^Output\s*:',raw,re.I) else 'step' if number or any(c['token']==r'\leftarrow' for c in own) else 'input_continuation'
        rendered=[c for c in own if not any(c in m['glyphs'] for m in runs)]
        for m in runs:
            atom=dict(m['glyphs'][0]);big=[c for c in m['glyphs'] if c['size']>=body*.86 and not c['font'].startswith('CMEX')]
            primary=statistics.median(c['origin'][1] for c in big) if big else g['y']
            atom.update(c='$'+m['latex']+'$',token=m['latex'],bbox=m['bbox'],origin=[m['bbox'][0],primary],size=body,line=-len(rendered)-1)
            rendered.append(atom)
        display=' '.join(spaced_text(row['chars']) for row in group_lines(rendered)).strip()
        steps.append({'raw':raw,'text':display,'source_step_number':int(number[1]) if number else None,'kind':kind,'bbox':bounds(own),'glyphs':own,'math':runs,'baseline':g['y']})
    return steps

def recover_algorithms(pdf,blocks,rid,next_id):
    result=list(blocks);remap={}
    for page in pdf:
        rotation=page.rotation;page.set_rotation(0)
        try:
            for obj in boxed_algorithms(page):
                rect=obj['rect'];steps=step_bands(page,rect)
                if len(steps)<4:continue
                captions=[b for b in result if b['type']=='caption' and re.match(r'^Algorithm\s+\d+[:.]',b['text'],re.I) and any(r['page_index']==page.number and abs(r['bbox'][1]*page.rect.height-obj['caption_bbox'].y0)<10 for r in b['regions'])]
                if len(captions)!=1:continue
                cap=captions[0];inside=[]
                for b in result:
                    if b is cap or b['type']=='algorithm' or not b['regions']:continue
                    if all(r['page_index']==page.number and rect.contains(fitz.Rect([v*(page.rect.width if i%2==0 else page.rect.height) for i,v in enumerate(r['bbox'])]).tl) for r in b['regions']):inside.append(b)
                if not inside:continue
                parent=min(inside,key=lambda b:b['reading_order']);snapshots=[dict(b) for b in inside];children=[];group='unspecified';level=0
                def bid():
                    nonlocal next_id
                    value=f'{rid}:b{next_id:06}';next_id+=1;return value
                for n,step in enumerate(steps):
                    sid=bid();mathchildren=[]
                    for m in step['math']:
                        from .math_structure import math_tree
                        mid=bid();mathchildren.append(mid)
                        children.append({'id':mid,'type':'formula','text':m['latex'],'section_id':parent['section_id'],'reading_order':parent['reading_order'],
                         'regions':[region(page.number,m['bbox'],page.rect.width,page.rect.height)],'source':'pdf_algorithm_glyph_rules','quality_flags':['formula_content_unverified'],
                         'data':{'parent_block_id':sid,'role':'algorithm_formula','math':{'latex':m['latex'],'source':'pdf_algorithm_glyph_rules','glyphs':m['glyphs'],'math_structure':math_tree(m['latex']),'verification':'unverified'},'assets':[]}})
                    raw=step['raw'];control=re.sub(r'^\d+\s*:\s*','',raw).lower()
                    if re.search(r'//\s*training\b',raw,re.I):group='training'
                    if re.search(r'//\s*inference\b',raw,re.I):group='inference'
                    if re.match(r'end\s+(for|while|if)\b',control):level=max(0,level-1)
                    text=step['text']
                    children.append({'id':sid,'type':'algorithm_step','text':text,'reading_order':parent['reading_order'],'section_id':parent['section_id'],
                     'regions':[region(page.number,step['bbox'],page.rect.width,page.rect.height)],'source':'pdf_boxed_algorithm_layout','quality_flags':['content_unverified'],
                     'data':{'parent_block_id':parent['id'],'step_number':n+1,'source_step_number':step['source_step_number'],'step_kind':step['kind'],'indent_level':level,'group_role':group,
                         'raw_text':raw,'glyphs':step['glyphs'],'math_latex':[m['latex'] for m in step['math']],'children':mathchildren,'verification':'unverified','assets':[]}})
                    if re.match(r'(for|while|if)\b',control):level+=1
                stepchildren=[c for c in children if c['type']=='algorithm_step']
                # Preserve every replaced raw object, including erroneous math candidates.
                new={**parent,'type':'algorithm','text':'\n'.join(c['text'] for c in stepchildren),'regions':[region(page.number,list(rect),page.rect.width,page.rect.height)]+cap['regions'],
                    'source':'pdf_caption_closed_rule_algorithm','quality_flags':['algorithm_content_unverified'],'data':{'raw_block_candidates':snapshots,'raw_text':parent['text'],'assets':parent['data'].get('assets',[]),
                     'children':[cap['id']]+[c['id'] for c in stepchildren],'caption':cap['text'],'caption_block_id':cap['id'],
                     'algorithm':{'source':'pdf_caption_closed_rule_algorithm','steps':[{'block_id':c['id'],'source_step_number':c['data']['source_step_number'],'step_kind':c['data']['step_kind'],'indent_level':c['data']['indent_level'],'group_role':c['data']['group_role']} for c in stepchildren],
                                  'groups':{g:[c['id'] for c in stepchildren if c['data']['group_role']==g] for g in ['training','inference']},'verification':'unverified','evidence':obj['evidence']}}}
                cap['data']['parent_block_id']=new['id'];cap['data']['role']='algorithm_caption'
                for b in inside:remap[b['id']]=new['id']
                at=result.index(parent);result=[b for b in result if b not in inside];result.insert(min(at,len(result)),new);result+=children
        finally:page.set_rotation(rotation)
    for b in result:
        for ref in b['data'].get('references',[]):
            if ref.get('target_block_id') in remap:ref['target_block_id']=remap[ref['target_block_id']]
    return result,next_id
