"""Comparison-only adapters. Never imply adoption or content verification."""
from html.parser import HTMLParser
from .math_structure import math_tree
from .table_structure import attach_headers,markdown

class TableHTML(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.cells=[];self.row=-1;self.current=None;self.script=[]
    def handle_starttag(self,tag,attrs):
        attributes=dict(attrs)
        if tag=='tr':self.row+=1
        if tag in ('td','th'):
            col=0
            occupied={x for c in self.cells if c['row']<=self.row<c['row']+c['row_span'] for x in range(c['column'],c['column']+c['column_span'])}
            while col in occupied:col+=1
            rs=int(attributes.get('rowspan',1));cs=int(attributes.get('colspan',1))
            if not 1<=rs<=100 or not 1<=cs<=100:raise ValueError('candidate table span exceeds budget')
            self.current={'row':self.row,'column':col,'row_span':rs,'column_span':cs,'text':'','raw_text':'',
                'regions':[],'column_header':tag=='th' or self.row==0,'row_header':self.row>0 and col==0,
                'region_status':'cell_coordinates_not_provided'}
        if tag in ('sup','sub') and self.current is not None:self.current['text']+='^{' if tag=='sup' else '_{';self.script.append(tag)
        if tag=='br' and self.current is not None:self.current['text']+='\n'
    def handle_endtag(self,tag):
        if tag in ('sup','sub') and self.current is not None and self.script:self.current['text']+='}';self.script.pop()
        if tag in ('td','th') and self.current is not None:
            self.current['text']=self.current['text'].strip()
            if '^{' in self.current['text'] or '_{' in self.current['text']:self.current['math_structure']=math_tree(self.current['text'])
            self.cells.append(self.current);self.current=None
    def handle_data(self,text):
        if self.current is not None:self.current['text']+=text;self.current['raw_text']+=text

def html_table(raw):
    parser=TableHTML();parser.feed(raw)
    model={'source':'candidate_html','num_rows':max((c['row']+c['row_span'] for c in parser.cells),default=0),
        'num_columns':max((c['column']+c['column_span'] for c in parser.cells),default=0),'cells':parser.cells,
        'verification':'unverified','checks':['header_roles_inferred_candidate','cell_regions_unknown']}
    if model['num_rows']>5000 or model['num_columns']>100:raise ValueError('candidate table dimensions exceed budget')
    return attach_headers(model)

def flatten(value):
    if isinstance(value,str):return value
    if isinstance(value,list):return ''.join(flatten(v) for v in value)
    if isinstance(value,dict):return flatten(value.get('content',''))
    return ''

def adapt_mineru(raw,rid='candidate-mineru'):
    if raw.get('metadata',{}).get('producer',{}).get('version')!='4.2.1':raise ValueError('Unsupported MinerU candidate schema/version')
    blocks=[]
    for page in raw['pages']:
        for item in page['blocks']:
            kind=item['type'];data={'raw_candidate':item,'verification':'unverified'};text=flatten(item.get('content',''))
            if kind=='table':
                body=next((x for x in item.get('content',[]) if x['type']=='table_body'),None)
                if body:data['table_model']=html_table(body['content']);text=markdown(data['table_model'])
            if kind=='equation':kind='formula';data['math_structure']=math_tree(text)
            box=item.get('bbox');regions=[]
            if box and len(box)==4 and all(0<=v<=1 for v in box):regions=[{'page_index':page['page_idx'],'bbox':box}]
            blocks.append({'id':f'{rid}:b{len(blocks):06}','type':kind,'text':text,'reading_order':len(blocks),
                'regions':regions,'source':'MinerU-4.2.1','quality_flags':['candidate_content_unverified','display_frame_requires_original_pdf_alignment'],
                'data':data})
    return {'blocks':blocks,'raw_candidate':raw,'adoption':'comparison_only','coordinate_frame':'candidate_display_normalized'}

def adapt_paddle(raw,rid='candidate-paddle'):
    payload=raw.get('res',raw)
    if 'parsing_res_list' not in payload:raise ValueError('Unsupported PP-StructureV3 candidate schema')
    blocks=[];width=payload.get('width');height=payload.get('height')
    for item in payload['parsing_res_list']:
        kind=item['block_label'];text=item['block_content'];data={'raw_candidate':item,'verification':'unverified'}
        if kind=='table':data['table_model']=html_table(text);text=markdown(data['table_model'])
        if kind in ('formula','display_formula'):kind='formula';data['math_structure']=math_tree(text)
        bbox=item.get('block_bbox');regions=[]
        if bbox and width and height:regions=[{'page_index':payload.get('page_index',0),'bbox':[bbox[0]/width,bbox[1]/height,bbox[2]/width,bbox[3]/height]}]
        blocks.append({'id':f'{rid}:b{len(blocks):06}','type':kind,'text':text,'reading_order':len(blocks),'regions':regions,
                       'source':'PP-StructureV3-3.7.0','quality_flags':['candidate_content_unverified','image_frame_alignment_required'],'data':data})
    return {'blocks':blocks,'raw_candidate':raw,'adoption':'comparison_only','coordinate_frame':'candidate_display_normalized'}
