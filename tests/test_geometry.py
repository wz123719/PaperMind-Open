import pytest
from backend.geometry import page_info,pdf_rect
from geometry_fixture import build

def test_40_authored_geometry_regions_rotation_crop_and_scale(tmp_path):
    import pymupdf as fitz
    path=tmp_path/'geometry.pdf'
    annotations=build(path,tmp_path/'annotations.json')
    assert len(annotations)==40
    with fitz.open(path) as pdf:
        for r in annotations:
            page=pdf[r['page_index']]
            info=page_info(page)
            assert info['rotation']==r['rotation']
            assert info['pdf_view']==pytest.approx(r['cropbox'])
            reconstructed=pdf_rect(r['bbox'],info['pdf_view'])
            assert reconstructed==pytest.approx(r['pdf_rect'],abs=1e-6)
            # Independent renderer transform: PDF user-space -> MuPDF unrotated -> rotated -> scaled.
            rotation=page.rotation;page.set_rotation(0)
            unrotated=fitz.Rect(r['pdf_rect'])*page.transformation_matrix
            page.set_rotation(rotation)
            display=unrotated*page.rotation_matrix
            for scale in (.6,1,1.4,2):
                box=display*fitz.Matrix(scale,scale)
                assert 0<=box.x0<box.x1<=page.rect.width*scale+.001
                assert 0<=box.y0<box.y1<=page.rect.height*scale+.001
            # Extraction is independently in unrotated cropped coordinates.
            matches=page.search_for(r['label'])
            assert matches
            intersection=matches[0]&unrotated
            assert (intersection.width*intersection.height)/(matches[0].width*matches[0].height)>.99

def test_multiregion_contract_retains_pages_and_distinct_rectangles():
    from backend.parse_pipeline import make_block
    rs=[{'page_index':0,'bbox':[.1,.8,.4,.9]}, {'page_index':1,'bbox':[.1,.1,.4,.2]},
        {'page_index':1,'bbox':[.6,.1,.9,.2]}]
    block=make_block('run',1,'text','across pages',rs,'geometry_fixture')
    assert block['regions']==rs and len(block['regions'])==3
