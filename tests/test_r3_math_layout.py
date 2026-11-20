import json
import pymupdf as fitz
from backend.native_math import layout_latex,decorations
from backend.math_structure import math_tree
from test_structure_refinement import glyph

def test_overprinted_bar_binds_to_symbol_before_its_index_and_is_structural():
    a=glyph('a',10,25);i=glyph('k',15,27,size=7);bar=glyph('¯',10.1,25,token=r'\bar')
    bar['bbox']=[10.1,17,15.1,27]
    text=layout_latex([bar,a,i],[])
    assert r'\bar{a}' in text and '_{k}' in text
    tree=math_tree(text);assert 'decoration' in json.dumps(tree) and tree['checks']==[]

def test_ambiguous_accent_is_retained_as_unresolved_not_silently_attached():
    bar=glyph('¯',11,25,token=r'\bar');bar['bbox']=[10,17,20,27]
    a=glyph('a',10,25);b=glyph('b',14,25)
    result,unknown=decorations([bar,a,b]);assert unknown and len(result)==3

def test_transpose_applies_to_completed_scripted_operand_not_part_of_its_exponent():
    cs=[glyph('w',10,25),glyph('j',16,28,size=7),glyph('q',16,20,size=7),glyph('⊤',20,18,size=7,token=r'\top')]
    text=layout_latex(cs,[])
    assert r'\left(w_{j}^{q}\right)^{\top}' in text
    tree=math_tree(text);assert 'transpose' in json.dumps(tree) and tree['checks']==[]

def test_disconnected_small_sum_limits_expand_crop_but_neighbor_body_does_not(monkeypatch):
    import backend.math_regions as regions
    pdf=fitz.open();page=pdf.new_page()
    page.insert_text((50,100),'a = S z',fontsize=10);page.insert_text((80,83),'p',fontsize=7);page.insert_text((77,113),'k=2',fontsize=7)
    page.insert_text((78,65),'other',fontsize=10)
    cs=[glyph('a',50,100),glyph('=',65,100),glyph('S',80,100,token=r'\sum'),glyph('z',100,100),
        glyph('p',80,83,size=7),glyph('k',77,113,size=7),glyph('=',81,113,size=7),glyph('2',85,113,size=7),glyph('Q',80,65)]
    for n,c in enumerate(cs):c['line']=1 if n<4 else 2 if n==4 else 3 if n<8 else 4
    monkeypatch.setattr(regions,'characters',lambda page,clip:[c for c in cs if fitz.Rect(c['bbox']).intersects(clip)])
    result=regions.crop_math(page,fitz.Rect(45,90,115,103))
    assert result and result['bbox'][1]<83 and result['bbox'][3]>=113 and result['bbox'][1]>65
    tokens=[c['c'] for c in result['glyphs']];assert 'p' in tokens and '2' in tokens and 'Q' not in tokens
