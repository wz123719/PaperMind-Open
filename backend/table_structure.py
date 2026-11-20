"""Canonical cells plus independent PDF ruled-grid/subrow candidates."""
import re
import statistics
import copy
from collections import defaultdict
import pymupdf as fitz
from .geometry import region
from .native_math import characters,group_lines,formatted_line,bounds,latex,horizontal_bars,layout_latex


def text_of(chars):
    return '\n'.join(''.join(s['text'] for s in formatted_line(g['chars'])) for g in group_lines(chars)).strip()


def model_cell(page,rect,row,col,row_span=1,col_span=1,header=False,text=None,baseline_range=None):
    cs=characters(page,fitz.Rect(rect)+(-.2,-.2,.2,.2))
    if baseline_range:cs=[c for c in cs if baseline_range[0]<=c['origin'][1]<baseline_range[1]]
    decoration=[c for c in cs if c['glyph'].startswith(('bracketleft','bracketright')) or ord(c['c'])<32]
    body=[c for c in cs if c not in decoration]
    value=text_of(body) if text is None else text
    substructure=None
    right=[c['bbox'][0] for c in decoration if c['glyph'].startswith('bracketright')]
    if right:
        edge=min(right)
        repeated=[c for c in body if c['bbox'][0]>=edge]
        inside=[c for c in body if c not in repeated]
        if repeated and inside:
            substructure={'kind':'matrix_with_repeat','rows':[text_of(g['chars']) for g in group_lines(inside)],
                'repeat':text_of(repeated),'verification':'unverified'}
            value='['+'; '.join(substructure['rows'])+'] '+substructure['repeat']
    return {'row':row,'column':col,'row_span':row_span,'column_span':col_span,
        'text':value,'raw_text':page.get_textbox(fitz.Rect(rect)),
        'regions':[region(page.number,rect,page.rect.width,page.rect.height)],
        'column_header':header,'row_header':col==0 and not header,'glyphs':cs,'substructure':substructure}


def attach_headers(model):
    for c in model['cells']:
        c['column_headers']=[{'row':h['row'],'column':h['column'],'text':h['text'],'regions':h.get('regions',[])} for h in sorted(model['cells'],key=lambda h:(h['row'],h['column']))
            if h['column_header'] and h['row']<c['row'] and h['column']<c['column']+c['column_span']
            and c['column']<h['column']+h['column_span']]
        c['row_headers']=[{'row':h['row'],'column':h['column'],'text':h['text']} for h in model['cells']
            if h.get('row_header') and h['column']<c['column'] and h['row']<=c['row']<h['row']+h['row_span']]
    return model


def from_docling(raw,page,page_size=None):
    cells=[]
    width,height=(page.rect.width,page.rect.height) if page.rotation%180==0 else (page.rect.height,page.rect.width)
    pw,ph=(page_size['width'],page_size['height']) if page_size else (page.rect.width,page.rect.height)
    for c in raw.get('table_cells',[]):
        bbox=c.get('bbox')
        if not bbox:continue
        rect=fitz.Rect(bbox['l'],bbox['t'],bbox['r'],bbox['b'])
        if bbox.get('coord_origin')=='BOTTOMLEFT':rect=fitz.Rect(rect.x0,ph-rect.y1,rect.x1,ph-rect.y0)
        rect=fitz.Rect(rect.x0*page.rect.width/pw,rect.y0*page.rect.height/ph,rect.x1*page.rect.width/pw,rect.y1*page.rect.height/ph)*page.derotation_matrix
        cells.append({'row':c['start_row_offset_idx'],'column':c['start_col_offset_idx'],
            'row_span':c['row_span'],'column_span':c['col_span'],'text':c['text'],'raw_text':c['text'],
            'regions':[region(page.number,list(rect),width,height)],'column_header':c['column_header'],
            'row_header':c.get('row_header',False)})
    return attach_headers({'source':'docling_cells','num_rows':raw['num_rows'],'num_columns':raw['num_cols'],
        'cells':cells,'checks':[],'verification':'unverified'})


def clustered(values,tolerance=1):
    result=[]
    for v in sorted(values):
        if not result or abs(v-result[-1])>tolerance:result.append(v)
    return result


def ruled_candidate(page,clip):
    tables=page.find_tables(clip=clip+(-2,-2,2,2),strategy='lines').tables
    if not tables:return None
    table=max(tables,key=lambda t:fitz.Rect(t.bbox).width*fitz.Rect(t.bbox).height)
    rect=fitz.Rect(table.bbox)
    if rect.width*rect.height<clip.width*clip.height*.85:return None
    rects=[r for row in table.rows for r in row.cells if r]
    xs=clustered([r[i] for r in rects for i in (0,2)]);ys=clustered([r[i] for r in rects for i in (1,3)])
    if len(xs)-1!=table.col_count or len(ys)-1!=table.row_count:return None
    cells=[];seen=set()
    for rect in rects:
        key=tuple(round(x,1) for x in rect)
        if key in seen:continue
        seen.add(key)
        x0,y0,x1,y1=rect
        col=min(range(len(xs)),key=lambda i:abs(xs[i]-x0));endcol=min(range(len(xs)),key=lambda i:abs(xs[i]-x1))
        row=min(range(len(ys)),key=lambda i:abs(ys[i]-y0));endrow=min(range(len(ys)),key=lambda i:abs(ys[i]-y1))
        cells.append(model_cell(page,rect,row,col,endrow-row,endcol-col,header=row==0))
    if sum(c['row']==0 and bool(c['text']) for c in cells)<3:return None
    return attach_headers({'source':'pymupdf_ruled_grid','num_rows':table.row_count,'num_columns':table.col_count,
        'cells':cells,'checks':['independent_vector_grid'],'verification':'unverified'})


def subrow_candidate(page,clip,model):
    # Only trigger when multiple numeric cells contain stacked source baselines.
    multi=[]
    for cell in model['cells']:
        if cell['column_header']:continue
        r=cell['regions'][0]['bbox'];bb=[r[0]*page.rect.width,r[1]*page.rect.height,r[2]*page.rect.width,r[3]*page.rect.height]
        groups=group_lines(characters(page,fitz.Rect(bb)+(-.3,-.5,.3,.5)))
        if len(groups)>=2 and all(re.fullmatch(r'\s*[-+]?\d+(?:\.\d+)?\s*',text_of(g['chars'])) for g in groups):multi.append((cell,groups))
    if len(multi)<3:return None
    headers=[c for c in model['cells'] if c['column_header'] and c['column_span']==1]
    nc=model['num_columns'];centers={}
    for col in range(nc):
        choices=[c for c in headers if c['column']==col]
        if choices:
            bb=choices[-1]['regions'][0]['bbox'];centers[col]=(bb[0]+bb[2])*page.rect.width/2
    # A blank leading header has no cell: infer its center from body-cell evidence.
    for col in range(nc):
        if col not in centers:
            choices=[c for c in model['cells'] if c['column']==col and c['column_span']==1]
            if not choices:return None
            centers[col]=statistics.median((c['regions'][0]['bbox'][0]+c['regions'][0]['bbox'][2])*page.rect.width/2 for c in choices)
    xs=[clip.x0]+[(centers[c-1]+centers[c])/2 for c in range(1,nc)]+[clip.x1]
    header_bottom=max(c['regions'][0]['bbox'][3]*page.rect.height for c in headers)
    cs=characters(page,fitz.Rect(clip.x0,header_bottom+.5,clip.x1,clip.y1+1))
    numeric_columns={c['column'] for c,_ in multi}
    rows=[]
    for col in numeric_columns:
        cc=[c for c in cs if xs[col]<=sum(c['bbox'][::2])/2<xs[col+1]]
        for g in group_lines(cc):
            if re.fullmatch(r'\s*[-+]?\d+(?:\.\d+)?\s*',text_of(g['chars'])):rows.append(g['baseline'])
    baselines=clustered(rows,2)
    if len(baselines)<2:return None
    ys=[header_bottom+1]+[(a+b)/2 for a,b in zip(baselines,baselines[1:])]+[clip.y1]
    cells=[]
    for h in headers:cells.append({**h,'row':0})
    for row in range(len(baselines)):
        for col in range(nc):
            bb=[xs[col],ys[row],xs[col+1],ys[row+1]]
            cell=model_cell(page,bb,row+1,col,baseline_range=(ys[row],ys[row+1]))
            if cell['text']:cells.append(cell)
    # Preserve a source row-label centered between numeric subrows as a spanning label.
    separators=clustered([b.y0 for b in horizontal_bars(page,clip) if b.width>clip.width*.8])
    for original in model['cells']:
        if original['column_header'] or original['column'] in numeric_columns:continue
        if original['column']!=0:continue
        r=original['regions'][0]['bbox'];cy=(r[1]+r[3])*page.rect.height/2
        near=[i for i,y in enumerate(baselines) if abs(y-cy)<(ys[-1]-ys[0])/max(1,len(baselines))*.65]
        lower=max([y for y in separators if y<cy],default=clip.y0)
        upper=min([y for y in separators if y>cy],default=clip.y1)
        in_band=[i for i,y in enumerate(baselines) if lower<y<upper]
        if len(in_band)>1 and separators:near=in_band
        if len(near)>1:
            cells=[c for c in cells if not(c['column']==0 and c['row']-1 in near)]
            cells.append({**original,'row':near[0]+1,'row_span':len(near)})
    return attach_headers({'source':'pdf_numeric_baseline_subrows','num_rows':len(baselines)+1,'num_columns':nc,
        'cells':cells,'checks':['stacked_numeric_cells_split_by_source_baselines'],'verification':'unverified'})


def categorical_subrows(page,model):
    """Split aligned categorical records; wrapped prose is not a row signal."""
    vocabulary={'yes','no','true','false','invariant','variant','supported','unsupported','✓','✔','✕','✖','✗','✘'}
    result=copy.deepcopy(model);changes=[]
    for row in sorted({c['row'] for c in model['cells'] if not c['column_header']},reverse=True):
        cells=[c for c in model['cells'] if c['row']==row and not c['column_header']]
        if len(cells)<4 or any(c['row_span']!=1 or c['column_span']!=1 or len(c['regions'])!=1 for c in cells):continue
        grouped=[]
        for c in cells:
            rr=c['regions'][0]['bbox'];rect=fitz.Rect(rr[0]*page.rect.width,rr[1]*page.rect.height,rr[2]*page.rect.width,rr[3]*page.rect.height)
            gs=group_lines(characters(page,rect+(-.3,-.3,.3,.3)))
            grouped.append((c,gs))
        numeric=[(c,gs) for c,gs in grouped if c['column']>0 and len(gs)>=2
                 and all(text_of(g['chars']).strip().lower() in vocabulary for g in gs)]
        if len(numeric)<3:continue
        n=len(numeric[0][1]);baselines=[g['baseline'] for g in numeric[0][1]]
        if any(len(gs)!=n or any(abs(g['baseline']-y)>1.5 for g,y in zip(gs,baselines)) for c,gs in grouped):continue
        first=min(grouped,key=lambda x:x[0]['column'])
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z -]{1,40}',text_of(g['chars']).strip()) for g in first[1]):continue
        old=[c for c in result['cells'] if c['row']==row and not c['column_header']]
        result['cells']=[c for c in result['cells'] if c not in old]
        for c in result['cells']:
            if c['row']>row:c['row']+=n-1
        for c,gs in grouped:
            rr=c['regions'][0]['bbox'];y0=rr[1]*page.rect.height;y1=rr[3]*page.rect.height
            ys=[y0]+[(a+b)/2 for a,b in zip(baselines,baselines[1:])]+[y1]
            for i,g in enumerate(gs):
                rect=[rr[0]*page.rect.width,ys[i],rr[2]*page.rect.width,ys[i+1]]
                new=model_cell(page,rect,row+i,c['column'],header=False,baseline_range=(ys[i],ys[i+1]))
                new['row_header']=c['column']==first[0]['column'];result['cells'].append(new)
        result['num_rows']+=n-1;changes.append({'original_row':row,'source_baselines':baselines,'rows':n})
    if not changes:return None
    result.update(source='pdf_aligned_categorical_records',verification='unverified',row_split_evidence=changes)
    result['checks'].append('aligned_categorical_rows_not_prose');return attach_headers(result)


def symbol_candidate(page,original):
    from .native_math import DINGBATS
    result=copy.deepcopy(original);changed=False
    for cell in result['cells']:
        if len(cell['regions'])!=1:continue
        rr=cell['regions'][0]['bbox'];rect=fitz.Rect(rr[0]*page.rect.width,rr[1]*page.rect.height,rr[2]*page.rect.width,rr[3]*page.rect.height)
        cs=characters(page,rect+(-.2,-.2,.2,.2));mapped=[c for c in cs if 'dingbat' in c['font'].lower() and c['glyph'] in DINGBATS]
        if not mapped:
            if any('dingbat' in c['font'].lower() for c in cs):
                cell['symbol_status']='unknown_font_mapping';result['checks'].append('unmapped_dingbat_symbol');changed=True
            continue
        cell.update(text=text_of(cs),source_glyphs=cs,symbol_status='embedded_font_encoding_candidate',
                    symbol_evidence=[{'font':c['font'],'raw_extracted_character':c['c'],'glyph_name':c['glyph'],'decoded':c['token'],'bbox':c['bbox'],
                                      'mapping':'embedded_type1_literal_encoding+Adobe_Zapf_glyph_name'} for c in mapped])
        if cell['text'].strip() in DINGBATS.values():cell['boolean_value']=cell['text'].strip() in ('✓','✔')
        changed=True
    if not changed:return None
    result['source']='pdf_embedded_symbol_encoding';result['checks'].append('font_glyph_name_mapping_not_digit_replacement')
    return attach_headers(result)


def markdown(model):
    grid=[['']*model['num_columns'] for _ in range(model['num_rows'])]
    for c in model['cells']:
        if c['row']<len(grid) and c['column']<len(grid[0]):grid[c['row']][c['column']]=c['text'].replace('|',r'\|').replace('\n','<br>')
    rows=['| '+' | '.join(row)+' |' for row in grid]
    rows.insert(1,'| '+' | '.join('---' for _ in grid[0])+' |')
    return '\n'.join(rows)


def source_relationships(page,clip,original):
    """Restore scripts and spanning headers only from actual glyph/rule evidence."""
    from .math_structure import math_tree
    from .math_recognition import latex_checks
    model=copy.deepcopy(original);changed=False
    for cell in model['cells']:
        if len(cell['regions'])!=1:continue
        r=cell['regions'][0]['bbox'];rect=fitz.Rect(r[0]*page.rect.width,r[1]*page.rect.height,r[2]*page.rect.width,r[3]*page.rect.height)
        cs=characters(page,rect+(-.4,-.5,.4,.5));groups=group_lines(cs)
        if len(groups)>1:
            inside=[g for g in groups if rect.y0<=g['baseline']<=rect.y1]
            if len(inside)==1:groups=inside;cs=inside[0]['chars']
        if len(groups)!=1 or not cs:continue
        base=statistics.median(c['size'] for c in cs)
        baseline=statistics.median(c['origin'][1] for c in cs if c['size']>=base*.9)
        scripts=[c for c in cs if c['size']<base*.9 and abs(c['origin'][1]-baseline)>base*.15]
        if not scripts:continue
        value=layout_latex(cs,horizontal_bars(page,rect))
        if latex_checks(value) or any(ord(c['c'])<32 and c['c'].strip() and c['token']==c['c'] for c in cs):
            model['checks'].append('table_math_unmapped');continue
        cell.update(text=value,math_latex=value,math_structure=math_tree(value),source_glyphs=cs,
                    math_check_status='structure_extracted_not_content_verified');changed=True
        scientific=re.fullmatch(r'([-+]?\d+(?:\.\d+)?)\\(?:cdot|times)10\^\{([-+]?\d+)\}',re.sub(r'\s+','',value))
        if scientific:
            cell['numeric_semantics']={'kind':'scientific_notation','mantissa':scientific[1],'base':10,'exponent':int(scientific[2]),'verification':'unverified'}
            cell['raw_regions']=cell['regions'];cell['regions']=[region(page.number,bounds(cs),page.rect.width,page.rect.height)]
    # A multi-line header is not automatically a spanning header. Its source
    # column partition must contain multiple independent lower-level headers.
    headers=[c for c in model['cells'] if c['column_header']]
    for merged in headers:
        r=merged['regions'][0]['bbox'];rect=fitz.Rect(r[0]*page.rect.width,r[1]*page.rect.height,r[2]*page.rect.width,r[3]*page.rect.height)
        groups=group_lines(characters(page,rect+(-.3,-.3,.3,.3)))
        if len(groups)!=2:continue
        top,bottom=groups
        rules=[]
        for drawing in page.get_drawings():
            for item in drawing['items']:
                if item[0]=='l':
                    a,b=item[1:3]
                    if abs(a.x-b.x)<.5 and min(a.y,b.y)<=top['baseline'] and max(a.y,b.y)>=bottom['baseline']-1:rules.append(a.x)
        # Rules can be split into contiguous source segments at row boundaries.
        if not rules:
            segments=defaultdict(list)
            for drawing in page.get_drawings():
                for item in drawing['items']:
                    if item[0]=='l' and abs(item[1].x-item[2].x)<.5:
                        a,b=item[1:3];segments[round(a.x,1)].append((min(a.y,b.y),max(a.y,b.y)))
            for x,ys in segments.items():
                covering=sorted((a,b) for a,b in ys if b>=top['baseline']-8 and a<=bottom['baseline'])
                if covering and covering[0][0]<=top['baseline'] and covering[-1][1]>=bottom['baseline'] and all(b>=c-.5 for (a,b),(c,d) in zip(covering,covering[1:])):rules.append(x)
        if not rules:continue
        center=sum(bounds(top['chars'])[::2])/2
        left=max([x for x in rules if x<center],default=clip.x0);right=min([x for x in rules if x>center],default=clip.x1)
        children=[]
        for h in headers:
            rr=h['regions'][0]['bbox'];cx=(rr[0]+rr[2])*page.rect.width/2
            if h is merged or (left<cx<right and abs(rr[3]*page.rect.height-bounds(bottom['chars'])[3])<3):children.append(h)
        if len(children)<2:continue
        # A shared right-side partition alone cannot prove a parent header:
        # adjacent independent metrics may each have two text lines. The
        # proposed parent must also sit over the combined child-column group.
        centers=[(c['regions'][0]['bbox'][0]+c['regions'][0]['bbox'][2])*page.rect.width/2 for c in children]
        group_center=(min(centers)+max(centers))/2
        if abs(center-group_center)>max(8,(max(centers)-min(centers))*.15):continue
        # Same-height neighboring headings are peers, even when the middle
        # heading happens to be centered over their combined bounding box.
        peer=False
        for child in children:
            if child is merged:continue
            rr=child['regions'][0]['bbox'];area=fitz.Rect(rr[0]*page.rect.width,rr[1]*page.rect.height,rr[2]*page.rect.width,rr[3]*page.rect.height)
            lines=group_lines(characters(page,area+(-.3,-.3,.3,.3)))
            if lines and abs(lines[0]['baseline']-top['baseline'])<statistics.median(c['size'] for c in top['chars'])*.35:peer=True;break
        if peer:continue
        cols=sorted(c['column'] for c in children)
        if cols!=list(range(cols[0],cols[-1]+1)):continue
        # Insert one header row; body values remain in their original columns.
        header_row=merged['row']
        for c in model['cells']:
            if c['row']>header_row:c['row']+=1
            elif c['row']==header_row:
                if c in children:c['row']+=1
                else:c['row_span']+=1
        merged['text']=text_of(bottom['chars']);merged['regions']=[region(page.number,bounds(bottom['chars']),page.rect.width,page.rect.height)]
        parent={'row':header_row,'column':cols[0],'row_span':1,'column_span':len(cols),
                'text':text_of(top['chars']),'raw_text':text_of(top['chars']),
                'regions':[region(page.number,bounds(top['chars']),page.rect.width,page.rect.height)],
                'column_header':True,'row_header':False,'source_partition':{'left':left,'right':right,'vertical_rules':rules}}
        model['cells'].append(parent);model['num_rows']+=1;changed=True;break
    if not changed:return None
    model['source']='pdf_glyph_header_relationships';model['verification']='unverified'
    model['checks'].append('source_math_and_header_structure_only')
    attach_headers(model)
    model['relationship_checks']={'numeric_cells_without_headers':[{'row':c['row'],'column':c['column']} for c in model['cells']
        if not c['column_header'] and re.fullmatch(r'[-+]?\d+(?:\.\d+)?',c['text']) and (not c['column_headers'] or not c['row_headers'])],
        'content_verification':'unverified'}
    return model


def refine_table(page,block):
    raw=block['data'].get('table')
    if not raw or len(block['regions'])!=1:return
    sizes=block['data'].get('provenance_page_sizes',[])
    model=from_docling(raw,page,sizes[0] if sizes else None)
    rotation=page.rotation;page.set_rotation(0)
    try:_refine_table_unrotated(page,block,model)
    finally:page.set_rotation(rotation)


def _refine_table_unrotated(page,block,model):
    r=block['regions'][0]['bbox']
    clip=fitz.Rect(r[0]*page.rect.width,r[1]*page.rect.height,r[2]*page.rect.width,r[3]*page.rect.height)
    candidates=[model];selected=0
    ruled=ruled_candidate(page,clip)
    if ruled:
        candidates.append(ruled)
        if ruled['num_columns']!=model['num_columns']:selected=len(candidates)-1
    subrows=subrow_candidate(page,clip,model)
    if subrows:candidates.append(subrows);selected=len(candidates)-1
    categorical=categorical_subrows(page,candidates[selected])
    if categorical:candidates.append(categorical);selected=len(candidates)-1
    symbols=symbol_candidate(page,candidates[selected])
    if symbols:candidates.append(symbols);selected=len(candidates)-1
    refined=source_relationships(page,clip,candidates[selected])
    if refined:candidates.append(refined);selected=len(candidates)-1
    block['data']['table_candidates']=candidates
    block['data']['table_model']=candidates[selected]
    block['data']['selected_table_candidate']=selected
    block['data']['table_differences']=[{'source':c['source'],'rows':c['num_rows'],'columns':c['num_columns']} for c in candidates]
    block['data'].setdefault('raw_text',block['text'])
    block['text']=markdown(candidates[selected])
    if selected:block['quality_flags'].append('table_geometry_refined_unverified')
