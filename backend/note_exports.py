"""Bounded synchronous, journaled manual exports with immutable files and conflict baselines."""
import hashlib,json,os,re,stat,tempfile,time,unicodedata
from pathlib import Path
from urllib.parse import quote
from sqlalchemy import select
from .db import engine,write_tx,uid,vault_settings,note_exports,paper_files,notes as notes_table
from . import notes,reading,parsing
from .files import file_path
from .note_markdown import export_markdown,safe_prose,EXPORT_VERSION

MAX_PACKAGE=100*1024*1024
RESERVED={'CON','PRN','AUX','NUL',*[f'{p}{i}' for p in ('COM','LPT') for i in range(1,10)]}
RESERVED.update(p+d for p in ('COM','LPT') for d in '¹²³')

def digest_bytes(data):return hashlib.sha256(data).hexdigest()

def components(relative):
    if not isinstance(relative,str) or not relative or len(relative)>180 or '\\' in relative:raise ValueError('输出子目录须使用安全相对路径与 / 分隔符')
    parts=relative.split('/')
    for p in parts:
        if (not p or p in ('.','..') or len(p)>120 or p[-1] in ' .' or
            any(ord(x)<32 or x in '<>:"|?*' for x in p) or p.split('.')[0].upper() in RESERVED):raise ValueError('输出路径含不安全或保留名称')
    return parts

def no_links(path):
    # Reject untrusted symlinks/junctions while permitting Windows Cloud Filter (OneDrive/iCloud) placeholders.
    path=Path(os.path.abspath(path))
    for p in [*reversed(path.parents),path]:
        try:info=p.lstat()
        except FileNotFoundError:continue
        reparse_tag=getattr(info,'st_reparse_tag',0)
        is_cloud=(reparse_tag & 0xFFFF0000)==0x90000000
        if stat.S_ISLNK(info.st_mode) or (not is_cloud and getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024)):
            raise ValueError('不支持符号链接、junction或reparse point路径')
    return path

def checked_root(root,subdir):
    if not isinstance(root,str) or not root or root.startswith(('\\\\','//','\\?\\','\\.\\')):raise ValueError('仅支持显式本地Vault目录')
    p=Path(root)
    if not p.is_absolute() or any(c in root for c in ('\x00',)) or ':' in str(p)[2:]:raise ValueError('Vault根目录无效')
    p=no_links(p)
    if not p.is_dir():raise ValueError('Vault根目录必须已存在且为目录')
    destination=p.joinpath(*components(subdir));no_links(destination)
    if not destination.is_relative_to(p):raise ValueError('输出目录越界')
    return p,destination

def settings():
    with engine.connect() as c:config=c.execute(select(vault_settings.c.config).where(vault_settings.c.id=='default')).scalar()
    return config or {'root':'','subdir':'PaperMind','revision':None,'configured':False}

def configure(root,subdir,expected):
    base,_=checked_root(root,subdir)
    with write_tx() as c:
        old=c.execute(select(vault_settings.c.config).where(vault_settings.c.id=='default')).scalar()
        if (old or {}).get('revision')!=expected:raise notes.Conflict('Vault设置已变化，请刷新')
        value={'root':str(base),'subdir':subdir,'revision':uid(),'configured':True}
        c.execute(vault_settings.delete().where(vault_settings.c.id=='default'))
        c.execute(vault_settings.insert().values(id='default',config=value))
    return value

def validate(root,subdir):
    base,dest=checked_root(root,subdir)
    # Only this explicit validation operation probes writes. Never remove existing user files.
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=base,prefix='.papermind-probe-',delete=False) as f:name=f.name;f.write(b'PaperMind write probe')
        return {'valid':True,'output':str(dest),'probe':'created and removed one generated temporary file'}
    except OSError as exc:raise ValueError('Vault目录不可写，请检查权限') from exc
    finally:
        if name:Path(name).unlink(missing_ok=True)

def owned_file(path):
    path=no_links(path)
    if not path.is_file():raise ValueError('所需源资源不存在')
    return path

def resources(rev, *, bundle_pdf=True):
    note=rev['note'];snap=rev['snapshot'];rid=note['parse_run_id']
    with engine.connect() as c:file=c.execute(select(paper_files).where(paper_files.c.id==note['paper_file_id'])).mappings().one()
    pdf=owned_file(file_path(file['relative_path']));pdf_hash=digest_bytes(pdf.read_bytes())
    if pdf_hash!=note['file_sha256']:raise ValueError('原PDF哈希发生变化')
    result=[{'source':str(pdf),'relative':f"_resources/{note['id']}/{pdf_hash}.pdf",'sha256':pdf_hash,'size':pdf.stat().st_size,'kind':'pdf'}] if bundle_pdf else []
    md=rev['markdown'];known={a['id']:a for a in notes.assets(note['id'])}
    used=set()
    def image(match):
        target=match[2]
        if not target.startswith('asset:') or target[6:] not in known:raise ValueError('图片必须使用当前笔记的受控 asset:ID；远程/任意路径或缺失图片不能发布')
        aid=target[6:];asset=known[aid]
        run=parsing.get_run(rid);root=file_path(run['artifact_root']);path=owned_file(root/asset['name'])
        if not path.is_relative_to(root):raise ValueError('解析资源越界')
        raw=path.read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('只支持已登记PNG图片')
        sha=digest_bytes(raw);relative=f"_resources/{note['id']}/{sha}.png"
        if aid not in used:result.append({'source':str(path),'relative':relative,'sha256':sha,'size':len(raw),'kind':'image'});used.add(aid)
        return '!['+match[1]+']('+quote(relative,safe='/')+')'
    md=export_markdown(md,image)
    if bundle_pdf:
        pdf_relative=quote(result[0]['relative'],safe='/')
        md+='\n### 离线PDF证据\n\n[绑定原始PDF]('+pdf_relative+')\n'
        for e in notes.evidence(snap):
            for page in sorted({r['page_index']+1 for r in e.get('regions',[])}):
                md+=f'\n- [原文第{page}页]({pdf_relative}#page={page})：'+safe_prose(e.get('quote','').replace('\n',' '))+'；状态 '+e['verification']+'\n'
        md+='\n> 以上PDF链接支持页码跳转，不声明Obsidian坐标高亮。\n'
    if len(result)>501 or sum(f['size'] for f in result)>MAX_PACKAGE:raise ValueError('同步发布上限100MiB/500张图片')
    return md,result

def target_path(config,relative,create=False):
    _,base=checked_root(config['root'],config['subdir']);components(relative)
    path=base.joinpath(*relative.split('/'));no_links(path)
    if create:
        # Existing nodes are checked both before and after directory creation.
        path.parent.mkdir(parents=True,exist_ok=True);no_links(path)
    return path

def disk_state(path):
    no_links(path)
    if not path.exists():return {'exists':False,'sha256':None,'text':None}
    if not path.is_file():raise ValueError('目标不是普通文件')
    if path.stat().st_size>2*1024*1024:raise ValueError('目标文件过大，保留外部文件并人工处理')
    raw=path.read_bytes()
    return {'exists':True,'sha256':digest_bytes(raw),'text':raw.decode('utf-8',errors='replace')}

def baseline(c,nid,config):
    rows=c.execute(select(note_exports).where(note_exports.c.note_id==nid,note_exports.c.status=='succeeded').order_by(note_exports.c.completed_at.desc())).mappings().all()
    return next((dict(r) for r in rows if r['plan']['config']['root']==config['root'] and r['plan']['config']['subdir']==config['subdir']),None)

def check_baseline(plan):
    previous=plan.get('baseline')
    if not previous:return
    actual=disk_state(target_path(plan['config'],previous['target']))
    if not actual['exists'] or actual['sha256']!=previous['sha256']:
        raise notes.Conflict('Vault上次发布文件已被外部修改或删除；保留外部文件，可手工合并后另存',vault=actual,
            local=plan['markdown'],previous=previous['markdown'],diff=notes.diff_text(actual['text'] or '',plan['markdown']))

def filename_key(name):
    return unicodedata.normalize('NFC', name).casefold()

def title_filename(title, edition=1, fork=False):
    clean=unicodedata.normalize('NFC', title or '')
    clean=''.join(' ' if ch in '<>:"/\\|?*' or unicodedata.category(ch).startswith('C') else ch for ch in clean)
    stem=' '.join(clean.split()).strip(' .') or '未命名论文'
    if stem.split('.')[0].rstrip().upper() in RESERVED:stem='论文 '+stem
    suffix=('（副本）' if edition==1 else f'（副本 {edition}）') if fork else (f'（{edition}）' if edition>1 else '')
    limit=120-len((suffix+'.md').encode('utf-16-le'))//2
    stem=stem.encode('utf-16-le')[:limit*2].decode('utf-16-le',errors='ignore').rstrip(' .')
    return (stem or '未命名论文')+suffix+'.md'

def choose_target(c,config,title,fork):
    _,base=checked_root(config['root'],config['subdir'])
    reserved={filename_key(p.name) for p in base.iterdir()} if base.exists() else set()
    plan=note_exports.c.plan
    for root,subdir,target in c.execute(select(plan['config']['root'].as_string(),plan['config']['subdir'].as_string(),
                                                plan['target'].as_string())):
        if root and subdir and target and os.path.normcase(os.path.join(root,subdir))==os.path.normcase(str(base)):
            reserved.add(filename_key(target))
    for edition in range(1,len(reserved)+2):
        target=title_filename(title,edition,fork)
        if filename_key(target) not in reserved:
            return target
    raise ValueError('未能分配可用的论文笔记文件名')

def preview(nid,rid,content_hash,key,fork=False):
    if not isinstance(key,str) or not 8<=len(key)<=100:raise ValueError('发布操作键须为8至100字符')
    rev=notes.revision(nid,rid)
    if rev['note']['current_revision']!=rid or rev['content_hash']!=content_hash or not rev['reviewed']:raise notes.Conflict('仅可预览当前精确审核版本')
    config=settings()
    if not config['configured']:raise ValueError('请先显式配置测试或正式Vault')
    checked_root(config['root'],config['subdir']);md,files=resources(rev);eid=uid()
    fingerprint=reading.digest({'note':nid,'revision':rid,'hash':content_hash,'config':config,'fork':fork,'render_version':EXPORT_VERSION})
    with write_tx() as c:
        old=c.execute(select(note_exports).where(note_exports.c.request_key==key)).mappings().first()
        if old:
            if old['plan'].get('render_version')!=EXPORT_VERSION:raise ValueError('旧导出操作键不能静默升级，请使用新键重新预览')
            if old['plan']['request_hash']!=fingerprint:raise ValueError('发布操作键已用于其他请求')
            return public(dict(old))
        if c.execute(select(notes_table.c.current_revision).where(notes_table.c.id==nid)).scalar()!=rid:raise notes.Conflict('笔记已变化')
        prior=baseline(c,nid,config)
        base=None if fork or not prior else {'target':prior['plan']['target'],'sha256':prior['plan']['markdown_hash'],'markdown':prior['plan']['markdown']}
        target=choose_target(c,config,rev['snapshot']['metadata'].get('title'),fork)
        plan={'request_hash':fingerprint,'render_version':EXPORT_VERSION,'config':config,'revision_hash':content_hash,'markdown':md,'markdown_hash':digest_bytes(md.encode()),
            'files':files,'target':target,'baseline':base,'fork':fork,'warnings':[notes.CAUTION,'人工审核只表示接受本笔记版本；旧来源状态不升级。',
                '每个revision发布独立文件；不会原地覆盖旧Markdown。跨进程目录替换竞态仍需避免。']}
        check_baseline(plan)
        actual=disk_state(target_path(config,target))
        if actual['exists']:raise notes.Conflict('同名文件已存在，不能认领或覆盖',vault=actual,local=md,diff=notes.diff_text(actual['text'] or '',md))
        c.execute(note_exports.insert().values(id=eid,note_id=nid,revision_id=rid,request_key=key,plan=plan,status='preview',created_at=time.time()))
    return get(eid)

def public(row):return {**row,'plan':{**row['plan'],'files':[{k:v for k,v in f.items() if k!='source'} for f in row['plan']['files']]}}
def listing(nid):
    notes.get(nid)
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(note_exports.c.id,note_exports.c.revision_id,note_exports.c.status,note_exports.c.created_at)
            .where(note_exports.c.note_id==nid).order_by(note_exports.c.created_at.desc()).limit(100)).mappings()]
def get(eid):
    with engine.connect() as c:row=c.execute(select(note_exports).where(note_exports.c.id==eid)).mappings().first()
    if not row:raise LookupError('发布记录不存在')
    return public(dict(row))

def durable_new(path,data):
    """Same-volume fsync then no-clobber hard-link publication. Never replaces a user file."""
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.papermind-tmp-',delete=False) as f:
            temporary=Path(f.name);f.write(data);f.flush();os.fsync(f.fileno())
        no_links(path);os.link(temporary,path)
    finally:
        if temporary:temporary.unlink(missing_ok=True)

def fault(stage):pass  # test-only injection hook, not exposed to HTTP

def commit(eid):
    # Durable preparation journal is committed before filesystem mutation.
    with write_tx() as c:
        row=c.execute(select(note_exports).where(note_exports.c.id==eid)).mappings().first()
        if not row:raise LookupError('发布记录不存在')
        if row['status']=='succeeded':return public(dict(row))
        if row['plan'].get('render_version')!=EXPORT_VERSION:
            raise notes.Conflict('旧导出计划未按区域保真规则生成，请使用新操作键重新预览；保留旧文件，必要时另存')
        first_attempt=row['status']=='preview'
        if first_attempt and disk_state(target_path(row['plan']['config'],row['plan']['target']))['exists']:
            raise notes.Conflict('预览后出现同名文件，保留外部文件，请另存')
        c.execute(note_exports.update().where(note_exports.c.id==eid).values(status='preparing',error=None))
    try:
        # BEGIN IMMEDIATE is the cross-process application publishing mutex.
        with write_tx() as c:
            row=dict(c.execute(select(note_exports).where(note_exports.c.id==eid)).mappings().one())
            if row['status']=='succeeded':return public(row)
            plan=row['plan'];rev=notes.revision(row['note_id'],row['revision_id'])
            if settings()!=plan['config'] or rev['note']['current_revision']!=rev['id'] or not rev['reviewed'] or rev['content_hash']!=plan['revision_hash']:
                raise notes.Conflict('审核版本或Vault配置已变化，请重新预览')
            check_baseline(plan)
            for resource in plan['files']:
                source=owned_file(resource['source']);data=source.read_bytes()
                if digest_bytes(data)!=resource['sha256']:raise ValueError('源资源哈希变化')
                target=target_path(plan['config'],resource['relative'],True)
                if target.exists():
                    if not target.is_file() or digest_bytes(target.read_bytes())!=resource['sha256']:raise notes.Conflict('受管资源被修改，保留磁盘文件')
                else:durable_new(target,data)
                fault('resource')
            # Check external baseline again immediately before publishing the Markdown.
            check_baseline(plan);target=target_path(plan['config'],plan['target'],True);state=disk_state(target)
            if state['exists']:
                # Only a journaled, already-started attempt may resume its exact immutable bytes.
                if first_attempt or state['sha256']!=plan['markdown_hash']:raise notes.Conflict('目标已出现外部文件，不能覆盖',vault=state,local=plan['markdown'])
            else:durable_new(target,plan['markdown'].encode('utf-8'))
            fault('markdown')
            if digest_bytes(target.read_bytes())!=plan['markdown_hash']:raise ValueError('发布后校验失败')
            c.execute(note_exports.update().where(note_exports.c.id==eid).values(status='succeeded',error=None,completed_at=time.time()))
            fault('database_commit')
    except Exception as exc:
        with write_tx() as c:c.execute(note_exports.update().where(note_exports.c.id==eid).values(status='failed',error=str(exc)))
        raise
    return get(eid)


def durable_replace(path, data):
    """Atomic fsync + same-volume replace for updating an existing managed note in place."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.papermind-upd-', delete=False) as f:
            temporary = Path(f.name)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        no_links(path)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def sync_same_title(nid: str, *, bundle_pdf: bool = False, force_overwrite: bool = False):
    """One-click Obsidian sync using exact paper title (<论文标题>.md) without serial number suffixes."""
    rev = notes.revision(nid)
    if not rev['reviewed']:
        rev = notes.review(nid, rev['id'], rev['content_hash'])
    config = settings()
    if not config['configured']:
        raise ValueError('请先在笔记面板的 Vault 设置中填写本地 Obsidian 库目录')
    checked_root(config['root'], config['subdir'])
    md, files = resources(rev, bundle_pdf=bundle_pdf)
    # Normalize any remaining \(...\) and \[...\] outside code blocks for Obsidian MathJax
    md = re.sub(r'\\\[([\s\S]*?)\\\]', lambda m: f'$$\n{m.group(1).strip()}\n$$', md)
    md = re.sub(r'\\\(([^\n]*?)\\\)', lambda m: f'${m.group(1).strip()}$', md)
    target_name = title_filename(rev['snapshot']['metadata'].get('title'), edition=1, fork=False)
    md_bytes = md.encode('utf-8')
    md_hash = digest_bytes(md_bytes)
    eid = uid()
    with write_tx() as c:
        prior = baseline(c, nid, config)
        target_file = target_path(config, target_name, create=True)
        actual = disk_state(target_file)
        if actual['exists'] and not force_overwrite:
            managed_same_file = prior and filename_key(prior['plan']['target']) == filename_key(target_name)
            if not managed_same_file or actual['sha256'] not in (prior['plan']['markdown_hash'], md_hash):
                raise notes.Conflict(
                    f'Obsidian 中已存在同名笔记「{target_name}」且包含外部修改；如确认覆盖更新可点击「覆盖同名文件」',
                    target=target_name, vault=actual, local=md,
                    diff=notes.diff_text(actual['text'] or '', md),
                )
        for resource in files:
            src = owned_file(resource['source'])
            rdata = src.read_bytes()
            if digest_bytes(rdata) != resource['sha256']:
                raise ValueError('源资源哈希变化')
            rtarget = target_path(config, resource['relative'], create=True)
            if not rtarget.exists():
                durable_new(rtarget, rdata)
        durable_replace(target_file, md_bytes)
        plan = {
            'request_hash': reading.digest({'sync': nid, 'rev': rev['id'], 'bundle_pdf': bundle_pdf, 'target': target_name}),
            'render_version': EXPORT_VERSION,
            'config': config,
            'revision_hash': rev['content_hash'],
            'markdown': md,
            'markdown_hash': md_hash,
            'files': files,
            'target': target_name,
            'baseline': {'target': target_name, 'sha256': md_hash, 'markdown': md},
            'fork': False,
            'same_title_sync': True,
            'bundle_pdf': bundle_pdf,
            'warnings': [],
        }
        now = time.time()
        c.execute(note_exports.insert().values(
            id=eid, note_id=nid, revision_id=rev['id'],
            request_key='sync:' + eid, plan=plan,
            status='succeeded', error=None, created_at=now, completed_at=now,
        ))
    return {**get(eid), 'full_path': str(target_path(config, target_name))}
