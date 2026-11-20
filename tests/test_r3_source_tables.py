import copy
from backend.source_tables import align_tables

def cell(row,col,text,span=1):return {'row':row,'column':col,'row_span':1,'column_span':span,'text':text,'raw_text':text}

def fixture():
    cells=[cell(0,0,'Method'),cell(0,1,'MetricSet',2),cell(1,1,'Red'),cell(1,2,'Blue'),
           cell(2,0,'Alpha'),cell(2,1,'11'),cell(2,2,'13'),cell(3,0,'Beta'),cell(3,1,'17'),cell(3,2,'19')]
    source={'id':'s1','kind':'table','file':'body.tex','line':25,'raw':'original definition',
        'expanded':r'\caption{Independent results for anonymous models.}\label{tab:same}',
        'table_model':{'num_columns':3,'cells':copy.deepcopy(cells)}}
    pdfcells=[{**c,'regions':[{'page_index':2,'bbox':[.1+c['column']*.1,.1+c['row']*.05,.2+c['column']*.1,.14+c['row']*.05]}],
               'column_header':c['row']<2,'column_headers':[{'text':'MetricSet'},{'text':'Red' if c['column']==1 else 'Blue'}]} for c in cells]
    block={'id':'b1','type':'table','regions':[{'page_index':2,'bbox':[.1,.1,.5,.4]}],
        'data':{'caption':'Table 7: Independent results for anonymous models.','table_model':{'num_columns':3,'cells':pdfcells}}}
    return source,block

def test_source_table_unique_content_binds_real_cell_regions_with_headers_and_raw_evidence():
    source,block=fixture();doc={'objects':[source]};align_tables(doc,[block])
    mapping=source['pdf_mapping'];assert mapping['block_id']=='b1' and len(mapping['cells'])==10
    parent=next(c for c in mapping['cells'] if c['source_text']=='MetricSet');assert parent['pdf_column_span']==2
    value=next(c for c in mapping['cells'] if c['source_text']=='17');assert value['pdf_row']==3 and value['regions']
    assert block['data']['source_table']['file']=='body.tex' and block['data']['source_table']['raw_definition']=='original definition'
    assert block['data']['table_model']['cells'][-1]['source_cells'][0]['source_object_id']=='s1'
    assert mapping['verification']=='unverified'

def test_identical_source_or_pdf_tables_are_ambiguous_not_assigned_by_number_or_order():
    for which in ['source','pdf']:
        source,block=fixture();other=copy.deepcopy(source if which=='source' else block);other['id']='duplicate'
        doc={'objects':[source,other] if which=='source' else [source]}
        align_tables(doc,[block,other] if which=='pdf' else [block])
        assert source['pdf_mapping']['status']=='unknown' and source['pdf_mapping']['regions']==[]
        assert 'source_table' not in block['data']

def test_duplicate_caption_numbers_require_actual_matching_content():
    source,block=fixture();wrong=copy.deepcopy(block);wrong['id']='wrong'
    for c in wrong['data']['table_model']['cells']:c['text']='unrelated'
    align_tables({'objects':[source]},[wrong,block]);assert source['pdf_mapping']['block_id']=='b1'

def test_conflicting_cell_not_replaced_and_unmatched_evidence_is_retained():
    source,block=fixture();block['data']['table_model']['cells'][-1]['text']='999'
    align_tables({'objects':[source]},[block])
    assert source['pdf_mapping']['status']!='unknown'
    assert source['pdf_mapping']['differences'][-1]['raw_text']=='19'
    assert block['data']['table_model']['cells'][-1]['text']=='999'

def test_cell_signature_preserves_numeric_and_math_differences():
    from backend.source_tables import signature
    assert signature('3.5')!=signature('35')
    assert signature('-17')!=signature('17')
    assert signature(r'n^{2}')!=signature('n2')
    assert signature(r'\textbf{3.5}')==signature('3.5')
