import copy
import pymupdf as fitz
from backend.pdf_rules import rule_segments
from backend.native_math import group_lines,layout_latex
from backend.math_layout_checks import layout_checks
from backend.algorithm_layout import boxed_algorithms,step_bands
from backend.structure_refinement import algorithm_steps
from backend.figure_panels import embedded_panel_groups
from backend.reading_layout import column_order,split_metadata_body
from backend.table_structure import source_relationships
from test_structure_refinement import glyph

def block(id,kind,rect,text='',order=0):
    return {'id':id,'type':kind,'text':text,'reading_order':order,'section_id':'s','regions':[{'page_index':0,'bbox':rect}],
            'quality_flags':[],'source':'fixture','data':{'assets':[]}}

def test_stretched_bitmask_rules_are_actual_black_rules_not_arbitrary_images():
    doc=fitz.open();p=doc.new_page(width=400,height=400)
    x=doc.get_new_xref();doc.update_object(x,'<<>>')
    doc.update_stream(x,b'q 30 0 0 0.5 50 200 cm BI /W 1 /H 1 /BPC 1 /IM true /D [1 0] /F /AHx ID 80> EI Q')
    p.set_contents(x)
    rules=rule_segments(p,p.rect)
    assert len(rules)==1 and rules[0]['source']=='monochrome_1bit_inline_mask'
    pix=fitz.Pixmap(fitz.csGRAY,fitz.IRect(0,0,2,2),False);pix.clear_with(0)
    p.insert_image(fitz.Rect(90,190,120,191),pixmap=pix)
    assert len(rule_segments(p,p.rect))==1

def test_argument_minimum_fraction_and_limits_survive_source_geometry():
    chars=[glyph('a',10,100),glyph('r',15,100),glyph('g',20,100),glyph('m',25,100),glyph('i',32,100),glyph('n',35,100),
           glyph('z',28,108,size=7),glyph('1',50,94),glyph('q',50,108)]
    text=layout_latex(chars,[fitz.Rect(48,98,58,98.4)])
    assert r'\arg \min_{z}' in text and r'\frac{1}{q}' in text

def test_native_line_grouping_never_duplicates_late_small_script_glyphs():
    a=glyph('a',10,30);b=glyph('b',20,30);small=glyph('j',25,33,size=7)
    a['line']=0;b['line']=1;small['line']=2
    out=group_lines([a,b,small]);assert sum(len(g['chars']) for g in out)==3
    assert len({id(c) for g in out for c in g['chars']})==3

def test_nested_script_scope_is_not_promoted_to_outer_function():
    cs=[glyph('F',10,50),glyph('p',17,53,size=7),glyph('k',22,50,size=5)]
    text=layout_latex(cs,[])
    assert 'F_{p^{k}}' in text

def test_missing_radical_scope_is_a_support_failure_not_syntax_success():
    root=glyph('r',10,40,token=r'\sqrt');x=glyph('x',20,40)
    assert 'radical_scope_without_source_rule' in layout_checks([root,x],[],r'\sqrt x')
    bar=fitz.Rect(root['bbox'][2],root['bbox'][1]+1,40,root['bbox'][1]+1.4)
    assert not layout_checks([root,x],[bar],r'\sqrt{x}')

def boxed_fixture(numbered=True):
    doc=fitz.open();p=doc.new_page(width=400,height=500);p.draw_rect((40,80,350,290))
    p.insert_text((45,100),'Input: examples and coefficients',fontsize=10)
    p.insert_text((45,116),'Output: updated state',fontsize=10)
    lines=['1: for each example do','2: update state','3: end for','4: return result'] if numbered else ['a <- b','c <- d','e <- f','g <- h']
    for i,text in enumerate(lines):p.insert_text((45,145+i*28),text,fontsize=10)
    p.insert_text((45,306),'Algorithm 7: Anonymous procedure.',fontsize=10)
    return doc,p

def test_boxed_numbered_algorithm_requires_physical_boundary_and_header_evidence():
    doc,p=boxed_fixture();found=boxed_algorithms(p);assert len(found)==1
    steps=step_bands(p,found[0]['rect'])
    assert [s['source_step_number'] for s in steps if s['kind']=='step']==[1,2,3,4]
    assert [s['kind'] for s in steps][:2]==['input','output']

def test_unboxed_caption_or_multiline_equation_does_not_create_algorithm():
    doc=fitz.open();p=doc.new_page(width=400,height=500)
    p.insert_text((45,306),'Algorithm 7: A caption alone.',fontsize=10)
    assert boxed_algorithms(p)==[]
    p.draw_rect((40,80,350,290));p.insert_text((45,100),'x = y + z\na = b + c\np = q + r',fontsize=10)
    assert boxed_algorithms(p)==[]

def test_existing_caption_above_code_layout_remains_line_based_and_indented():
    doc=fitz.open();p=doc.new_page(width=400,height=500)
    for text,x,y in [('Require: state',40,100),('while active do',40,120),('update state',55,140),('end while',40,160)]:p.insert_text((x,y),text,fontsize=10)
    b=block('r:b000000','code',[.09,.17,.7,.34]);children=algorithm_steps(doc,b,'r',1)
    assert len(children)==4 and children[2]['data']['indent_level']>children[1]['data']['indent_level']

def test_scientific_exponent_uses_size_baseline_and_rejects_wrapped_plain_digits():
    doc=fitz.open();p=doc.new_page(width=400,height=400)
    p.insert_text((50,100),'1.2 x 10',fontsize=10);p.insert_text((90,96),'5',fontsize=7)
    model={'num_rows':1,'num_columns':1,'source':'raw','checks':[],'cells':[{'row':0,'column':0,'row_span':1,'column_span':1,'text':'1.2 x 10 5','column_header':False,'row_header':False,'regions':[{'page_index':0,'bbox':[.12,.21,.25,.27]}]}]}
    value=source_relationships(p,p.rect,model);assert value and '^{5}' in value['cells'][0]['text']
    doc2=fitz.open();q=doc2.new_page(width=400,height=400)
    q.insert_text((50,100),'10',fontsize=10);q.insert_text((50,115),'5',fontsize=10)
    assert source_relationships(q,q.rect,model) is None

def test_three_internal_labels_need_caption_evidence_and_ink_gutters():
    doc=fitz.open();p=doc.new_page(width=600,height=400)
    for x in [40,180,320]:p.draw_rect((x,50,x+100,120))
    for text,x in [('(a)',80),('(b) Without condition',175),('(c) With condition',315)]:p.insert_text((x,140),text,fontsize=9)
    picture=block('p','picture',[.05,.1,.73,.36]);caption=block('c','caption',[.05,.4,.75,.47],'Figure 2: (a) output. (b, c) other outputs.',1)
    out=embedded_panel_groups(doc,[copy.deepcopy(picture),copy.deepcopy(caption)],'r',10)
    group=next(b for b in out if b['type']=='figure_group');assert len(group['data']['panels'])==3 and len(group['regions'])==7
    caption['text']='Figure 2: (a) only one referenced panel.'
    assert not any(b['type']=='figure_group' for b in embedded_panel_groups(doc,[picture,caption],'r',10))

def test_independent_neighbor_figures_without_contiguous_panel_labels_stay_separate():
    doc=fitz.open();doc.new_page(width=600,height=400)
    pictures=[block('p1','picture',[.1,.1,.3,.3]),block('p2','picture',[.4,.1,.6,.3])]
    caption=block('c','caption',[.1,.4,.7,.5],'Figure 2: (a, b) compare.',2)
    assert not any(b['type']=='figure_group' for b in embedded_panel_groups(doc,pictures+[caption],'r',10))

def test_two_column_order_uses_full_width_bands_and_keeps_children_with_parent():
    blocks=[block('title','section_header',[.1,.05,.9,.09],order=0)]
    for i,y in enumerate([.2,.4,.6]):blocks.append(block('R'+str(i),'text',[.55,y,.9,y+.05],order=i+1))
    for i,y in enumerate([.2,.4,.6]):blocks.append(block('L'+str(i),'text',[.1,y,.45,y+.05],order=i+4))
    child=block('inline','formula',[.12,.4,.2,.42],order=8);child['data']['parent_block_id']='L1';blocks.append(child)
    ordered=[b['id'] for b in column_order(blocks)]
    assert ordered.index('L2')<ordered.index('R0') and ordered.index('inline')==ordered.index('L1')+1

def test_overlapping_fraction_and_independent_line_form_one_complete_math_child():
    from backend.inline_math import merge_candidates
    frac={'bbox':[20,20,40,40],'source':'fraction'};display={'bbox':[10,20,80,40],'source':'display'}
    assert merge_candidates([frac],[display])==[display]
    assert len(merge_candidates([frac],[{**display,'bbox':frac['bbox']}]))==1

def test_source_candidate_with_different_operand_is_retained_as_conflict():
    from backend.source_adapter import match_math
    native=r'g(x)=\frac{1}{1+\exp(-x)}+\alpha+\beta+\gamma+\delta'
    source=native.replace('g(x)','g(t)')
    obj={'id':'s1','kind':'display_math','raw':source,'expanded':source,'file':'main.tex','line':2,'checks':[]}
    candidate=match_math({'status':'available','objects':[obj]},native,native_checks=[])
    assert candidate and 'source_pdf_identifier_conflict' in candidate['checks'] and candidate['raw']==source

def test_math_only_extensible_piece_does_not_become_a_complete_expression():
    from backend.algorithm_layout import math_runs
    doc=fitz.open();page=doc.new_page();c=glyph('p',10,20,token=r'\sqrt');c['font']='CMEX10'
    assert math_runs(page,[c])==[]

def test_roman_named_function_before_brackets_remains_one_operator():
    cs=[glyph(c,10+i*5,30) for i,c in enumerate('Var[x]')]
    for c in cs[:3]:c['font']='Times-Roman'
    assert r'\operatorname{Var}' in layout_latex(cs,[])

def test_source_word_gaps_are_retained_when_pdf_has_no_literal_spaces():
    from backend.algorithm_layout import spaced_text
    cs=[glyph('Train',10,30),glyph('N',40,30),glyph('to',55,30)]
    cs[0]['bbox'][2]=35;cs[1]['bbox'][2]=45
    assert spaced_text(cs)=='Train N to'
