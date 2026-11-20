"""Compound figure relations require caption side labels AND source title evidence."""
import re
from .geometry import region
from .native_math import characters,group_lines,bounds
from .structure_refinement import source_clip


def normalized(text):return ' '.join(re.findall(r'[a-z0-9]+',text.lower()))


def figure_groups(pdf,blocks,rid,next_id):
    result=list(blocks);removed_sections={}
    for main in blocks:
        if main['type']!='picture' or len(main['regions'])!=1:continue
        caption=main['data'].get('caption') or ''
        left=re.search(r'(?i)\(left\)\s*(.+?)\s*\(right\)',caption)
        right=re.search(r'(?i)\(right\)\s*(.+)',caption)
        if not left or not right:continue
        caps=[b for b in blocks if b['type']=='caption' and b['text']==caption and len(b['regions'])==1]
        if len(caps)!=1:continue
        cap=caps[0];mr=main['regions'][0];cr=cap['regions'][0];page_index=mr['page_index']
        if cr['page_index']!=page_index or cr['bbox'][1]<mr['bbox'][3]:continue
        matches=[]
        for panel in blocks:
            if panel is main or panel['type']!='picture' or panel['data'].get('caption') or len(panel['regions'])!=1:continue
            pr=panel['regions'][0]
            if pr['page_index']!=page_index or pr['bbox'][2]>=mr['bbox'][0] or pr['bbox'][3]>cr['bbox'][1]:continue
            overlap=min(pr['bbox'][3],mr['bbox'][3])-max(pr['bbox'][1],mr['bbox'][1])
            if overlap<=0:continue
            titles=[b for b in blocks if b['type'] in ('section_header','text') and len(b['regions'])==1
                and normalized(b['text']) and normalized(b['text']) in normalized(left[1])
                and not re.match(r'^\d',b['text']) and b['regions'][0]['page_index']==page_index
                and b['regions'][0]['bbox'][3]<=pr['bbox'][1] and b['regions'][0]['bbox'][1]>=mr['bbox'][1]-.03
                and min(b['regions'][0]['bbox'][2],pr['bbox'][2])>max(b['regions'][0]['bbox'][0],pr['bbox'][0])]
            if len(titles)==1:matches.append((panel,titles[0]))
        if len(matches)!=1:continue  # Ambiguity is not resolved by increasing a gap threshold.
        panel,title=matches[0]
        page=pdf[page_index];rotation=page.rotation;page.set_rotation(0)
        try:
            lines=group_lines(characters(page,source_clip(page,mr)))
            right_titles=[]
            for line in lines:
                text=''.join(c['token'] for c in sorted(line['chars'],key=lambda c:c['bbox'][0])).strip()
                if len(normalized(text))>8 and normalized(text) in normalized(right[1]):right_titles.append((text,line['chars']))
            if len(right_titles)!=1:continue
            text,cs=right_titles[0];right_id=f'{rid}:b{next_id:06}';next_id+=1
            right_title={'id':right_id,'type':'figure_panel_title','text':text,'section_id':main['section_id'],
                'reading_order':main['reading_order'],'regions':[region(page_index,bounds(cs),page.rect.width,page.rect.height)],
                'source':'pdf_glyph_layout','quality_flags':['figure_relation_unverified'],
                'data':{'parent_block_id':main['id'],'role':'panel_title','assets':[]}}
        finally:page.set_rotation(rotation)
        prior=[b for b in blocks if b['reading_order']<title['reading_order'] and b['type'] in ('section_header','title')]
        fallback=prior[-1]['section_id'] if prior else None
        if title['type']=='section_header':removed_sections[title['section_id']]=fallback
        title['data']['original_type']=title['type'];title['type']='figure_panel_title'
        title['data'].update(parent_block_id=panel['id'],role='panel_title')
        panel['data']['children']=[title['id']];main['data']['children']=[right_id]
        gid=f'{rid}:b{next_id:06}';next_id+=1
        for child in (panel,main,cap):child['data']['parent_block_id']=gid
        group={'id':gid,'type':'figure_group','text':caption,'section_id':fallback,'reading_order':title['reading_order'],
            'regions':title['regions']+panel['regions']+main['regions']+right_title['regions']+cap['regions'],
            'source':'source_object_relations','quality_flags':['figure_relation_unverified'],
            'data':{'children':[panel['id'],main['id'],cap['id']],'panels':[panel['id'],main['id']],
                'caption_block_id':cap['id'],'caption':caption,'assets':list(dict.fromkeys(panel['data'].get('assets',[])+main['data'].get('assets',[]))),
                'association_status':'candidate','association_evidence':{'caption_side_labels':['left','right'],
                    'source_title_matches':[title['id'],right_id]},'verification':'unverified'}}
        result.insert(result.index(main)+1,right_title)
        result.insert(result.index(title),group)
    for b in result:
        if b['section_id'] in removed_sections:b['section_id']=removed_sections[b['section_id']]
    from .figure_panels import embedded_panel_groups
    result=embedded_panel_groups(pdf,result,rid,next_id)
    return result,removed_sections
