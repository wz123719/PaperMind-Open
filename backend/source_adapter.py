"""Source/PDF alignment adapter; uncertain matches remain unmapped candidates."""
import hashlib,re
from difflib import SequenceMatcher
from .tex_source import unpack,parse_source,SourceFailure
from .files import file_path

def math_signature(text):
    text=re.sub(r'\\(?:label|tag)\{[^}]*\}','',text)
    text=re.sub(r'\\(?:left|right|quad|qquad|displaystyle|nonumber|notag)\b|\\[,!;:]','',text)
    text=re.sub(r'\\(?:operatorname|mathrm|mathit|mathbf|boldsymbol|bm)\{([^{}]*)\}',r'\1',text)
    return re.sub(r'[\s{}&$]','',text).replace(r'\dfrac',r'\frac').replace(r'\tfrac',r'\frac')

def match_math(document,native,page=None,bbox=None,native_checks=None):
    if not document or document.get('status')!='available':return None
    sig=math_signature(native)
    if len(sig)<8:return None
    scores=[]
    pdf_numbers=set()
    if page is not None and bbox is not None:
        import pymupdf as fitz
        box=fitz.Rect(bbox)
        for word in page.get_text('words',clip=fitz.Rect(page.rect.width*.7,max(0,box.y0-3),page.rect.width,min(page.rect.height,box.y1+3))):
            label=re.fullmatch(r'\((\d{1,3})\)',word[4])
            if label:pdf_numbers.add(label[1])
    for obj in document['objects']:
        if obj['kind'] not in ('display_math','inline_math') or obj['checks']:continue
        other=math_signature(obj['expanded'])
        score=SequenceMatcher(None,sig,other,autojunk=False).ratio()
        if score>=.94:scores.append((score,obj))
    scores.sort(key=lambda x:-x[0])
    method='candidate_unique_token_match'
    # Static TeX counters are evidence only: excluded branches and compilation
    # options can make the exact-version archive differ from the distributed PDF.
    # Never use an inferred counter to override token/context alignment.
    if document.get('number_mapping_verified') is True and len(pdf_numbers)==1:
        numbered=[o for o in document['objects'] if o['kind']=='display_math' and not o['checks'] and o.get('number') in pdf_numbers]
        if len(numbered)==1:
            obj=numbered[0];similarity=SequenceMatcher(None,sig,math_signature(obj['expanded']),autojunk=False).ratio()
            if similarity>=.15:scores=[(similarity,obj)];method='candidate_exact_pdf_label_and_source_counter'
    if not scores and page is not None and bbox is not None:
        import pymupdf as fitz
        def words(text):
            text=re.sub(r'-\s*\n','',text)
            text=re.sub(r'\\[A-Za-z]+','',text)
            return re.findall(r'[a-z]{3,}',text.lower())
        box=fitz.Rect(bbox)
        before=words(page.get_textbox(fitz.Rect(max(0,box.x0-30),max(0,box.y0-140),min(page.rect.width,box.x1+30),box.y0)))
        after=words(page.get_textbox(fitz.Rect(max(0,box.x0-30),box.y1,min(page.rect.width,box.x1+30),min(page.rect.height,box.y1+110))))
        candidates=[]
        for obj in document['objects']:
            if obj['kind']!='display_math' or obj['checks']:continue
            a=SequenceMatcher(None,before,words(obj.get('context_before','')),autojunk=False).find_longest_match().size
            b=SequenceMatcher(None,after,words(obj.get('context_after','')),autojunk=False).find_longest_match().size
            similarity=SequenceMatcher(None,sig,math_signature(obj['expanded']),autojunk=False).ratio()
            if similarity>=.35 and ((a>=20 and b>=6) or (a>=12 and b>=12)):candidates.append(((a+b)*similarity,obj))
        candidates.sort(key=lambda x:-x[0])
        if candidates and (len(candidates)==1 or candidates[0][0]>=candidates[1][0]+10):
            score,obj=candidates[0];scores=[(min(.999,score/100),obj)];method='candidate_unique_both_side_source_context'
    if not scores or len(scores)>1 and scores[0][0]-scores[1][0]<.04:return None
    score,obj=scores[0]
    normalized=re.sub(r'\\label\{[^}]*\}','',obj['expanded']).replace('&','').strip()
    checks=list(obj['checks'])
    def identifiers(text):
        text=re.sub(r'\\(?:text|operatorname|mathrm|mathit|mathbf|boldsymbol|bm)\{([^{}]*)\}',r'\1',text)
        text=re.sub(r'\\[A-Za-z]+',' ',text)
        text=re.sub(r'\b(?:arg|min|max|log|exp|Var|Norm|RMS)\b',' ',text)
        return set(re.findall(r'[A-Za-z]',text))
    if native_checks is not None and not any(k.startswith('unmapped') for k in native_checks) and identifiers(native)!=identifiers(normalized):
        checks.append('source_pdf_identifier_conflict')
    return {'source':'restricted_tex','raw':obj['raw'],'normalized_latex':normalized,
            'source_object_id':obj['id'],'checks':checks,'alignment':{'status':method,'score':score},
            'source_file':obj['file'],'source_line':obj['line'],'verification':'unverified'}

def prepare_source(config,work):
    descriptor=config.get('source',{'status':'unavailable','reason':'source_not_requested'})
    if descriptor['status']!='available':return {**descriptor,'objects':[]}
    data=file_path(descriptor['archive_path']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=descriptor['archive_sha256']:raise SourceFailure('源文件哈希与提交指纹不一致')
    try:
        unpack(data,work/'_source');doc=parse_source(work/'_source')
        if not doc['objects']:return {**descriptor,**doc,'status':'not_parseable','reason':'source_wrapper_has_no_tex_objects'}
        return {**descriptor,**doc,'status':'available'}
    except SourceFailure as exc:return {**descriptor,'status':'parse_failed','reason':str(exc),'objects':[]}

def align_document(source,blocks):
    from .source_tables import align_tables
    align_tables(source,blocks)
    by_id={o['id']:o for o in source.get('objects',[])}
    for block in blocks:
        math=block['data'].get('math',{})
        for candidate in math.get('candidates',[]):
            oid=candidate.get('source_object_id')
            if oid in by_id:
                if 'source_pdf_identifier_conflict' in candidate.get('checks',[]):
                    by_id[oid]['pdf_mapping']={'status':'unknown_source_pdf_conflict','regions':[],'candidate_regions':block['regions'],'block_id':block['id']}
                    continue
                by_id[oid]['pdf_mapping']={'status':candidate['alignment']['status'],'block_id':block['id'],
                                            'regions':block['regions'],'score':candidate['alignment']['score']}
                block['data']['source_object_id']=oid
        # Match source headings/captions only to the corresponding PDF type.
        kinds={'section_header':{'part','chapter','section','subsection','subsubsection'},'caption':{'caption'}}.get(block['type'])
        if not kinds:continue
        def text_sig(t):return re.sub(r'[^\w]','',re.sub(r'^\s*[\d.]+','',t)).lower()
        matches=[o for o in source.get('objects',[]) if o['kind'] in kinds and text_sig(o['expanded'])==text_sig(block['text'])]
        if len(matches)==1:
            matches[0]['pdf_mapping']={'status':'candidate_exact_text','block_id':block['id'],'regions':block['regions']}
            block['data']['source_object_id']=matches[0]['id']
    return source
