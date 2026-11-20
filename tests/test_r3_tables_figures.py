import copy
from types import SimpleNamespace
import pymupdf as fitz
from backend.native_math import type1_encoding,characters
from backend.table_structure import categorical_subrows,from_docling,symbol_candidate
from backend.figure_panels import embedded_panel_groups
from test_structure_refinement import raw_cell,glyph

def test_literal_type1_encoding_is_read_without_execution_and_unknown_is_not_guessed():
    data=b'/Encoding 256 array dup 61 /a19 put dup 62 /a23 put currentfile eexec dup 99 /a19 put'
    assert type1_encoding(data)=={61:'a19',62:'a23'}

def test_font_identity_and_proven_encoding_control_symbol_decoding(monkeypatch):
    import backend.native_math as native
    monkeypatch.setattr(native,'font_encodings',lambda p:{'DemoDingbats':{61:'a19'},'Helvetica':{51:'a19'}})
    def span(font,c):return {'font':font,'size':10,'chars':[{'c':c,'origin':[10,20],'bbox':[10,10,16,22]}]}
    page=SimpleNamespace(get_text=lambda *a,**k:{'blocks':[{'type':0,'lines':[{'spans':[span('DemoDingbats','=')]},{'spans':[span('Helvetica','3')]}]}]})
    cs=characters(page,None);assert cs[0]['token']=='✓' and cs[0]['pdf_encoding_code']==61 and cs[1]['token']=='3'

def test_symbol_cell_preserves_raw_value_and_does_not_change_ordinary_digits(monkeypatch):
    import backend.table_structure as table
    pdf=fitz.open();p=pdf.new_page()
    model={'source':'original','checks':[],'num_rows':1,'num_columns':2,'cells':[
        {'row':0,'column':i,'row_span':1,'column_span':1,'text':'3','raw_text':'3','column_header':False,
         'regions':[{'page_index':0,'bbox':[.1+i*.2,.1,.2+i*.2,.13]}]} for i in range(2)]}
    def cs(page,rect):
        c=glyph('3',rect.x0,rect.y1)
        c.update(font='DemoDingbats' if rect.x0<100 else 'Helvetica',glyph='a19' if rect.x0<100 else '',token='✓' if rect.x0<100 else '3')
        return [c]
    monkeypatch.setattr(table,'characters',cs)
    result=symbol_candidate(p,model);assert result['cells'][0]['text']=='✓' and result['cells'][0]['raw_text']=='3'
    assert result['cells'][0]['boolean_value'] is True and result['cells'][1]['text']=='3' and 'boolean_value' not in result['cells'][1]

def test_aligned_categorical_rows_split_but_multiline_prose_is_rejected():
    pdf=fitz.open();p=pdf.new_page();cells=[]
    for col,x in enumerate([50,180,260,340]):
        p.insert_text((x,105),'Method' if col==0 else 'Flag'+str(col),fontsize=10)
        cells.append(raw_cell(0,col,'header',[x,95,x+60,108],True))
        for row,y in enumerate([130,145]):p.insert_text((x,y),('Group A' if row==0 else 'Group B') if col==0 else ('Yes' if row==0 else 'No'),fontsize=10)
        cells.append(raw_cell(1,col,'merged',[x,120,x+65,148]))
    model=from_docling({'num_rows':2,'num_cols':4,'table_cells':cells},p)
    result=categorical_subrows(p,model);assert result['num_rows']==3
    assert next(c for c in result['cells'] if c['row']==2 and c['column']==1)['text']=='No'
    pdf2=fitz.open();p2=pdf2.new_page()
    for col,x in enumerate([50,180,260,340]):
        for text,y in [('paragraph',130),('continued',145)]:p2.insert_text((x,y),text,fontsize=10)
    assert categorical_subrows(p2,model) is None

def figure_fixture():
    doc=fitz.open();p=doc.new_page(width=400,height=400)
    p.draw_rect((40,70,150,140));p.draw_rect((190,70,300,140))
    p.insert_text((40,165),'(a) Red square result.',fontsize=10);p.insert_text((185,165),'(b) Blue square result.',fontsize=10)
    p.insert_text((40,195),'Figure 9: Results in 9(a) and 9(b).',fontsize=10)
    def b(id,kind,text,order,rect):return {'id':id,'type':kind,'text':text,'reading_order':order,'section_id':'s1',
        'regions':[{'page_index':0,'bbox':[v/400 for v in rect]}],'data':{'assets':[]},'quality_flags':[]}
    return doc,[b('p','picture','',0,[30,60,310,150]),b('t','list_item','(a) Red square result. (b) Blue square result.',1,[40,154,290,169]),
                b('c','caption','Figure 9: Results in 9(a) and 9(b).',3,[40,183,300,198])]

def test_embedded_panels_require_labels_caption_and_real_empty_gutter():
    doc,blocks=figure_fixture();result=embedded_panel_groups(doc,blocks,'r',10)
    group=next(b for b in result if b['type']=='figure_group');assert len(group['regions'])==5 and len(group['data']['panels'])==2
    panels=[b for b in result if b['type']=='figure_panel'];assert panels[0]['regions'][0]['bbox'][2]<=panels[1]['regions'][0]['bbox'][0]
    assert all(b['data']['verification']=='unverified' for b in panels)

def test_intervening_body_or_competing_caption_prevents_figure_binding():
    for mode in ['body','duplicate','wrong_labels']:
        doc,blocks=figure_fixture()
        if mode=='wrong_labels':blocks[-1]['text']='Figure 9: An unrelated picture.'
        else:
            extra=copy.deepcopy(blocks[-1]);extra['id']='other';extra['reading_order']=2
            if mode=='body':extra.update(type='text',text='Unrelated body');extra['regions'][0]['bbox'][1]=.44
            blocks.insert(2,extra)
        assert not any(b['type']=='figure_group' for b in embedded_panel_groups(doc,blocks,'r',10))
