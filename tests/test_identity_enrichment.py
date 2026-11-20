"""R1 regressions: real API/Worker/storage pipeline, controlled arXiv transport.

All identifiers, including synthetic v8, are fixture inputs, not live claims.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import httpx
import pytest
from sqlalchemy import select
from backend import arxiv, queue
from backend.db import engine, papers, paper_files, STORAGE
from backend.worker import execute
from conftest import pdf_bytes

def upload(client, data):
    r = client.post('/papers', files={'file': ('upload.pdf', data, 'application/pdf')})
    assert r.status_code == 201, r.text
    return r.json()

def snapshot():
    with engine.connect() as conn:
        return {table.name: [dict(row) for row in conn.execute(select(table).order_by(table.c.id)).mappings()]
                for table in (papers, paper_files)}

def downloader(data, doi=None, barrier=None, year=2017):
    def download(payload, path, progress):
        if barrier:
            barrier.wait(timeout=10)
        def respond(request):
            if request.url.host == 'export.arxiv.org':
                doi_tag = f'<x:doi>{doi}</x:doi>' if doi else ''
                return httpx.Response(200, text=f'''<feed xmlns="http://www.w3.org/2005/Atom"
                    xmlns:x="http://arxiv.org/schemas/atom"><entry>
                    <id>http://arxiv.org/abs/{payload['canonical']}</id>
                    <title>Remote title must not replace existing title</title>
                    <published>{year}-01-01T00:00:00Z</published>
                    <author><name>Remote Author</name></author>{doi_tag}</entry></feed>''')
            return httpx.Response(200, content=data)
        with httpx.Client(transport=httpx.MockTransport(respond)) as c:
            return arxiv.download(payload, path, progress, c)
    return download

def run_import(client, data, canonical='1706.03762v7', doi=None):
    r = client.post('/papers/imports', json={'input': canonical})
    assert r.status_code == 202
    jid = r.json()['job_id']
    worker = 'r1-' + jid
    job = queue.claim(worker)
    assert job['id'] == jid
    execute(job, worker, downloader(data, doi))
    return queue.get_job(jid)

def test_upload_then_worker_enrich_repeat_and_new_version(client):
    a = pdf_bytes(title='Keep local title')
    original = upload(client, a)
    before = snapshot()
    imported = run_import(client, a, doi='10.1234/r1')
    assert imported['status'] == 'succeeded'
    assert imported['result'] == {'paper_id': original['paper_id'], 'file_id': original['file_id'], 'duplicate': True}
    filled = snapshot()
    paper, file = filled['papers'][0], filled['paper_files'][0]
    assert len(filled['papers']) == len(filled['paper_files']) == 1
    assert paper['arxiv_id'] == '1706.03762' and paper['doi'] == '10.1234/r1' and paper['year'] == 2017
    assert paper['title'] == 'Keep local title' and paper['authors'] == ['Test Author']
    assert paper['created_at'] == before['papers'][0]['created_at']
    assert file['arxiv_version'] == 7
    assert file == {**before['paper_files'][0], 'arxiv_version': 7}
    assert file['source'] == 'upload' and file['version'] == 1
    # Import provenance remains in persistent jobs, never relabels first source.
    assert imported['payload']['canonical'] == '1706.03762v7'

    repeated = run_import(client, a, doi='10.1234/r1')
    assert repeated['status'] == 'succeeded' and repeated['result'] == imported['result']
    assert snapshot() == filled

    b = pdf_bytes(title='Different bytes for synthetic v8')
    next_version = run_import(client, b, '1706.03762v8', doi='10.1234/r1')
    assert next_version['status'] == 'succeeded'
    assert next_version['result']['paper_id'] == original['paper_id']
    assert next_version['result']['file_id'] != original['file_id']
    assert not next_version['result']['duplicate']
    library = client.get('/papers').json()
    assert len(library) == 1
    assert [f['version'] for f in library[0]['files']] == [2, 1]
    assert [f['arxiv_version'] for f in library[0]['files']] == [8, 7]
    assert [f['source'] for f in library[0]['files']] == ['arxiv:1706.03762v8', 'upload']
    assert library[0]['title'] == 'Keep local title'
    assert hashlib.sha256(client.get('/files/' + original['file_id'] + '/content').content).hexdigest() == file['sha256']
    assert not list((STORAGE/'tmp').glob('*.part'))

@pytest.mark.parametrize('owned', ['arxiv_id', 'doi'])
def test_worker_conflict_identifier_owned_by_other_paper_is_atomic(client, owned):
    data = pdf_bytes(title='Unknown identity')
    upload(client, data)
    upload(client, pdf_bytes(title='Separate owner', arxiv='1706.03762v7' if owned == 'arxiv_id' else None,
                             doi='10.1234/owned' if owned == 'doi' else None))
    before = snapshot()
    job = run_import(client, data, doi='10.1234/owned')
    assert job['result'] is None and job['status'] == 'queued'
    assert '身份冲突' in job['error'] and '已归属其他论文' in job['error'] and '人工确认' in job['error']
    assert snapshot() == before  # No partial arXiv/DOI/year/version enrichment.
    assert not list((STORAGE/'tmp').glob('*.part'))

@pytest.mark.parametrize('canonical,doi,field', [
    ('2301.12345v7', '10.1234/original', 'arxiv_id'),
    ('1706.03762v8', '10.1234/original', 'arxiv_version'),
    ('1706.03762v7', '10.1234/different', 'doi'),
])
def test_worker_conflict_existing_enriched_identity_is_preserved(client, canonical, doi, field):
    data = pdf_bytes()
    upload(client, data)
    assert run_import(client, data, doi='10.1234/original')['status'] == 'succeeded'
    before = snapshot()
    job = run_import(client, data, canonical, doi)
    assert job['result'] is None and '身份冲突' in job['error'] and field in job['error']
    assert snapshot() == before

def test_conflicting_embedded_identifiers_and_new_file_api_conflict(client):
    original = upload(client, pdf_bytes(arxiv='1706.03762v7', doi='10.1234/one'))
    before = snapshot()
    # Same bytes cannot be assigned a remote ID contradicting explicit PDF metadata.
    job = run_import(client, pdf_bytes(arxiv='1706.03762v7', doi='10.1234/one'), '2301.12345v7')
    assert 'arxiv_id' in job['error'] and snapshot() == before
    # A different PDF with same DOI but incompatible arXiv ID must also be rejected.
    response = client.post('/papers', files={'file': ('other.pdf', pdf_bytes(title='Other',
        arxiv='2301.12345v7', doi='10.1234/one'), 'application/pdf')})
    assert response.status_code == 409
    assert '身份冲突' in response.json()['detail'] and '人工确认' in response.json()['detail']
    assert snapshot() == before
    assert client.get('/papers/' + original['paper_id']).json()['arxiv_id'] == '1706.03762'

def test_concurrent_worker_enrichment_preserves_single_file(client):
    data = pdf_bytes()
    original = upload(client, data)
    before = snapshot()
    claims = []
    for n in range(4):
        jid = queue.enqueue(arxiv.normalize('1706.03762v7'))
        worker = f'r1-concurrent-{n}'
        job = queue.claim(worker)
        assert job['id'] == jid
        claims.append((job, worker))
    controlled = downloader(data, '10.1234/concurrent', Barrier(4))
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda pair: execute(*pair, controlled), claims))
    results = [queue.get_job(job['id']) for job, _ in claims]
    assert all(j['status'] == 'succeeded' for j in results)
    assert all(j['result'] == {'paper_id': original['paper_id'], 'file_id': original['file_id'], 'duplicate': True} for j in results)
    state = snapshot()
    assert len(state['papers']) == len(state['paper_files']) == 1
    assert state['papers'][0]['arxiv_id'] == '1706.03762'
    assert state['papers'][0]['doi'] == '10.1234/concurrent'
    assert state['paper_files'][0] == {**before['paper_files'][0], 'arxiv_version': 7}

def test_concurrent_disagreeing_worker_enrichment_has_one_winner(client):
    data = pdf_bytes()
    original = upload(client, data)
    claims = []
    for n, canonical in enumerate(('1706.03762v7', '2301.12345v7')):
        queue.enqueue(arxiv.normalize(canonical))
        worker = f'r1-conflicting-{n}'
        claims.append((queue.claim(worker), worker))
    controlled = downloader(data, barrier=Barrier(2))
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda pair: execute(*pair, controlled), claims))
    outcomes = [queue.get_job(job['id']) for job, _ in claims]
    good = [j for j in outcomes if j['status'] == 'succeeded']
    bad = [j for j in outcomes if j['error']]
    assert len(good) == len(bad) == 1
    assert '身份冲突' in bad[0]['error'] and 'arxiv_id' in bad[0]['error']
    state = snapshot()
    assert len(state['papers']) == len(state['paper_files']) == 1
    assert state['papers'][0]['id'] == original['paper_id']
    assert state['papers'][0]['arxiv_id'] == good[0]['payload']['arxiv_id']
    assert state['paper_files'][0]['id'] == original['file_id']
    assert state['paper_files'][0]['source'] == 'upload' and state['paper_files'][0]['version'] == 1

def test_duplicate_missing_fields_preserves_populated_metadata_and_version(client):
    data = pdf_bytes()
    original = upload(client, data)
    assert run_import(client, data, doi='10.1234/original')['status'] == 'succeeded'
    before = snapshot()
    # A later plain upload has no arXiv fields and cannot erase filled metadata.
    again = upload(client, data)
    assert again['duplicate'] and again['file_id'] == original['file_id']
    assert snapshot() == before
    jid = queue.enqueue(arxiv.normalize('1706.03762v7'))
    execute(queue.claim('later-year'), 'later-year', downloader(data, '10.1234/original', year=2024))
    assert queue.get_job(jid)['status'] == 'succeeded'
    assert snapshot() == before  # A differing bibliographic year never overwrites one already present.

def test_concurrent_different_files_competing_for_same_identity(client):
    data = [pdf_bytes(title=f'Unknown identity {n}') for n in range(2)]
    originals = [upload(client, blob) for blob in data]
    before = snapshot()
    claims = []
    for n in range(2):
        queue.enqueue(arxiv.normalize('1706.03762v7'))
        worker = f'r1-owner-race-{n}'
        claims.append((queue.claim(worker), worker))
    barrier = Barrier(2)
    def run(n):
        execute(*claims[n], downloader(data[n], '10.1234/single-owner', barrier))
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(run, range(2)))
    outcomes = [queue.get_job(job['id']) for job, _ in claims]
    winners = [n for n, outcome in enumerate(outcomes) if outcome['status'] == 'succeeded']
    assert len(winners) == 1
    winner = winners[0]
    assert '已归属其他论文' in outcomes[1-winner]['error']
    after = snapshot()
    assert len(after['papers']) == len(after['paper_files']) == 2
    for original, blob in zip(originals, data):
        paper = next(p for p in after['papers'] if p['id'] == original['paper_id'])
        file = next(f for f in after['paper_files'] if f['id'] == original['file_id'])
        if original == originals[winner]:
            assert paper['arxiv_id'] == '1706.03762' and file['arxiv_version'] == 7
        else:
            assert paper == next(p for p in before['papers'] if p['id'] == paper['id'])
            assert file == next(f for f in before['paper_files'] if f['id'] == file['id'])
        assert client.get('/files/'+file['id']+'/content').content == blob

def test_worker_fills_previously_unknown_bibliographic_fields(client):
    from io import BytesIO
    from pypdf import PdfWriter
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    writer.write(output)
    data = output.getvalue()
    original = upload(client, data)
    assert original['paper']['title'] is None and original['paper']['authors'] is None
    assert run_import(client, data, doi='10.1234/empty')['status'] == 'succeeded'
    enriched = client.get('/papers/'+original['paper_id']).json()
    assert enriched['title'] == 'Remote title must not replace existing title'
    assert enriched['authors'] == ['Remote Author'] and enriched['year'] == 2017
    assert enriched['doi'] == '10.1234/empty' and enriched['arxiv_id'] == '1706.03762'
    assert enriched['files'][0]['id'] == original['file_id'] and enriched['files'][0]['arxiv_version'] == 7
