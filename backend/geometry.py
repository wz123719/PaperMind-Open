"""Canonical regions: normalized, unrotated visible CropBox, top-left origin.

Coordinates [x0,y0,x1,y1] are fractions, pages are 0-indexed. PDF.js conversion:
xPDF=view[0]+x*viewWidth; yPDF=view[3]-y*viewHeight; then apply PDF.js viewport.
This handles CropBox offsets, page /Rotate and user zoom exactly once.
"""
def normalize_rect(rect, width, height):
    x0, y0, x1, y1 = rect
    return [max(0., min(1., x0/width)), max(0., min(1., y0/height)),
            max(0., min(1., x1/width)), max(0., min(1., y1/height))]

def region(page_index, bbox, width, height):
    return {'page_index': page_index, 'bbox': normalize_rect(bbox, width, height)}

def pdf_rect(bbox, view):
    x0,y0,x1,y1=bbox
    left,bottom,right,top=view
    return [left+x0*(right-left),top-y1*(top-bottom),left+x1*(right-left),top-y0*(top-bottom)]

def page_info(page):
    import pymupdf as fitz
    rotation = page.rotation
    page.set_rotation(0)  # in-memory only, source PDF never saved or modified
    width, height = page.rect.width, page.rect.height
    box = page.rect * ~page.transformation_matrix
    info = {'page_index': page.number, 'page_label': page.get_label() or str(page.number+1),
        'width_points': width, 'height_points': height, 'rotation': rotation,
        'pdf_view': list(box), 'coordinate_contract': 'normalized-unrotated-crop-topleft-v1'}
    page.set_rotation(rotation)
    return info
