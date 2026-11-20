"""40 explicitly labelled geometric reference regions, not semantic quality data.

Five hand-authored rectangles are repeated over 8 specified rotation/CropBox
conditions. References come from these drawing instructions, never extraction.
"""
import json
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject,RectangleObject

# PDF user-space rectangles (left, bottom, right, top), authored reference labels.
REFERENCES=[('Alpha',(75,680,260,710)),('Beta',(310,580,510,615)),
            ('Gamma',(85,430,285,465)),('Delta',(305,290,515,325)),
            ('Epsilon',(95,130,315,165))]

def build(destination,annotation_path):
    writer=PdfWriter();annotations=[]
    for crop in ([0,0,600,800],[30,40,570,760]):
        for rotation in (0,90,180,270):
            page=writer.add_blank_page(600,800)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            commands=[]
            for label,box in REFERENCES:
                x0,y0,x1,y1=box
                commands.append(f'0 0 0 RG {x0} {y0} {x1-x0} {y1-y0} re S BT /F1 12 Tf {x0+6} {y0+10} Td ({label} reference region) Tj ET')
                norm=[(x0-crop[0])/(crop[2]-crop[0]),(crop[3]-y1)/(crop[3]-crop[1]),
                      (x1-crop[0])/(crop[2]-crop[0]),(crop[3]-y0)/(crop[3]-crop[1])]
                annotations.append({'id':f'p{len(writer.pages)-1}-{label}','page_index':len(writer.pages)-1,
                    'label':label,'pdf_rect':list(box),'bbox':norm,'cropbox':crop,'rotation':rotation,
                    'provenance':'explicitly authored reference rectangle; requires visual check'})
            stream=DecodedStreamObject();stream.set_data('\n'.join(commands).encode())
            page[NameObject('/Contents')]=writer._add_object(stream)
            page.cropbox=RectangleObject(crop);page.rotate(rotation)
    writer.add_metadata({'/Title':'Geometry QA - 40 authored regions, rotations and crops','/DOI':'10.9999/papermind-geometry-fixture'})
    writer.write(destination)
    Path(annotation_path).write_text(json.dumps(annotations,indent=2),encoding='utf-8')
    return annotations
