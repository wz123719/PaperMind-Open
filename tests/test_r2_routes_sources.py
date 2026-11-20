import copy,gzip,io,json,tarfile
from pathlib import Path
from types import SimpleNamespace
import httpx,pytest,pymupdf as fitz
from backend.tex_source import unpack,parse_source,SourceFailure,expand_macros
from backend.source_files import register,registration,source_url
from backend.source_adapter import prepare_source,match_math
from backend.object_cache import ObjectCache
from backend.math_structure import math_tree
from backend.table_structure import refine_table
from backend import parsing
from backend.files import save_pdf
from conftest import pdf_bytes
from test_structure_refinement import block_for,raw_cell

def archive(files):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as t:
        for name,data in files.items():
            info=tarfile.TarInfo(name);data=data.encode() if isinstance(data,str) else data;info.size=len(data);t.addfile(info,io.BytesIO(data))
    return out.getvalue()

def test_source_archive_traversal_and_symlinks_rejected(tmp_path):
    with pytest.raises(SourceFailure):unpack(archive({'../../escape.tex':'bad'}),tmp_path/'a')
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w') as tar:
        m=tarfile.TarInfo('linked');m.type=tarfile.SYMTYPE;m.linkname='outside';tar.addfile(m)
    with pytest.raises(SourceFailure):unpack(out.getvalue(),tmp_path/'b')
    assert not (tmp_path.parent/'escape.tex').exists()

def test_source_main_inputs_macro_expansion_order_and_unknown(tmp_path):
    unpack(archive({'main.tex':r'\documentclass{article}\newcommand{\sq}[1]{#1^{2}}\begin{document}\section{First}\input{body}\section{Last}\end{document}',
                    'body.tex':r'\subsection{Child}$\frac{\sq{x}}{\sqrt{z}}$ $\unknown{q}$'}),tmp_path)
    doc=parse_source(tmp_path);objects=doc['objects']
    assert [x['expanded'] for x in objects if x['kind'].endswith('section')]==['First','Child','Last']
    math=next(o for o in objects if o['kind']=='inline_math')
    assert math['expanded']==r'\frac{x^{2}}{\sqrt{z}}' and math['file']=='body.tex' and not math['checks']
    assert any('unknown_command:unknown' in o['checks'] for o in objects)
    assert next(o for o in objects if o['expanded']=='Child')['parent_id']==next(o for o in objects if o['expanded']=='First')['id']
    assert doc['execution']=='none'

@pytest.mark.parametrize('files',[
    {'a.tex':r'\documentclass{article}\begin{document}\input{missing}\end{document}'},
    {'a.tex':r'\documentclass{article}\begin{document}\input{b}\end{document}','b.tex':r'\input{a}'},
    {'a.tex':r'\documentclass{article}\begin{document}a','b.tex':r'\documentclass{article}\begin{document}b'}])
def test_missing_cyclic_and_ambiguous_sources_fail_explicitly(files,tmp_path):
    unpack(archive(files),tmp_path)
    with pytest.raises(SourceFailure):parse_source(tmp_path)

def test_source_version_fingerprint_and_archive_hash_binding(tmp_path):
    from backend.db import STORAGE
    tmp_path=STORAGE
    pdf=tmp_path/'paper.pdf';pdf.write_bytes(pdf_bytes(arxiv='2401.01234v3'));record=save_pdf(pdf,'local')
    source=tmp_path/'source.tar.gz';source.write_bytes(archive({'main.tex':r'\documentclass{article}\begin{document}\section{Test}$x^3$\end{document}'}))
    before=parsing.submit(record['file_id'],'docling')
    from backend.source_files import identity
    file=identity(record['file_id']);meta={'pdf_sha256':file['sha256'],'arxiv_id':'2401.01234','arxiv_version':2,
            'url':'https://arxiv.org/src/2401.01234v3','retrieved_at':1,'status':'available'}
    with pytest.raises(SourceFailure):register(record['file_id'],source,meta)
    meta['arxiv_version']=3;saved=register(record['file_id'],source,meta)
    after=parsing.submit(record['file_id'],'docling');assert before['input_hash']!=after['input_hash']
    assert after['config']['source']['archive_sha256']==saved['archive_sha256']
    from backend.files import file_path
    file_path(saved['archive_path']).write_bytes(b'changed')
    assert registration(record['file_id'])['reason']=='source_hash_mismatch'

@pytest.mark.parametrize('url',['http://arxiv.org/src/2401.01234v3','https://example.com/src/2401.01234v3',
    'https://arxiv.org/src/2401.01234v4','https://arxiv.org/src/2401.01234','https://arxiv.org/src/2401.01234v3?x=1'])
def test_source_redirect_must_keep_exact_version_and_official_origin(url):
    with pytest.raises(SourceFailure):source_url(url,'2401.01234v3')

def test_cache_reuses_only_exact_file_image_region_model_config_and_detects_corruption(tmp_path):
    identity={'pdf':'a','source':'s','model':'m','config':{'version':1}}
    c=ObjectCache(identity,tmp_path);features={'page':0,'bbox':[0,0,1,1],'image':'sha'}
    c.put(features,{'latex':'x^{3}'});assert c.get(features)=={'latex':'x^{3}'}
    for key,value in [('pdf','b'),('source','t'),('model','n'),('config',{'version':2})]:
        changed=copy.deepcopy(identity);changed[key]=value;assert ObjectCache(changed,tmp_path).get(features) is None
    assert c.get({**features,'image':'different'}) is None
    p=next(tmp_path.rglob('*.json'));d=json.loads(p.read_text());d['result']['latex']='wrong';p.write_text(json.dumps(d))
    assert c.get(features) is None

def test_math_tree_preserves_fraction_scripts_root_sum_and_content_unknown():
    tree=math_tree(r'\frac{a^{4}}{\sqrt{b_{n}}}+\sum_{j=1}^{k}z_j')
    encoded=json.dumps(tree)
    assert all(x in encoded for x in ['fraction','numerator','denominator','root','radicand','scripts','operator_relations','operand'])
    assert tree['verification']=='unverified'
    assert math_tree('x^{')['checks']

def test_source_alignment_requires_unique_supported_content():
    obj={'id':'s1','kind':'display_math','expanded':r'\frac{u^{3}}{v_{j}}','raw':'raw','file':'body.tex','line':9,'checks':[]}
    document={'status':'available','objects':[obj]}
    result=match_math(document,r'\frac{u^{3}}{v_{j}}')
    assert result['source_object_id']=='s1' and result['verification']=='unverified'
    assert match_math({**document,'objects':[obj,{**obj,'id':'s2'}]},r'\frac{u^{3}}{v_{j}}') is None
    assert match_math(document,r'\sqrt{u+v}') is None

def test_multiline_header_expands_only_with_actual_vertical_partition_and_keeps_values():
    pdf=fitz.open();p=pdf.new_page();xs=[50,150,250,350,450];top=100
    # Grouped header over three metrics, unrelated method header has its own partition.
    p.draw_line((150,100),(150,130));p.insert_text((55,112),'Method',fontsize=10)
    p.insert_text((280,112),'ScoreSet',fontsize=10)
    for x,t in [(180,'Red'),(280,'Green'),(380,'Blue')]:p.insert_text((x,125),t,fontsize=10)
    for x,t in [(55,'Model'),(180,'11'),(280,'13'),(380,'17')]:p.insert_text((x,145),t,fontsize=10)
    raw={'num_rows':2,'num_cols':4,'table_cells':[
        raw_cell(0,0,'Method',[55,100,100,115],True),raw_cell(0,1,'Red',[180,115,205,128],True),
        raw_cell(0,2,'ScoreSet Green',[278,100,325,128],True),raw_cell(0,3,'Blue',[380,115,410,128],True),
        *[raw_cell(1,c,t,[x,134,x+45,148]) for c,(x,t) in enumerate([(55,'Model'),(180,'11'),(280,'13'),(380,'17')])]]}
    b=block_for(raw,[50,98,450,150],p);refine_table(p,b)
    model=b['data']['table_model'];numeric=next(c for c in model['cells'] if c['text']=='17')
    assert [h['text'] for h in numeric['column_headers']]==['ScoreSet','Blue']
    parent=next(c for c in model['cells'] if c['text']=='ScoreSet');assert parent['column']==1 and parent['column_span']==3
    assert b['data']['table']==raw and 'ScoreSet' in b['text']

def test_source_fetch_api_queues_bounded_worker_job(client,tmp_path):
    from backend.db import STORAGE
    tmp_path=STORAGE
    pdf=tmp_path/'paper.pdf';pdf.write_bytes(pdf_bytes(arxiv='2401.01234v3'));record=save_pdf(pdf,'local')
    status=client.get('/v1/files/'+record['file_id']+'/source');assert status.status_code==200 and status.json()['status']=='unavailable'
    r=client.post('/v1/files/'+record['file_id']+'/source');assert r.status_code==202
    from backend.queue import get_job
    job=get_job(r.json()['job_id']);assert job['type']=='arxiv_source' and job['max_attempts']==3
    again=client.post('/v1/files/'+record['file_id']+'/source');assert again.json()['job_id']==job['id']

def test_delimited_math_environment_alias_and_matrix_rows_are_bounded_and_source_ordered(tmp_path):
    unpack(archive({'main.tex':r'\documentclass{article}\def\starts#1\stops{\begin{align}#1\end{align}}\begin{document}'
        r'\section{Setup}\starts A=\begin{bmatrix}a&b\\c&d\end{bmatrix}\\z=\frac{x}{y}\stops\end{document}'}),tmp_path)
    doc=parse_source(tmp_path);parents=[o for o in doc['objects'] if 'multi_line_source_parent' in o['checks']]
    assert len(parents)==1 and len(parents[0]['children'])==2
    children=[o for o in doc['objects'] if o['id'] in parents[0]['children']]
    assert r'a&b\\c&d' in children[0]['expanded'] and children[1]['expanded'].strip()==r'z=\frac{x}{y}'
    assert all(o['offset'][0]>doc['objects'][0]['offset'][0] for o in children)
    assert not any('#1' in o['raw'] for o in doc['objects'])

def test_math_tree_understands_tex_infix_over():
    tree=math_tree(r'{g_i\over\sigma_i}(a_i-\mu_i)')
    group=tree['expression']['items'][0]
    assert group['body']['items'][0]['type']=='fraction'

def test_supported_glyph_route_skips_image_inference_and_reuses_exact_cache(tmp_path,monkeypatch):
    import backend.local_math_backend as backend
    from test_structure_refinement import glyph
    from PIL import Image
    p=fitz.open();page=p.new_page()
    localized={'bbox':[10,10,60,40],'glyphs':[glyph('a',10,25),glyph('+',20,25),glyph('b',30,25)],'image':Image.new('RGB',(50,30),'white')}
    def forbidden(_):raise AssertionError('Image component must not run for supported glyph layout')
    session=SimpleNamespace(cache=ObjectCache({'pdf':'anonymous','config':1},tmp_path),route_events=[],source_document=None,recognize=forbidden)
    first=backend.recognize_region(page,localized,session);second=backend.recognize_region(page,localized,session)
    assert first==second and first['source']=='pdf_glyph_rule_layout'
    assert any(e['type']=='cache_hit' for e in session.cache.events)
    assert first['verification']=='unverified' and first['math_structure']

def test_root_rule_does_not_create_a_false_inline_fraction(monkeypatch):
    import backend.inline_math as inline
    from test_structure_refinement import glyph
    cs=[glyph('q',10,16,token=r'\sqrt'),glyph('a',22,6),glyph('b',22,12)]
    cs[0]['bbox']=[10,5,17,18]
    monkeypatch.setattr(inline,'characters',lambda *args:cs)
    monkeypatch.setattr(inline,'horizontal_bars',lambda *args:[fitz.Rect(17,7.8,34,8.2)])
    assert inline.fraction_candidates(None,fitz.Rect(0,0,100,100))==[]

def test_candidate_html_adapter_keeps_math_spans_and_never_invents_cell_regions():
    from backend.candidate_adapters import html_table
    model=html_table('<table><tr><th colspan="2">Metrics</th></tr><tr><td>Method</td><td>n<sup>4</sup></td></tr></table>')
    assert model['num_columns']==2 and model['cells'][0]['column_span']==2
    assert model['cells'][-1]['text']=='n^{4}' and model['cells'][-1]['math_structure']
    assert all(c['regions']==[] for c in model['cells'])
    assert model['verification']=='unverified'

def test_static_source_counter_cannot_override_unrelated_pdf_formula():
    pdf=fitz.open();page=pdf.new_page();page.insert_text((510,110),'(7)')
    obj={'id':'s7','kind':'display_math','number':'7','expanded':r'\sqrt{unrelated_{k}}',
         'raw':'raw','file':'main.tex','line':1,'checks':[]}
    assert match_math({'status':'available','objects':[obj]},r'\frac{x+y}{z}',page,[50,95,490,115]) is None

def test_empty_discard_macro_does_not_emit_hidden_math(tmp_path):
    unpack(archive({'main.tex':r'\documentclass{article}\newcommand{\hidden}[1]{}\begin{document}'
                   r'\hidden{\begin{equation}wrong=x\end{equation}}\begin{equation}visible=y\end{equation}\end{document}'}),tmp_path)
    doc=parse_source(tmp_path)
    assert not any('wrong' in obj['expanded'] for obj in doc['objects'])
    assert any('visible=y' in obj['expanded'] for obj in doc['objects'])

def test_alternative_failure_uses_one_bounded_fallback_and_keeps_failure_event(tmp_path,monkeypatch):
    import backend.local_math_backend as backend
    from PIL import Image
    page=fitz.open();p=page.new_page();calls=[]
    localized={'bbox':[1,1,30,15],'glyphs':[],'image':Image.new('RGB',(30,15),'white')}
    monkeypatch.setattr(backend,'layout_latex',lambda *a:'unknown')
    def alternative(image):calls.append('alternative');raise parsing.ParseFailure('object budget exceeded')
    def fallback(image):calls.append('rapid');return {'source':'rapid','raw':'x','normalized_latex':'x','checks':[],'elapsed_seconds':1}
    session=SimpleNamespace(config={'mineru_math_manifest_sha256':'m'},cache=ObjectCache({'pdf':'x'},tmp_path),
        source_document=None,route_events=[],recognize_alternative=alternative,recognize=fallback)
    result=backend.recognize_region(p,localized,session)
    assert calls==['alternative','rapid'] and result['source']=='rapid'
    assert any(e.get('route')=='mineru' and e['type']=='route_failed' for e in session.cache.events)
    assert result['verification']=='unverified' and result['route_history'][1]['status']=='failed'

def test_single_metric_multiline_header_is_not_promoted_over_adjacent_metrics():
    from backend.table_structure import source_relationships
    pdf=fitz.open();p=pdf.new_page()
    p.draw_line((150,90),(150,140))
    p.insert_text((165,105),'GroupA',fontsize=10)
    p.insert_text((170,120),'Score',fontsize=10)
    p.insert_text((280,120),'GroupB Score',fontsize=10)
    p.insert_text((410,120),'GroupC Score',fontsize=10)
    from backend.table_structure import from_docling
    raw={'num_rows':2,'num_cols':4,'table_cells':[
        raw_cell(0,0,'Method',[55,95,110,122],True),raw_cell(0,1,'GroupA Score',[165,95,205,123],True),
        raw_cell(0,2,'GroupB Score',[280,110,350,123],True),raw_cell(0,3,'GroupC Score',[410,110,480,123],True),
        *[raw_cell(1,c,t,[x,140,x+40,152]) for c,(x,t) in enumerate([(55,'Model'),(170,'11'),(280,'13'),(410,'17')])]]}
    model=from_docling(raw,p)
    assert source_relationships(p,fitz.Rect(50,90,500,155),model) is None

def test_centered_multiline_peer_header_does_not_become_a_group():
    from backend.table_structure import source_relationships,from_docling
    pdf=fitz.open();p=pdf.new_page();p.draw_line((150,90),(150,140))
    cells=[raw_cell(0,0,'Method',[55,95,110,122],True)]
    for col,x,name in [(1,180,'Alpha'),(2,290,'Beta'),(3,400,'Gamma')]:
        p.insert_text((x,105),name,fontsize=10);p.insert_text((x,120),'Score',fontsize=10)
        cells.append(raw_cell(0,col,name+' Score',[x,95,x+45,123],True))
    cells += [raw_cell(1,c,str(11+c),[x,140,x+40,152]) for c,x in enumerate([55,180,290,400])]
    model=from_docling({'num_rows':2,'num_cols':4,'table_cells':cells},p)
    assert source_relationships(p,fitz.Rect(50,90,500,155),model) is None
