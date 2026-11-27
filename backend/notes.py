"""Immutable structured notes. No model calls and no implicit export side effects."""
import copy,difflib,re,time
import yaml
from sqlalchemy import select
from .db import (engine,write_tx,uid,notes,note_revisions,note_operations,note_reviews,papers,paper_files,chat_messages)
from . import reading,parsing,chat
from . import paper_note_template as paper_template

TITLES=['基本信息','一句话与贡献','背景与问题','相关工作','框架与流程','模块与公式','实验','优势局限与条件','实现复现','已有知识联系','个人疑问','证据与参考链接']
SECTIONS=[{'id':f's{i+1:02d}','title':title} for i,title in enumerate(TITLES)]
CAUTION='解析质量尚未整体通过；分章导览不等于跨章节综合；引文匹配不等于论断成立。'
class NoteDumper(yaml.SafeDumper):pass
NoteDumper.add_representer(str,lambda dumper,value:dumper.represent_scalar('tag:yaml.org,2002:str',value,style='"' if '\n' in value or '\r' in value else None))

class Conflict(ValueError):
    def __init__(self,message,**detail):self.detail={'message':message,**detail};super().__init__(message)

def get(nid):
    with engine.connect() as c:row=c.execute(select(notes).where(notes.c.id==nid)).mappings().first()
    if not row:raise LookupError('笔记不存在')
    return dict(row)

def revision(nid,rid=None):
    note=get(nid);rid=rid or note['current_revision']
    with engine.connect() as c:
        row=c.execute(select(note_revisions).where(note_revisions.c.id==rid,note_revisions.c.note_id==nid)).mappings().first()
        reviewed=c.execute(select(note_reviews.c.content_hash).where(note_reviews.c.revision_id==rid)).scalar()
    if not row:raise LookupError('笔记版本不存在')
    result=dict(row);result['reviewed']=reviewed==row['content_hash'];result['note']=note
    result['markdown']=markdown(result)
    return result

def listing(paper_id=None):
    with engine.connect() as c:
        query = select(
            notes,
            note_revisions.c.snapshot['metadata']['title'].as_string().label('title'),
        ).join(note_revisions, note_revisions.c.id == notes.c.current_revision).order_by(notes.c.created_at.desc())
        if paper_id:
            query = query.where(notes.c.paper_id == paper_id)
        return [dict(r) for r in c.execute(query).mappings()]

def versions(nid):
    get(nid)
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(note_revisions.c.id,note_revisions.c.parent_id,note_revisions.c.content_hash,
            note_revisions.c.operation,note_revisions.c.created_at).where(note_revisions.c.note_id==nid).order_by(note_revisions.c.created_at.desc())).mappings()]

def file_identity(fid,parse_id=None):
    with engine.connect() as c:
        file=c.execute(select(paper_files).where(paper_files.c.id==fid)).mappings().first()
        paper=c.execute(select(papers).where(papers.c.id==file['paper_id'])).mappings().one() if file else None
    if not file:raise LookupError('PDF不存在')
    if parse_id:
        doc=parsing.structure(parse_id)
        if doc['run']['paper_file_id']!=fid or doc['run']['file_sha256']!=file['sha256']:raise ValueError('文件与解析版本不符')
    return dict(file),dict(paper)

def paper_note_sections(report, metadata):
    run = report['run']
    claims = {c['id']: c for s in report['sections'] for c in s['claims']}
    sections = []
    for part in paper_template.render(report, metadata):
        ids = part.pop('claim_ids')
        origins = [{'kind':'reading', 'reading_run_id':run['id'], 'parse_run_id':run['parse_run_id'],
                    'source_version':report['evidence_contract'], 'report':{'sections':[{'claims':[claims[i] for i in ids]}]}}] if ids else []
        sections.append({**part, 'origins':origins, 'manual':False})
    return sections

def reading_content(nid,run_id, snapshot=None):
    note=get(nid);report=reading.report(run_id);run=report['run']
    if run['parse_run_id']!=note['parse_run_id']:raise ValueError('精读与笔记固定解析版本不符')
    if snapshot and snapshot.get('template') == paper_template.VERSION:
        from .knowledge_reading import VERSION
        if report.get('pipeline_version') != VERSION:
            raise ValueError('论文知识笔记只能重新导入综合精读')
        sections = paper_note_sections(report, snapshot['metadata'])
        # Leave the manually maintained links and stable paper metadata alone.
        selected = [s for s in sections if s['id'] not in ('s01', 's13')]
        return {s['id']:s['markdown'] for s in selected}, {s['id']:s['origins'] for s in selected}
    body=[]
    for section in report['sections']:
        body+=['### '+section['title'],'导览（未核验）：'+section['summary']]
        for claim in section['claims']:
            body+=['- '+claim['text']+' ['+claim['verification']+']']
    origin={'kind':'reading','reading_run_id':run_id,'parse_run_id':run['parse_run_id'],
        'source_version':report['evidence_contract'],'report':report}
    from .knowledge_reading import MarkdownRenderer, VERSION
    if report.get('pipeline_version') == VERSION:
        claims = {c['id']: c for section in report['sections'] for c in section['claims']}
        overview_ids = (report.get('synthesis') or {}).get('overview', [])
        return {'s02': '\n'.join('- ' + claims[i]['text'] + ('（推断）' if claims[i]['kind'] == 'inference' else '')
                                 for i in overview_ids) or '综合结论暂未完成。',
                's05': MarkdownRenderer().render(report)}, {'s02':[origin], 's05':[origin]}
    # Explicit placement only; never invent a cross-section synthesis from section summaries.
    return {'s02':'待补充：当前只有分章导览，尚未完成跨章节综合。','s05':'\n\n'.join(body)},{'s02':[origin], 's05':[origin]}

def create(fid,parse_id=None,reading_id=None,title=None,key=None):
    file,paper=file_identity(fid,parse_id);nid=uid();rid=uid();now=time.time()
    if title is not None and (not isinstance(title,str) or len(title)>1000):raise ValueError('标题过长')
    snap={'metadata':{'title':title if title is not None else paper['title'],'authors':paper['authors'],'year':paper['year'],
        'source':file['source'],'arxiv_id':paper['arxiv_id'],'doi':paper['doi'],'tags':[]},
        'identity':{'paper_id':paper['id'],'paper_file_id':fid,'file_sha256':file['sha256'],'file_version':file['version'],'parse_run_id':parse_id},
        'sections':[{**s,'markdown':'','origins':[],'manual':False} for s in SECTIONS],'warnings':[CAUTION]}
    # Initial creation is itself idempotent; key is scoped to immutable request identity.
    if not isinstance(key,str) or not 8<=len(key)<=100:raise ValueError('创建笔记须提供8至100字符操作键')
    request=reading.digest({'file':fid,'parse':parse_id,'reading':reading_id,'title':title})
    # Use a dedicated operation namespace without claiming a note before it exists.
    with write_tx() as c:
        existing=c.execute(select(note_operations).where(note_operations.c.key=='create:'+key)).mappings().first()
        if existing:
            if existing['request_hash']!=request:raise ValueError('操作键已用于其他创建请求')
            previous=existing['note_id']
        else:
            previous=None
            if reading_id:
                report=reading.report(reading_id)
                if report['run']['parse_run_id']!=parse_id:raise ValueError('精读与解析版本不符')
                from .knowledge_reading import VERSION
                if report.get('pipeline_version') == VERSION:
                    snap.update(template=paper_template.VERSION, sections=paper_note_sections(report, snap['metadata']),
                                warnings=report['warnings'])
                else:
                    body=[]
                    for s in report['sections']:
                        body+=['### '+s['title'],'导览（未核验）：'+s['summary']]
                        body+=['- '+claim['text']+' ['+claim['verification']+']' for claim in s['claims']]
                    snap['sections'][1]['markdown']='待补充：当前只有分章导览，尚未完成跨章节综合。'
                    snap['sections'][4].update(markdown='\n\n'.join(body),origins=[{'kind':'reading','reading_run_id':reading_id,
                        'parse_run_id':parse_id,'source_version':report['evidence_contract'],'report':report}])
            c.execute(notes.insert().values(id=nid,paper_id=paper['id'],paper_file_id=fid,file_sha256=file['sha256'],parse_run_id=parse_id,current_revision=rid,created_at=now))
            c.execute(note_revisions.insert().values(id=rid,note_id=nid,parent_id=None,snapshot=snap,content_hash=reading.digest(snap),operation='create',created_at=now))
            c.execute(note_operations.insert().values(note_id=nid,key='create:'+key,request_hash=request,revision_id=rid))
    return revision(previous or nid)

def mutate(nid,expected,key,operation,payload,transform):
    if not isinstance(key,str) or not 8<=len(key)<=100:raise ValueError('操作键须为8至100字符')
    fingerprint=reading.digest({'expected':expected,'operation':operation,'payload':payload})
    current=revision(nid);rid=uid();now=time.time()
    with write_tx() as c:
        repeated=c.execute(select(note_operations).where(note_operations.c.note_id==nid,note_operations.c.key==key)).mappings().first()
        if repeated:
            if repeated['request_hash']!=fingerprint:raise ValueError('操作键已用于其他内容；主动再次插入请使用新键')
            rid=repeated['revision_id']
        else:
            head=c.execute(select(notes.c.current_revision).where(notes.c.id==nid)).scalar()
            if head!=expected or current['id']!=expected:
                latest=revision(nid)['snapshot']
                local=payload.get('markdown','') if isinstance(payload,dict) else ''
                remote=next((s['markdown'] for s in latest['sections'] if s['id']==payload.get('section_id')), '')
                raise Conflict('笔记已在其他窗口保存，未覆盖你的编辑',current_revision=head,expected_revision=expected,
                    submitted=payload,current=latest,local=local,remote=remote,diff=diff_text(remote,local))
            snap=copy.deepcopy(current['snapshot']);transform(snap)
            if sum(len(s['markdown']) for s in snap['sections'])>500000:raise ValueError('单笔记最多500000字符')
            c.execute(note_revisions.insert().values(id=rid,note_id=nid,parent_id=head,snapshot=snap,content_hash=reading.digest(snap),operation=operation,created_at=now))
            c.execute(notes.update().where(notes.c.id==nid).values(current_revision=rid))
            c.execute(note_operations.insert().values(note_id=nid,key=key,request_hash=fingerprint,revision_id=rid))
    return revision(nid,rid)

def section(snap,sid):
    found=next((s for s in snap['sections'] if s['id']==sid),None)
    if not found:raise ValueError('章节ID无效')
    return found

def edit(nid,expected,key,sid,text):
    if not isinstance(text,str) or len(text)>500000:raise ValueError('章节文字无效或过长')
    def change(snap):section(snap,sid).update(markdown=text,manual=True)
    return mutate(nid,expected,key,'manual_edit',{'section_id':sid,'markdown':text},change)

def suggestions(nid,reading_id):
    base=revision(nid);proposed,_=reading_content(nid,reading_id,base['snapshot'])
    return {'expected_revision':base['id'],'reading_run_id':reading_id,'changes':[{'section_id':sid,'current':section(base['snapshot'],sid)['markdown'],
        'proposed':text,'diff':diff_text(section(base['snapshot'],sid)['markdown'],text)} for sid,text in proposed.items()],
        'warning':'建议不会自动保存；只应用所选章节，可能替换该章节手写内容。'}

def apply_reading(nid,expected,key,reading_id,section_ids):
    proposed,origins=reading_content(nid,reading_id,revision(nid)['snapshot'])
    if not section_ids or len(set(section_ids))!=len(section_ids) or any(s not in proposed for s in section_ids):raise ValueError('请选择有效建议章节')
    def change(snap):
        for sid in section_ids:section(snap,sid).update(markdown=proposed[sid],origins=origins[sid],manual=False)
    return mutate(nid,expected,key,'apply_selected_reading',{'reading_run_id':reading_id,'sections':section_ids},change)

def answer_preview(nid,message_id):
    note=get(nid)
    with engine.connect() as c:row=c.execute(select(chat_messages).where(chat_messages.c.id==message_id)).mappings().first()
    if not row:raise LookupError('回答不存在')
    row=dict(row)
    if row['role']!='assistant' or row['status']!='completed':raise ValueError('只有完整成功回答可以保存')
    turn=chat.turn(row['turn_id']);identity=turn['snapshot']['identity']
    for k in ('paper_id','paper_file_id','file_sha256','parse_run_id'):
        if identity.get(k)!=note[k]:raise ValueError('回答与笔记论文/文件/解析版本不符')
    version=turn['snapshot'].get('source_version','chat-source-1')
    from .chat_sources import SOURCE_VERSION
    warning='旧版未按现行符号规则复核' if version!=SOURCE_VERSION else '引文匹配不等于论断正确，待人工审核'
    text='### 保存的完整回答\n\n'+row['content']+'\n\n> 来源版本：'+version+'；'+warning
    return {'markdown':text,'origin':{'kind':'chat','message_id':message_id,'turn_id':turn['id'],'identity':identity,
        'source_version':version,'message':row,'snapshot':turn['snapshot']},'warning':warning}

def save_answer(nid,expected,key,sid,message_id,mode='append'):
    if mode not in ('append','replace'):raise ValueError('追加/替换方式无效')
    answer=answer_preview(nid,message_id)
    def change(snap):
        target=section(snap,sid)
        target['markdown']=(target['markdown']+'\n\n' if mode=='append' and target['markdown'] else '')+answer['markdown']
        target['origins']=(target['origins'] if mode=='append' else [])+[answer['origin']]
    return mutate(nid,expected,key,'save_complete_answer',{'message_id':message_id,'section_id':sid,'mode':mode},change)

def restore(nid,expected,key,old):
    saved=revision(nid,old)['snapshot']
    def change(snap):snap.clear();snap.update(copy.deepcopy(saved))
    return mutate(nid,expected,key,'restore',{'from_revision':old},change)

def review(nid,rid,content_hash):
    current=revision(nid,rid)
    with write_tx() as c:
        if c.execute(select(notes.c.current_revision).where(notes.c.id==nid)).scalar()!=rid or current['content_hash']!=content_hash:
            raise Conflict('当前版本已变化，请重新预览并审核')
        if not c.execute(select(note_reviews.c.revision_id).where(note_reviews.c.revision_id==rid)).scalar():
            c.execute(note_reviews.insert().values(revision_id=rid,content_hash=content_hash,reviewed_at=time.time()))
    return revision(nid,rid)

def diff_text(a,b):return '\n'.join(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile='current',tofile='proposed',lineterm=''))
def difference(nid,a,b):return {'diff':diff_text(revision(nid,a)['markdown'],revision(nid,b)['markdown'])}

def evidence(snap):
    result=[]
    for s in snap['sections']:
        for origin in s['origins']:
            if origin['kind']=='highlight':
                result.append({'section_id':s['id'],'manual':s['manual'],'source_version':origin.get('source_version','pdf-highlight-v1'),
                    'claim':origin.get('note') or '原文高亮摘录','verification':'unreviewed','matched':True,
                    'quote':origin.get('quote',''),'regions':origin.get('regions',[])})
                continue
            if origin['kind']=='chat':claims=origin['message']['data'].get('claims',[])
            else:claims=[c for stage in origin['report']['sections'] for c in stage['claims']]
            for claim in claims:
                for item in claim.get('evidence',[]):
                    result.append({'section_id':s['id'],'manual':s['manual'],'source_version':origin['source_version'],
                        'claim':claim['text'],'verification':claim['verification'],**item})
    return result

def markdown(rev):
    snap=rev['snapshot']
    if snap.get('template') == paper_template.VERSION:
        body = []
        for s in snap['sections']:
            heading = '' if s['id'] == 's00' else '## '+s['title']+'\n\n'
            body.append(heading+(s['markdown'] or '_待补充_'))
            if s['manual'] and s['origins']:
                body.append('> 手动修改：旧引文不自动支持新文字。')
        quotes = {}
        for e in evidence(snap):
            if e.get('matched'):
                pages = sorted({r['page_index']+1 for r in e.get('regions',[])})
                quotes.setdefault((tuple(pages), e['quote']), e)
        if quotes:
            body.extend(['### 原文摘录（引文匹配不等于论断已核实）', '\n'.join(
                '- 第 '+ '、'.join(map(str,pages))+' 页：'+paper_template.prose(quote)
                for pages,quote in quotes)])
        return '\n\n'.join(body)+'\n'
    meta={**snap['metadata'],'id':rev['note_id'],'type':'paper-note','status':'human-reviewed' if rev['reviewed'] else 'needs-review',
        **snap['identity'],'revision':rev['id'],'parent_revision':rev['parent_id'],'content_hash':rev['content_hash'],
        'created_at':rev['note']['created_at'],'updated_at':rev['created_at'],
        'reading_run_ids':sorted({o['reading_run_id'] for s in snap['sections'] for o in s['origins'] if o['kind']=='reading'})}
    body='---\n'+yaml.dump(meta,Dumper=NoteDumper,allow_unicode=True,sort_keys=False,width=120)+'---\n\n> '+CAUTION+'\n'
    for s in snap['sections']:
        body+='\n## '+s['title']+'\n\n'+(s['markdown'] or '_待补充_')+'\n'
        if s['origins']:body+='\n> '+('手动修改：保留历史来源追溯，旧引文不自动支持新文字。' if s['manual'] else '导入来源保持原校验状态，待人工审核。')+'\n'
    body+='\n### 原文追溯（人工审核不改变原始证据状态）\n'
    for e in evidence(snap):
        pages=sorted({r['page_index']+1 for r in e.get('regions',[])})
        body+='\n- '+e['verification']+'；'+e['source_version']+'；页码 '+(','.join(map(str,pages)) or '未知')+'；'+e.get('quote','').replace('\n',' ')+'\n'
    return body

def assets(nid):
    note=get(nid)
    if not note['parse_run_id']:return []
    doc=parsing.structure(note['parse_run_id'])
    return [{'id':reading.digest({'parse':note['parse_run_id'],'name':name})[:32],'name':name,
        'url':'/api/v1/parse-runs/'+note['parse_run_id']+'/assets/'+name}
        for name in sorted({a for b in doc['blocks'] for a in b['data'].get('assets',[])})]
