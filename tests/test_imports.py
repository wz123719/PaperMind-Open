from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import httpx
import pytest
from sqlalchemy import select, func
from backend import arxiv, queue
from backend.db import engine, papers, paper_files, STORAGE
from backend.files import file_path, save_pdf
from backend.worker import execute
from conftest import pdf_bytes

def upload(client, data, name='paper.pdf'):
    return client.post('/papers', files={'file': (name, data, 'application/pdf')})

def test_upload_duplicate_real_file_and_version(client):
    a = upload(client, pdf_bytes(doi='10.1234/test'), '../../outside.pdf')
    assert a.status_code == 201
    body = a.json()
    assert body['paper']['title'] == 'Research fixture'
    content = client.get('/files/' + body['file_id'] + '/content')
    assert content.content == pdf_bytes(doi='10.1234/test')
    assert content.headers['content-type'] == 'application/pdf'
    b = upload(client, pdf_bytes(doi='10.1234/test')).json()
    assert b['duplicate'] and b['file_id'] == body['file_id']
    c = upload(client, pdf_bytes(title='Revised', doi='10.1234/test')).json()
    assert not c['duplicate'] and c['paper_id'] == body['paper_id']
    assert [f['version'] for f in c['paper']['files']] == [2, 1]
    assert len(client.get('/papers').json()) == 1
    # Same title without identifiers is not merged.
    upload(client, pdf_bytes(title='Revised'))
    assert len(client.get('/papers').json()) == 2

def test_invalid_limit_and_tmp_cleanup(client):
    for data in [b'not pdf', b'%PDF-1.7\nnot a real document', b'']:
        assert upload(client, data).status_code == 422
    assert upload(client, b'%PDF-' + b'x' * 65536).status_code == 413
    assert client.post('/papers', content=b'x', headers={'content-length': '9999999'}).status_code == 413
    assert not list((STORAGE/'tmp').glob('*.part'))
    assert client.get('/papers').json() == []

def test_chunked_request_limit_without_content_length(client):
    boundary='test-boundary'
    def chunks():
        yield f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="large.pdf"\r\nContent-Type: application/pdf\r\n\r\n'.encode()
        for _ in range(20): yield b'x'*65536
        yield f'\r\n--{boundary}--\r\n'.encode()
    r=client.post('/papers',content=chunks(),headers={'content-type':f'multipart/form-data; boundary={boundary}'})
    assert r.status_code==413

def test_concurrent_dedup():
    data = pdf_bytes(doi='10.5555/concurrency')
    def save(n):
        p = STORAGE / f'concurrent-{n}.part'
        p.write_bytes(data)
        try: return save_pdf(p, 'upload')
        finally: p.unlink(missing_ok=True)
    with ThreadPoolExecutor(4) as pool:
        rows = list(pool.map(save, range(8)))
    assert sum(not r['duplicate'] for r in rows) == 1
    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(paper_files)) == 1

@pytest.mark.parametrize('value,base,version', [
    ('2301.12345', '2301.12345', None), ('2301.12345v2', '2301.12345', 2),
    ('https://arxiv.org/abs/1706.03762v7', '1706.03762', 7),
    ('https://arxiv.org/pdf/hep-th/9901001v3.pdf', 'hep-th/9901001', 3),
    ('math.GT/0309136','math.GT/0309136',None), ('0704.0001', '0704.0001', None)])
def test_normalize(value, base, version):
    assert arxiv.normalize(value)['arxiv_id'] == base
    assert arxiv.normalize(value)['arxiv_version'] == version

@pytest.mark.parametrize('value', ['http://arxiv.org/abs/2301.12345','https://evil.test/abs/2301.12345',
    'https://arxiv.org.evil.test/pdf/2301.12345','https://arxiv.org:8000/pdf/2301.12345',
    'https://x@arxiv.org/pdf/2301.12345', 'https://arxiv.org/pdf/../../foo', '2313.12345',
    '2301.12345v0','https://arxiv.org/abs/2301.12345?url=http://127.0.0.1', 'bad'])
def test_invalid_url(value):
    with pytest.raises(ValueError): arxiv.normalize(value)

def transport_for_pdf(data):
    def respond(request):
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2301.12345v2</id><title>Controlled transport fixture</title><published>2023-01-01T00:00:00Z</published><author><name>Fixture Author</name></author></entry></feed>''')
        return httpx.Response(200, content=data)
    return httpx.MockTransport(respond)

def test_controlled_download_and_idempotent_worker(client):
    data = pdf_bytes(arxiv='2301.12345v2')
    def downloader(payload, path, progress):
        with httpx.Client(transport=transport_for_pdf(data)) as c:
            return arxiv.download(payload,path,progress,c)
    jid = client.post('/papers/imports',json={'input':'2301.12345v2'}).json()['job_id']
    execute(queue.claim('test-worker'), 'test-worker', downloader)
    assert queue.get_job(jid)['status'] == 'succeeded'
    r = queue.get_job(jid)['result']
    assert client.get('/papers/'+r['paper_id']).json()['files'][0]['arxiv_version'] == 2
    # Repeat the entire job: side effect remains one stored file/version.
    second = queue.enqueue(arxiv.normalize('2301.12345v2'))
    execute(queue.claim('other-worker'), 'other-worker', downloader)
    assert queue.get_job(second)['result']['duplicate']
    assert len(client.get('/papers').json()[0]['files']) == 1

def test_redirect_and_stream_size():
    seen=[]
    def redirect(request):
        seen.append(str(request.url))
        return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
    with httpx.Client(transport=httpx.MockTransport(redirect)) as c:
        with pytest.raises(arxiv.ImportFailure): arxiv.fetch(c,'https://arxiv.org/pdf/2301.12345',100)
    assert len(seen) == 1
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200,content=b'x'*101))) as c:
        with pytest.raises(arxiv.ImportFailure): arxiv.fetch(c,'https://arxiv.org/pdf/2301.12345',100)

def test_path_host_origin_security(client):
    with pytest.raises(ValueError): file_path('../secret')
    with pytest.raises(ValueError): file_path('C:/Windows/system.ini')
    assert client.get('/files/unknown/content').status_code == 404
    assert client.get('/papers', headers={'host':'evil.test'}).status_code == 400
    assert client.post('/papers/imports',json={'input':'2301.12345'},headers={'origin':'https://evil.test'}).status_code == 403
    assert client.post('/papers/imports',json={'input':'2301.12345'},headers={'x-papermind-client':''}).status_code == 403
    r=client.options('/papers',headers={'Origin':'https://evil.test','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-PaperMind-Client'})
    assert r.status_code == 400
