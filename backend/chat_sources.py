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

ZH_ACADEMIC_MAP = {
    '摘要': ('abstract', 'summary', 'overview'),
    '总结': ('abstract', 'conclusion', 'summary'),
    '核心': ('key', 'core', 'main', 'central'),
    '贡献': ('contribution', 'propose', 'novel', 'introduce'),
    '创新': ('novel', 'contribution', 'propose'),
    '背景': ('introduction', 'background', 'preliminary', 'related'),
    '动机': ('motivation', 'challenge', 'problem', 'why'),
    '问题': ('problem', 'challenge', 'formulation'),
    '方法': ('method', 'methodology', 'approach', 'proposed'),
    '架构': ('architecture', 'framework', 'structure', 'module', 'network'),
    '模型': ('model', 'architecture', 'network'),
    '框架': ('framework', 'pipeline', 'overview'),
    '算法': ('algorithm', 'procedure', 'step'),
    '公式': ('equation', 'formulation', 'loss', 'objective', 'function'),
    '损失': ('loss', 'objective', 'criterion', 'regularization'),
    '优化': ('optimization', 'optimizer', 'gradient', 'training', 'convergence'),
    '梯度': ('gradient', 'backpropagation', 'derivative'),
    '推导': ('derivation', 'proof', 'theorem', 'proposition', 'lemma'),
    '定理': ('theorem', 'lemma', 'proposition', 'proof'),
    '实验': ('experiment', 'evaluation', 'empirical', 'setup', 'result'),
    '结果': ('result', 'performance', 'accuracy', 'score', 'comparison', 'table'),
    '消融': ('ablation', 'component', 'variant', 'effect'),
    '基线': ('baseline', 'benchmark', 'comparison', 'state', 'sota'),
    '对比': ('comparison', 'outperform', 'baseline', 'table'),
    '数据集': ('dataset', 'benchmark', 'corpus', 'split'),
    '指标': ('metric', 'accuracy', 'error', 'precision', 'recall', 'f1', 'bleu'),
    '超参数': ('hyperparameter', 'learning', 'rate', 'batch', 'epoch', 'schedule'),
    '训练': ('training', 'train', 'epoch', 'batch', 'optimizer'),
    '推理': ('inference', 'decoding', 'latency', 'speed', 'throughput'),
    '效率': ('efficiency', 'complexity', 'runtime', 'memory', 'speed', 'cost'),
    '复杂度': ('complexity', 'computational', 'memory', 'time'),
    '局限': ('limitation', 'weakness', 'drawback', 'failure', 'future', 'discussion'),
    '缺点': ('limitation', 'weakness', 'drawback'),
    '未来': ('future', 'direction', 'conclusion', 'discussion'),
    '复现': ('implementation', 'code', 'reproduce', 'detail', 'setup'),
    '注意力': ('attention', 'self-attention', 'transformer'),
    '编码': ('encoder', 'encoding', 'representation', 'embedding'),
    '解码': ('decoder', 'decoding', 'generation'),
    '特征': ('feature', 'representation', 'embedding'),
    '泛化': ('generalization', 'domain', 'robustness', 'transfer'),
    '微调': ('fine-tuning', 'finetuning', 'adaptation'),
    '预训练': ('pre-training', 'pretraining', 'pretrained'),
    '蒸馏': ('distillation', 'teacher', 'student'),
    '采样': ('sampling', 'sample', 'distribution'),
    '表格': ('table', 'result', 'comparison'),
    '图': ('figure', 'architecture', 'illustration'),
}


def _expand_cross_lingual_terms(question: str) -> tuple[set[str], set[str], bool]:
    en_terms = set(re.findall(r'[A-Za-z0-9_]{2,}', question.lower()))
    zh_terms = set()
    has_zh = False
    for segment in re.findall(r'[\u4e00-\u9fff]+', question):
        has_zh = True
        if len(segment) == 1:
            zh_terms.add(segment)
        else:
            zh_terms.update(segment[i:i+2] for i in range(len(segment) - 1))
    expanded_en = set()
    for zh_key, mapped in ZH_ACADEMIC_MAP.items():
        if zh_key in question:
            expanded_en.update(mapped)
    return en_terms | expanded_en, zh_terms, has_zh


def _llm_expand_keywords(question: str) -> set[str]:
    """Optional fast cross-lingual keyword expansion when an active credential is available."""
    import json
    import httpx
    from . import dpapi, reading
    from .llm_provider import strip_json_fence, trust_system_proxy
    cfg = reading.settings()
    endpoint = (cfg.get('endpoint') or '').strip()
    if not endpoint or any(h in endpoint for h in ('127.0.0.1:9999', 'localhost:9999', 'localhost/')):
        return set()
    key = dpapi.load_secret('workspace') or (__import__('os').getenv(cfg.get('key_env') or '', ''))
    if cfg.get('key_env') and not key:
        return set()
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    prompt = (
        'Extract 4 to 8 concise English academic search keywords/phrases for retrieving relevant '
        'paragraphs from an English research paper to answer the user question. '
        'Return strict JSON only: {"keywords":["term1","term2"]}.'
    )
    try:
        with httpx.Client(timeout=httpx.Timeout(4.0, connect=2.0), follow_redirects=False,
                          trust_env=trust_system_proxy(cfg)) as client:
            resp = client.post(endpoint, headers=headers, json={
                'model': cfg['model'],
                'messages': [{'role': 'system', 'content': prompt}, {'role': 'user', 'content': question[:500]}],
                'max_tokens': 120, 'temperature': 0.0, 'stream': False,
            })
            if resp.status_code != 200:
                return set()
            raw = resp.json()['choices'][0]['message']['content']
            kws = json.loads(strip_json_fence(raw)).get('keywords', [])
            out = set()
            for kw in kws[:10]:
                if isinstance(kw, str):
                    out.update(re.findall(r'[A-Za-z0-9_-]{2,}', kw.lower()))
            return out
    except Exception:
        return set()


def _fts5_bm25_scores(blocks: list[dict], titles: dict[str, str], query_terms: set[str]) -> dict[str, float]:
    import sqlite3
    safe_tokens = [re.sub(r'[^A-Za-z0-9_]', '', t) for t in query_terms]
    safe_tokens = [t for t in safe_tokens if len(t) >= 2][:24]
    if not safe_tokens or not blocks:
        return {}
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute("CREATE VIRTUAL TABLE docs USING fts5(bid UNINDEXED, sec, body, tokenize='porter unicode61')")
        conn.executemany(
            'INSERT INTO docs(bid, sec, body) VALUES (?, ?, ?)',
            [(b['id'], titles.get(b.get('section_id'), ''), b['text']) for b in blocks if b.get('regions') and b['text'].strip()],
        )
        fts_query = ' OR '.join(f'"{t}"' for t in dict.fromkeys(safe_tokens))
        rows = conn.execute('SELECT bid, bm25(docs, 0.0, 2.5, 1.0) FROM docs WHERE docs MATCH ? ORDER BY 2 LIMIT 24', (fts_query,)).fetchall()
        # sqlite bm25() returns negative values where more negative = stronger match
        return {bid: max(0.5, -float(score)) for bid, score in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


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
    en_terms, zh_terms, has_zh = _expand_cross_lingual_terms(question)
    titles = {s['id']: s['title'].lower() for s in doc['sections']}
    bm25 = _fts5_bm25_scores(doc['blocks'], titles, en_terms)
    if has_zh and len(bm25) < 3:
        extra_en = _llm_expand_keywords(question)
        if extra_en - en_terms:
            en_terms |= extra_en
            bm25 = _fts5_bm25_scores(doc['blocks'], titles, en_terms)
    terms = en_terms | zh_terms
    wants_formula = any(k in question for k in ('公式', '损失', '推导', 'equation', 'formula', 'loss'))
    wants_table = any(k in question for k in ('实验', '结果', '消融', '对比', '指标', '表格', 'table', 'ablation', 'result'))
    scored=[]
    for block in doc['blocks']:
        if not block.get('regions') or not block['text'].strip():
            continue
        lowered=block['text'].lower()
        hits=[term for term in terms if term in lowered]
        lex_score=sum(min(lowered.count(term),3) for term in hits)+sum(2 for t in terms if t in titles.get(block['section_id'],''))
        fts_score=bm25.get(block['id'], 0.0) * 2.5
        kind_bonus=(2.0 if wants_formula and block['type']=='formula' and (lex_score or fts_score) else 0.0) + (
                    2.0 if wants_table and block['type']=='table' and (lex_score or fts_score) else 0.0)
        total_score=lex_score + fts_score + kind_bonus
        if total_score > 0:
            first=min((lowered.find(t) for t in hits),default=0)
            scored.append((-total_score,block['reading_order'],block,max(0,first-350)))
    for _,_,block,start in sorted(scored,key=lambda x:(x[0],x[1]))[:10]:
        add(fragment(block,start,min(len(block['text']),start+1600),rid))
    return source,{'version':SOURCE_VERSION,'mode':'cross_lingual_fts5_hybrid','terms':sorted(terms),
                   'hits':len(source),'status':'matched' if source else 'no_hits',
                   'scope':'仅本次检索片段，不代表阅读全文'}
