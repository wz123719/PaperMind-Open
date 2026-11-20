"""Conservative bidirectional TeX-table/PDF alignment; no answer replacement."""
import re,unicodedata
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from .tex_source import group,SourceFailure

VERSION='source-table-align-1'

def plain(text):
    text=re.sub(r'\\(?:label|cite\w*|ref|eqref)\s*\{[^{}]*\}','',text)
    text=re.sub(r'\\rule\s*\{[^{}]*\}\s*\{[^{}]*\}','',text)
    for _ in range(8):
        new=re.sub(r'\\(?:textbf|textit|textsc|textrm|mathrm|mathbf|mathit|boldsymbol|bm|emph|mbox|text|underline|overline)\s*\{([^{}]*)\}',r'\1',text)
        if new==text:break
        text=new
    text=re.sub(r'\\(?:bf|rm|it|small|footnotesize|scriptsize|displaystyle|left|right)\b','',text)
    for command,value in [('cdot','·'),('times','×'),('pm','±'),('percent','%')]:text=text.replace('\\'+command,value)
    text=re.sub(r'\\([%&#_])',r'\1',text)
    return unicodedata.normalize('NFKC',text)

def signature(text):
    # Retain decimal points, signs and mathematical relations: 3.5 != 35 and
    # n^2 != n2. Whitespace, TeX grouping and typography may differ harmlessly.
    return re.sub(r'[^a-z0-9_.+\-^()/=%×·±]+','',plain(text).lower())

def caption(obj):
    m=re.search(r'\\caption\*?(?:\[[^]]*\])?\s*\{',obj.get('expanded',''))
    if not m:return ''
    try:return group(obj['expanded'],m.end()-1)[0]
    except SourceFailure:return ''

def caption_signature(text):return signature(re.sub(r'^\s*Table\s*\d+[a-z]?\s*[:.]?','',text,flags=re.I))

def match_features(obj,block):
    source=obj.get('table_model') or {};pdf=block['data'].get('table_model') or {}
    a={signature(c['text']) for c in source.get('cells',[]) if signature(c['text'])}
    b={signature(c['text']) for c in pdf.get('cells',[]) if signature(c['text'])}
    cap=caption_signature(caption(obj));other=caption_signature(block['data'].get('caption') or '')
    cap_score=SequenceMatcher(None,cap,other,autojunk=False).ratio() if cap and other else 0
    common=a&b;coverage=len(common)/max(1,min(len(a),len(b)))
    numbers_a={plain(c['text']).strip() for c in source.get('cells',[]) if re.fullmatch(r'[-+]?\d+(?:\.\d+)?',plain(c['text']).strip())}
    numbers_b={plain(c['text']).strip() for c in pdf.get('cells',[]) if re.fullmatch(r'[-+]?\d+(?:\.\d+)?',plain(c['text']).strip())}
    numeric=len(numbers_a&numbers_b)/max(1,len(numbers_a))
    cols=source.get('num_columns')==pdf.get('num_columns')
    enough=len(common)>=6 or len(numbers_a&numbers_b)>=4
    supported=bool(cols and enough and coverage>=.55 and (cap_score>=.78 or coverage>=.88 and len(common)>=12))
    return {'caption_similarity':round(cap_score,5),'shared_distinct_cells':len(common),'cell_coverage':round(coverage,5),
            'numeric_coverage':round(numeric,5),'matching_column_count':cols,'supported':supported,
            'score':round(.5*cap_score+.4*coverage+.1*numeric,5)}

def bind_cells(obj,block):
    source=obj['table_model'];pdf=block['data']['table_model'];lookup=defaultdict(list)
    for c in pdf['cells']:
        value=signature(c['text'])
        if value:lookup[value].append(c)
    choices={};votes=defaultdict(Counter)
    for n,c in enumerate(source['cells']):
        value=signature(c['text'])
        if not value:continue
        found=[p for p in lookup[value] if p['column']<=c['column']<p['column']+p['column_span']]
        choices[n]=found
        if len(found)==1:votes[c['row']][found[0]['row']]+=1
    row_map={}
    for row,counts in votes.items():
        ranked=counts.most_common()
        if ranked[0][1]>=2 and (len(ranked)==1 or ranked[0][1]>ranked[1][1]):row_map[row]=ranked[0][0]
    bindings=[];differences=[]
    for n,c in enumerate(source['cells']):
        if not signature(c['text']):continue
        found=choices.get(n,[])
        if c['row'] in row_map:
            found=[p for p in found if p['row']<=row_map[c['row']]<p['row']+p['row_span']]
        if len(found)!=1:
            differences.append({'source_cell_index':n,'source_row':c['row'],'source_column':c['column'],
                'raw_text':c['raw_text'],'status':'ambiguous' if found else 'unmatched','candidate_count':len(found)})
            continue
        p=found[0]
        # Repeated body values without row corroboration cannot pick a row.
        entry={'source_cell_index':n,'source_row':c['row'],'source_column':c['column'],'raw_text':c['raw_text'],
            'source_text':c['text'],'pdf_text':p['text'],'pdf_row':p['row'],'pdf_column':p['column'],
            'pdf_row_span':p['row_span'],'pdf_column_span':p['column_span'],'regions':p.get('regions',[]),
            'column_headers':p.get('column_headers',[]),'row_headers':p.get('row_headers',[]),
            'status':'candidate_exact_cell_and_row_evidence' if c['row'] in row_map else 'candidate_unique_cell',
            'verification':'unverified'}
        if not entry['regions']:continue
        if (c['row_span'],c['column_span'])!=(p['row_span'],p['column_span']):
            entry['structure_difference']={'source_span':[c['row_span'],c['column_span']],'pdf_span':[p['row_span'],p['column_span']]}
        bindings.append(entry)
        p.setdefault('source_cells',[]).append({'source_object_id':obj['id'],'file':obj['file'],'line':obj['line'],
            'cell_index':n,'row':c['row'],'column':c['column'],'raw_text':c['raw_text'],'verification':'unverified'})
    return bindings,differences

def align_tables(document,blocks):
    all_source=[o for o in document.get('objects',[]) if o['kind']=='table']
    source=[o for o in all_source if o.get('table_model')]
    for obj in all_source:
        if not obj.get('table_model'):obj['pdf_mapping']={'status':'unknown','reason':'unsupported_source_table_structure','regions':[],'route':'pdf_fallback'}
    pdf=[b for b in blocks if b['type']=='table' and b['data'].get('table_model')]
    scores={}
    for obj in source:
        pairs=[]
        for block in pdf:
            features=match_features(obj,block);scores[obj['id'],block['id']]=features
            pairs.append({'block_id':block['id'],**features})
        obj['pdf_candidates']=sorted(pairs,key=lambda p:-p['score'])
    for obj in source:
        candidates=[p for p in obj['pdf_candidates'] if p['supported']]
        reason='no_supported_content_match'
        if candidates:
            top=candidates[0];others=[scores[o['id'],top['block_id']] for o in source if o is not obj]
            if len(candidates)>1 and top['score']-candidates[1]['score']<.10:reason='ambiguous_pdf_tables'
            elif any(p['supported'] and top['score']-p['score']<.10 for p in others):reason='ambiguous_source_tables'
            else:
                block=next(b for b in pdf if b['id']==top['block_id'])
                cells,differences=bind_cells(obj,block)
                if len(cells)>=4:
                    obj['pdf_mapping']={'status':'candidate_content_and_caption_unique','block_id':block['id'],
                        'regions':block['regions'],'features':top,'cells':cells,'differences':differences,'verification':'unverified'}
                    block['data']['source_object_id']=obj['id']
                    block['data']['source_table']={'object_id':obj['id'],'file':obj['file'],'line':obj['line'],
                        'raw_definition':obj['raw'],'expanded_definition':obj['expanded'],'labels':obj.get('labels',[]),
                        'route':'pdf_canonical_with_source_alignment','mapping_status':obj['pdf_mapping']['status'],
                        'features':top,'cells':cells,'differences':differences,'verification':'unverified'}
                    continue
                reason='insufficient_unambiguous_cells'
        obj['pdf_mapping']={'status':'unknown','reason':reason,'regions':[],'route':'pdf_fallback','verification':'unverified'}
    document['table_alignment']={'version':VERSION,'source_tables':len(all_source),'eligible_tables':len(source),
        'mapped_tables':sum(o['pdf_mapping']['status']!='unknown' for o in source),'verification':'unverified'}
