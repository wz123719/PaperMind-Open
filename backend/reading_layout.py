"""Conservative two-column bands; split only proven metadata/body mixtures."""
import copy
import pymupdf as fitz

def split_metadata_body(pdf,blocks,rid,next_id):
    result=[]
    for block in blocks:
        regions=block['regions'];split=False
        if block['type']=='text' and len(regions)>=3 and len({r['page_index'] for r in regions})==1:
            pi=regions[0]['page_index']
            heads=[r['bbox'][1] for b in blocks if b['type']=='section_header' and b is not blocks[0] for r in b['regions'] if r['page_index']==pi and r['bbox'][2]-r['bbox'][0]<.55]
            boundary=min(heads,default=0)
            split=(pi==0 and .16<boundary<.5 and any(r['bbox'][3]<boundary for r in regions) and any(r['bbox'][1]>=boundary for r in regions)
                   and max(r['bbox'][0] for r in regions)-min(r['bbox'][0] for r in regions)>.2)
        if not split:result.append(block);continue
        original=copy.deepcopy(block);page=pdf[regions[0]['page_index']];rotation=page.rotation;page.set_rotation(0)
        try:
            for n,r in enumerate(regions):
                bid=block['id'] if n==0 else f'{rid}:b{next_id:06}'
                if n:next_id+=1
                rect=fitz.Rect([v*(page.rect.width if i%2==0 else page.rect.height) for i,v in enumerate(r['bbox'])])
                value={**block,'id':bid,'text':page.get_textbox(rect).strip(),'regions':[r], 'source':'pdf_disjoint_metadata_body_regions','data':copy.deepcopy(block['data'])}
                value['data'].update(raw_text=original['text'],raw_regions=regions,split_from_block_id=block['id'],split_reason='above_and_below_first_body_heading_with_distinct_columns')
                result.append(value)
        finally:page.set_rotation(rotation)
    return result,next_id

def column_order(blocks):
    byid={b['id']:b for b in blocks};roots=[b for b in blocks if b['data'].get('parent_block_id') not in byid]
    def first(b):
        return min(b['regions'],key=lambda r:(r['page_index'],r['bbox'][1])) if b['regions'] else {'page_index':100000,'bbox':[0,0,1,1]}
    pages={first(b)['page_index'] for b in roots};ordered=[]
    for pi in sorted(pages):
        items=[b for b in roots if first(b)['page_index']==pi]
        left=[b for b in items if first(b)['bbox'][2]<.54];right=[b for b in items if first(b)['bbox'][0]>.46]
        if len(left)<3 or len(right)<3:ordered+=items;continue
        # Full-width objects divide column flows. A first-page body heading also
        # separates shared author metadata from the two independent prose columns.
        wide=[b for b in items if first(b)['bbox'][2]-first(b)['bbox'][0]>.55]
        cutpoints=sorted({first(b)['bbox'][1] for b in wide}|{first(b)['bbox'][3] for b in wide})
        heading=min((first(b)['bbox'][1] for b in items if b['type']=='section_header' and b not in wide),default=0)
        body_boundary=heading if pi==0 and .16<heading<.5 and wide else None
        if body_boundary:cutpoints.append(body_boundary);cutpoints.sort()
        def key(b):
            r=first(b)['bbox'];y=r[1];band=sum(y>=v-.001 for v in cutpoints)
            metadata=body_boundary and y<body_boundary
            col=0 if b in wide or metadata else int((r[0]+r[2])/2>.5)
            return band,col,round(y,3),r[0]
        items.sort(key=key)
        for b in items:b['data']['reading_order_evidence']={'source':'two_column_physical_bands','page_index':pi,'metadata_boundary':body_boundary,'verification':'unverified'}
        ordered+=items
    children={}
    for b in blocks:
        pid=b['data'].get('parent_block_id')
        if pid in byid:children.setdefault(pid,[]).append(b)
    flattened=[];seen=set()
    def visit(b):
        if b['id'] in seen:return
        seen.add(b['id']);flattened.append(b)
        explicit=b['data'].get('children',[]);own=children.get(b['id'],[])
        own.sort(key=lambda c:explicit.index(c['id']) if c['id'] in explicit else len(explicit)+c['reading_order'])
        for c in own:visit(c)
    for b in ordered:visit(b)
    for b in blocks:visit(b)
    for i,b in enumerate(flattened):b['reading_order']=i
    return flattened
