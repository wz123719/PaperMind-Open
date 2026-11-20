"""Optional exact-version arXiv sources; immutable archive and fenced registration."""
import hashlib,json,os,time,uuid
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import httpx
from sqlalchemy import select
from .db import STORAGE,engine,paper_files,papers,jobs,write_tx,uid,emit
from .files import file_path,LeaseLost
from .tex_source import SourceFailure,unpack,parse_source,VERSION

def identity(fid):
    with engine.connect() as conn:
        row=conn.execute(select(paper_files,papers.c.arxiv_id).join(papers,paper_files.c.paper_id==papers.c.id)
                         .where(paper_files.c.id==fid)).mappings().first()
    if not row:raise LookupError('文件不存在')
    return dict(row)

def registration(fid):
    file=identity(fid)
    result={'status':'unavailable','reason':'no_exact_version_source','pdf_sha256':file['sha256'],
            'arxiv_id':file['arxiv_id'],'arxiv_version':file['arxiv_version'],'parser_version':VERSION}
    path=STORAGE/'source-archives'/file['sha256']/'registration.json'
    if not file['arxiv_id'] or not file['arxiv_version']:result['reason']='pdf_has_no_exact_arxiv_version';return result
    if not path.exists():return result
    data=json.loads(path.read_text(encoding='utf-8'))
    if any(data.get(k)!=result[k] for k in ['pdf_sha256','arxiv_id','arxiv_version']):
        result['reason']='source_identity_mismatch';return result
    archive=file_path(data['archive_path'])
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest()!=data['archive_sha256']:
        result['reason']='source_hash_mismatch';return result
    return data

def source_url(url,canonical):
    u=urlsplit(url)
    if u.scheme!='https' or u.hostname not in ('arxiv.org','export.arxiv.org') or u.port not in (None,443) or u.username or u.password or u.query or u.fragment:
        raise SourceFailure('源文件地址不属于允许的arXiv版本端点')
    if u.path not in ('/src/'+canonical,'/e-print/'+canonical):raise SourceFailure('源文件重定向论文或版本不匹配')
    return url

def acquire(fid,target,progress=lambda _:None,client=None):
    file=identity(fid)
    if not file['arxiv_id'] or not file['arxiv_version']:raise SourceFailure('当前PDF没有可靠的arXiv版本，不能绑定源文件')
    canonical=f"{file['arxiv_id']}v{file['arxiv_version']}";url='https://arxiv.org/src/'+canonical
    own=client is None;client=client or httpx.Client(timeout=httpx.Timeout(30,connect=10),trust_env=False,
        headers={'User-Agent':'PaperMindWorkspace/1.0 (exact-version source research)'})
    started=time.monotonic()
    try:
        for _ in range(5):
            source_url(url,canonical)
            with client.stream('GET',url,follow_redirects=False) as response:
                if response.status_code in (301,302,303,307,308):url=urljoin(url,response.headers.get('location',''));continue
                response.raise_for_status();total=0
                with Path(target).open('wb') as output:
                    for chunk in response.iter_bytes(65536):
                        total+=len(chunk)
                        if total>32*1024*1024 or time.monotonic()-started>180:raise SourceFailure('源文件获取预算超限')
                        output.write(chunk);progress(total)
                return {'pdf_sha256':file['sha256'],'arxiv_id':file['arxiv_id'],'arxiv_version':file['arxiv_version'],
                        'url':url,'retrieved_at':time.time(),'parser_version':VERSION,'status':'available'}
        raise SourceFailure('源文件重定向次数超限')
    finally:
        if own:client.close()

def register(fid,target,metadata,lease=None):
    import shutil
    file=identity(fid)
    if any(metadata.get(k)!=v for k,v in [('pdf_sha256',file['sha256']),('arxiv_id',file['arxiv_id']),('arxiv_version',file['arxiv_version'])]):
        raise SourceFailure('源文件与PDF身份或版本不匹配')
    source_url(metadata['url'],f"{file['arxiv_id']}v{file['arxiv_version']}")
    data=Path(target).read_bytes();digest=hashlib.sha256(data).hexdigest()
    work=STORAGE/'tmp'/('source-'+uuid.uuid4().hex)
    try:
        unpack(data,work);parsed=parse_source(work)
    finally:
        if work.exists():shutil.rmtree(work)
    rel=f"source-archives/{file['sha256']}/{digest}.bin";dest=file_path(rel);dest.parent.mkdir(parents=True,exist_ok=True)
    manifest={**metadata,'archive_sha256':digest,'archive_path':rel,'bytes':len(data),
              'main_file':parsed['main_file'],'included_files':parsed['included_files'],'objects':len(parsed['objects'])}
    with write_tx() as conn:
        if lease:
            from .queue import owned
            if not conn.execute(select(jobs.c.id).where(owned(lease[0],lease[1],time.time()))).first():raise LeaseLost('源文件任务租约失效')
        if not dest.exists():os.replace(target,dest)
        temp=dest.parent/(uuid.uuid4().hex+'.part')
        temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');os.replace(temp,dest.parent/'registration.json')
    return manifest

def enqueue(fid):
    identity(fid);now=time.time();jid=uid()
    with write_tx() as conn:
        old=conn.execute(select(jobs.c.id).where(jobs.c.type=='arxiv_source',jobs.c.status.in_(['queued','running']))).scalars().all()
        for candidate in old:
            payload=conn.execute(select(jobs.c.payload).where(jobs.c.id==candidate)).scalar()
            if payload.get('paper_file_id')==fid:return candidate
        conn.execute(jobs.insert().values(id=jid,type='arxiv_source',payload={'paper_file_id':fid},status='queued',
            attempts=0,max_attempts=3,available_at=now,created_at=now,updated_at=now))
        emit(conn,jid,'queued',{'message':'等待获取对应版本源文件'})
    return jid
