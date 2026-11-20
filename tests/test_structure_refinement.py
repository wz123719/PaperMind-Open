import json
import re
from pathlib import Path
from types import SimpleNamespace
import pymupdf as fitz
from backend.table_structure import refine_table
from backend.native_math import latex,layout_latex
from backend.structure_refinement import algorithm_steps,refine_order
import pytest


def raw_cell(row,col,text,box,header=False,row_span=1,col_span=1):
    return {'start_row_offset_idx':row,'start_col_offset_idx':col,'row_span':row_span,'col_span':col_span,
        'text':text,'column_header':header,'row_header':col==0 and row>0,
        'bbox':{'l':box[0],'t':box[1],'r':box[2],'b':box[3],'coord_origin':'TOPLEFT'}}


def block_for(raw,rect,page):
    return {'id':'anonymous:b000000','type':'table','text':'ORIGINAL RAW TABLE','regions':[{'page_index':0,
        'bbox':[rect[0]/page.rect.width,rect[1]/page.rect.height,rect[2]/page.rect.width,rect[3]/page.rect.height]}],
        'quality_flags':[],'data':{'table':raw}}


def test_independent_grid_corrects_extra_column_and_preserves_original_evidence():
    pdf=fitz.open();p=pdf.new_page();xs=[50,150,250,350,450];ys=[100,130,160,190]
    for x in xs:p.draw_line((x,100),(x,190))
    for y in ys:p.draw_line((50,y),(450,y))
    values=[['Channel','East','West','North'],['Pump A','17','23','41'],['Pump B','19','29','43']]
    for r,row in enumerate(values):
        for c,text in enumerate(row):p.insert_text((xs[c]+5,ys[r]+20),text,fontsize=10)
    raw={'num_rows':3,'num_cols':5,'table_cells':[]};b=block_for(raw,[50,100,450,190],p)
    refine_table(p,b);model=b['data']['table_model']
    assert model['num_columns']==4 and model['num_rows']==3
    cell=next(c for c in model['cells'] if c['row']==2 and c['column']==3)
    assert cell['text']=='43' and cell['column_headers'][0]['text']=='North'
    assert cell['row_headers'][0]['text']=='Pump B'
    assert b['data']['table']==raw and b['data']['raw_text']=='ORIGINAL RAW TABLE'
    assert len(b['data']['table_candidates'])==2


def test_correct_table_keeps_existing_cell_values_and_merged_header_path():
    pdf=fitz.open();p=pdf.new_page();raw={'num_rows':3,'num_cols':2,'table_cells':[
        raw_cell(0,0,'Measurement',[50,100,250,120],True,col_span=2),
        raw_cell(1,0,'A',[50,120,150,140],True),raw_cell(1,1,'B',[150,120,250,140],True),
        raw_cell(2,0,'12.8',[50,140,150,160]),raw_cell(2,1,'6.25',[150,140,250,160])]}
    b=block_for(raw,[50,100,250,160],p);refine_table(p,b)
    assert b['data']['selected_table_candidate']==0
    cell=next(c for c in b['data']['table_model']['cells'] if c['row']==2 and c['column']==1)
    assert cell['text']=='6.25' and [h['text'] for h in cell['column_headers']]==['Measurement','B']


def glyph(c,x,y,size=10,token=None,line=0):
    return {'c':c,'token':token or c,'origin':[x,y],'bbox':[x,y-size,x+size*.5,y+2],
        'size':size,'font':'CMMI10','glyph':'','line':line,'span':x,'span_text':c}


def compact(value):return re.sub(r'\s+','',value)


def test_pdf_script_geometry_distinguishes_power_of_parenthesized_expression():
    chars=[glyph('(',0,20),glyph('z',5,20),glyph('-',10,20),glyph('q',15,20),glyph(')',20,20),glyph('4',25,15,7)]
    result=compact(latex(chars))
    assert result=='(z-q)^{4}' and 'q^{4}' not in result


def test_pdf_fraction_graph_uses_actual_rule_and_distinct_source_bands():
    cs=[glyph('a',20,10),glyph('3',25,6,7),glyph('b',20,30),glyph('n',25,33,7)]
    result=compact(layout_latex(cs,[fitz.Rect(18,19.8,33,20.2)]))
    assert result==r'\frac{a^{3}}{b_{n}}'


def test_algorithm_steps_retain_order_indent_and_distinct_source_regions():
    pdf=fitz.open();p=pdf.new_page();lines=[(50,80,'Require: input'),(60,95,'while active'),(70,110,'update state'),(60,125,'end loop')]
    for x,y,text in lines:p.insert_text((x,y),text,fontsize=10)
    b={'id':'random:b000001','type':'code','text':'flattened original','section_id':None,
        'regions':[{'page_index':0,'bbox':[45/p.rect.width,65/p.rect.height,200/p.rect.width,130/p.rect.height]}],'data':{}}
    result=algorithm_steps(pdf,b,'random',10)
    assert len(result)==4 and [r['data']['indent_level'] for r in result]==[0,1,2,1]
    assert [r['text'].strip() for r in result]==['Require: input','while active','update state','end loop']
    assert len({tuple(r['regions'][0]['bbox']) for r in result})==4
    assert b['data']['raw_text']=='flattened original'


def test_reading_order_correction_requires_source_preceding_introduction_same_column():
    def b(kind,top,text,x=.1):return {'id':text,'type':kind,'text':text,'data':{},'reading_order':0,
        'regions':[{'page_index':0,'bbox':[x,top,x+.3,top+.04]}]}
    formula=b('formula',.3,'x=y');intro=b('text',.25,'Use the following expression:')
    blocks=[formula,intro];refine_order(blocks);assert blocks==[intro,formula]
    other=b('text',.2,'The following experiment',.65);blocks=[formula,other];refine_order(blocks);assert blocks==[formula,other]


@pytest.mark.parametrize('rotation',[90,180,270])
def test_cell_provenance_derotates_with_nondefault_cropbox(rotation):
    from backend.table_structure import from_docling
    pdf=fitz.open();p=pdf.new_page(width=600,height=800);p.set_cropbox(fitz.Rect(30,40,570,740));p.set_rotation(rotation)
    native=fitz.Rect(90,110,170,155);display=native*p.rotation_matrix
    raw={'num_rows':1,'num_cols':1,'table_cells':[raw_cell(0,0,'Unseen cell',list(display))]}
    result=from_docling(raw,p)
    actual=result['cells'][0]['regions'][0]['bbox']
    assert actual==pytest.approx([90/540,110/700,170/540,155/700])


def test_stacked_numeric_cells_split_into_source_subrows_with_spanning_label():
    pdf=fitz.open();p=pdf.new_page(width=600,height=400)
    for y in [100,130,180,210]:p.draw_line((40,y),(540,y))
    for x in [40,180,270,540]:p.draw_line((x,100),(x,210))
    positions=[45,185,285,375,465];headers=['Group','Mode','p = 3','p = 7','p = 11']
    for x,t in zip(positions,headers):p.insert_text((x,120),t,fontsize=10)
    p.insert_text((45,158),'Cohort A',fontsize=10)
    for y,label,values in [(148,'Mode U',['12.1','18.3','25.7']),(166,'Mode V',['8.4','10.6','16.8']),(199,'Mode U',['30.1','31.2','34.3'])]:
        p.insert_text((185,y),label,fontsize=10)
        for x,text in zip(positions[2:],values):p.insert_text((x,y),text,fontsize=10)
    p.insert_text((45,199),'Cohort B',fontsize=10)
    bounds_x=[40,180,270,360,450,540];cells=[]
    for col,text in enumerate(headers):cells.append(raw_cell(0,col,text,[bounds_x[col],106,bounds_x[col+1],123],True))
    cells+=[raw_cell(1,0,'Cohort A',[45,145,110,163]),raw_cell(1,1,'Mode U Mode V',[185,137,250,170])]
    for c,text in zip(range(2,5),['12.1 8.4','18.3 10.6','25.7 16.8']):cells.append(raw_cell(1,c,text,[positions[c],136,positions[c]+30,170]))
    cells+=[raw_cell(3,0,'Cohort B',[45,187,110,203]),raw_cell(3,1,'Mode U',[185,187,250,203])]
    for c,text in zip(range(2,5),['30.1','31.2','34.3']):cells.append(raw_cell(3,c,text,[positions[c],187,positions[c]+30,203]))
    b=block_for({'num_rows':4,'num_cols':5,'table_cells':cells},[40,100,540,210],p)
    refine_table(p,b);model=b['data']['table_model']
    assert model['source']=='pdf_numeric_baseline_subrows'
    a=next(c for c in model['cells'] if c['row']==2 and c['column']==3)
    assert a['text']=='10.6' and a['row_headers'][0]['text']=='Cohort A'
    label=next(c for c in model['cells'] if c['text']=='Cohort A')
    assert label['row_span']==2


def test_compound_figure_uses_caption_titles_and_preserves_separate_regions():
    from backend.figure_structure import figure_groups
    pdf=fitz.open();p=pdf.new_page(width=600,height=800);p.insert_text((350,110),'Output routing',fontsize=12)
    def obj(i,kind,text,bb,caption=None,section='s'):
        return {'id':f'r:b{i:06}','type':kind,'text':text,'section_id':section,'reading_order':i,
            'regions':[{'page_index':0,'bbox':bb}],'quality_flags':[],'data':{'caption':caption,'assets':[]}}
    caption='Figure 9: (left) Input routing. (right) Output routing in two branches.'
    blocks=[obj(0,'section_header','1 Network',[.1,.05,.3,.07],section='real'),
        obj(1,'section_header','Input routing',[.14,.1,.4,.13]),
        obj(2,'picture','',[.17,.16,.32,.3]),obj(3,'picture','',[.56,.1,.85,.3],caption),
        obj(4,'caption',caption,[.1,.35,.9,.38])]
    result,removed=figure_groups(pdf,blocks,'r',10)
    groups=[b for b in result if b['type']=='figure_group']
    assert len(groups)==1 and len(groups[0]['regions'])==5 and removed=={'s':'real'}
    assert blocks[2]['regions']==[{'page_index':0,'bbox':[.17,.16,.32,.3]}]
    assert blocks[1]['type']=='figure_panel_title'
    # Same geometry with no explicit side/title evidence must not create a relation.
    blocks[3]['data']['caption']='Figure 9: Unrelated overview.'
    assert not any(b['type']=='figure_group' for b in figure_groups(pdf,blocks,'r',20)[0])
