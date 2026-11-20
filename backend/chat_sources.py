"""Server-owned selection mapping and bounded paper-local lexical retrieval."""
import re
import unicodedata
from . import parsing,reading
from .reading_provider import ReadingFailure

SOURCE_VERSION='chat-source-2-symbols'
MAX_SELECTION=4000
MAX_SOURCE=16000

def page_text_matches(doc,page_index,text):
    """A multi-page parsed block alone cannot prove a selection came from this page."""
    import pymupdf
    from sqlalchemy import select
    from .db import engine,paper_files
    from .files import file_path
    from .parse_api import SEARCH_LOCK
    with engine.connect() as c:
        file=c.execute(select(paper_files).where(paper_files.c.id==doc['run']['paper_file_id'])).mappings().first()
    if not file or file['sha256']!=doc['run']['file_sha256']:raise ReadingFailure('选文PDF身份校验失败')
    with SEARCH_LOCK,pymupdf.open(file_path(file['relative_path'])) as pdf:
        if not 0<=page_index<len(pdf):return False
        actual,_=normalized(pdf[page_index].get_text())
    needle,_=normalized(text)
    return next(matches(actual,needle),None) is not None

def normalized(text):
    """Keep operators, token boundaries and soft hyphens. Offsets always refer to raw text.

    NFC + explicit presentation ligatures/fullwidth ASCII only, never general NFKC.
    A physical EOL after a retained hyphen may disappear; the hyphen itself cannot.
    """
    chars=[];spans=[];i=0
    ligatures={'\ufb00':'ff','\ufb01':'fi','\ufb02':'fl','\ufb03':'ffi','\ufb04':'ffl','\ufb05':'st','\ufb06':'st'}
    while i<len(text):
        if text[i].isspace():
            j=i+1
            while j<len(text) and text[j].isspace():j+=1
            # This never turns x-y into xy, and never discards a minus/soft hyphen.
            physical_wrap=(chars and chars[-1] in ('-','\u00ad') and '\n' in text[i:j]
                           and j<len(text) and text[j].isalpha())
            if chars and j<len(text) and not physical_wrap:chars.append(' ');spans.append((i,j))
            i=j;continue
        j=i+1
        while j<len(text) and unicodedata.combining(text[j]):j+=1
        cluster=unicodedata.normalize('NFC',text[i:j])
        for c in cluster:
            value=ligatures.get(c,chr(ord(c)-0xfee0) if 0xff01<=ord(c)<=0xff5e else c)
            for result in value:chars.append(result);spans.append((i,j))
        i=j
    return ''.join(chars),spans

def matches(haystack,needle):
    """Do not turn a substring of a signed/multi-digit number into another value."""
    if not needle:return
    offset=0
    while True:
        index=haystack.find(needle,offset)
        if index<0:return
        end=index+len(needle);previous=haystack[index-1] if index else ''
        following=haystack[end] if end<len(haystack) else ''
        numeric_start=needle[0].isdecimal() or (needle[0]=='.' and len(needle)>1 and needle[1].isdecimal())
        preceding_sign=haystack[:index].rstrip()[-1:]
        bad_start=numeric_start and (previous.isdecimal() or preceding_sign in ('-','+','\u2212','\u00ad'))
        bad_end=needle[-1].isdecimal() and following.isdecimal()
        if not bad_start and not bad_end:yield index
        offset=index+1

def candidate_id(source):
    return reading.digest({'source_version':SOURCE_VERSION,'source':source})

def fragment(block,start,end,rid):
    return {'parse_run_id':rid,'block_id':block['id'],'fragment_id':f"{block['id']}@{start}:{end}",
            'start':start,'end':end,'text':block['text'][start:end],
            'quality_flags':block['quality_flags']}

def map_selection(rid,selection):
    doc=parsing.structure(rid);run=doc['run']
    if (selection.get('parse_run_id')!=rid or selection.get('paper_file_id')!=run['paper_file_id']
            or selection.get('file_sha256')!=run['file_sha256']):
        raise ReadingFailure('选文来源版本不匹配，请重新选择')
    page=selection.get('page_index');text=selection.get('text','')
    if not isinstance(page,int) or isinstance(page,bool) or not 0<=page<len(run['pages'] or []):
        raise ReadingFailure('选文页码无效')
    if not isinstance(text,str) or not 1<=len(text)<=MAX_SELECTION:
        raise ReadingFailure('选文须为1至4000个Unicode字符，不会自动截断')
    # The DOM range is for audit only; it does not grant authority over parsed material.
    layer=selection.get('layer_text');start=selection.get('layer_start');end=selection.get('layer_end')
    if (not isinstance(layer,str) or len(layer)>200000 or not isinstance(start,int) or not isinstance(end,int)
            or not 0<=start<end<=len(layer) or layer[start:end]!=text):
        raise ReadingFailure('文字层范围无效；偏移须为Unicode code point半开区间')
    needle,_=normalized(text)
    if len(needle)<3:raise ReadingFailure('请至少选择3个可识别字符')
    if not page_text_matches(doc,page,text):
        return {'status':'unmatched','candidates':[],'candidate_limit':20,'offset_unit':'unicode_code_point',
                'source_version':SOURCE_VERSION,'reason':'所选文字未能在该PDF页的原生文字中确认，请重新选择'}
    blocks=[b for b in doc['blocks'] if b['text'].strip() and any(r['page_index']==page for r in b['regions'])
            and not b['data'].get('parent_block_id')]
    found={}
    for index in range(len(blocks)):
        for count in range(1,min(3,len(blocks)-index)+1):
            window=blocks[index:index+count];parts=[];positions=[]
            for block in window:
                if parts:parts.append(' ');positions.append(None)
                value,spans=normalized(block['text']);parts.append(value)
                positions.extend((block,a,b) for a,b in spans)
            haystack=''.join(parts)
            for location in matches(haystack,needle):
                if len(found)>=20:break
                grouped={}
                for position in positions[location:location+len(needle)]:
                    if position is None:continue
                    block,a,b=position
                    if block['id'] not in grouped:grouped[block['id']]=[block,a,b]
                    else:grouped[block['id']][2]=b
                source=[fragment(b,a,z,rid) for b,a,z in grouped.values()]
                # A partial match inside an expanded ligature must not gain extra characters.
                if normalized(' '.join(s['text'] for s in source))[0]!=needle:continue
                identity=candidate_id(source)
                regions=[r for b,_,_ in grouped.values() for r in b['regions']]
                found[identity]={'candidate_id':identity,'source':source,'regions':regions,
                    'source_version':SOURCE_VERSION,
                    'preview':' … '.join(f['text'] for f in source),
                    'normalization':'保留负号/运算符/软连字符与词间边界；NFC及受限字形兼容，物理换行不删除连字符'}
    values=list(found.values())
    return {'status':'unmatched' if not values else 'ambiguous' if len(values)>1 else 'matched',
            'candidates':values,'candidate_limit':20,'offset_unit':'unicode_code_point','source_version':SOURCE_VERSION}

def confirmed(rid,selection):
    mapping=map_selection(rid,selection)
    candidate=next((x for x in mapping['candidates'] if x['candidate_id']==selection.get('candidate_id')),None)
    if not candidate:raise ReadingFailure('来源候选无效、过期或语义不匹配，请重新映射并确认')
    return {'page_index':selection['page_index'],'text':selection['text'],**candidate}

def context(doc,question,selection=None):
    blocks={b['id']:b for b in doc['blocks']};rid=doc['run']['id'];source=[]
    def add(item,required=False):
        if item['start']==item['end']:return
        if any(x['fragment_id']==item['fragment_id'] for x in source):return
        if len(__import__('json').dumps(source+[item],ensure_ascii=False))>MAX_SOURCE:
            if required:raise ReadingFailure('当前选文超过上下文预算，请缩小选文')
            return
        source.append(item)
    if selection:
        for item in selection['source']:add(item,True)
        for item in selection['source']:
            b=blocks[item['block_id']]
            add(fragment(b,max(0,item['start']-350),item['start'],rid))
            add(fragment(b,item['end'],min(len(b['text']),item['end']+350),rid))
        return source,{'version':SOURCE_VERSION,'mode':'selection_with_separate_neighbors','hits':len(source)}
    terms=set(re.findall(r'[A-Za-z0-9_]{2,}',question.lower()))
    for segment in re.findall(r'[\u4e00-\u9fff]+',question):
        terms.update(segment[i:i+2] for i in range(len(segment)-1))
    titles={s['id']:s['title'].lower() for s in doc['sections']}
    scored=[]
    for block in doc['blocks']:
        lowered=block['text'].lower()
        hits=[term for term in terms if term in lowered]
        score=sum(min(lowered.count(term),3) for term in hits)+sum(2 for t in terms if t in titles.get(block['section_id'],''))
        if score and block['regions']:
            first=min((lowered.find(t) for t in hits),default=0)
            scored.append((-score,block['reading_order'],block,max(0,first-350)))
    for _,_,block,start in sorted(scored,key=lambda x:(x[0],x[1]))[:8]:
        add(fragment(block,start,min(len(block['text']),start+1600),rid))
    return source,{'version':SOURCE_VERSION,'mode':'paper_local_lexical','terms':sorted(terms),
                   'hits':len(source),'status':'matched' if source else 'no_hits',
                   'scope':'仅本次检索片段，不代表阅读全文'}
