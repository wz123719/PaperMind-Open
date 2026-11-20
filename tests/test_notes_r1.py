import re
import pytest,yaml
from backend.note_markdown import export_markdown,regions
from test_notes import setup_note,edit,vault,target

@pytest.mark.parametrize('math',[
    '$a < b$',
    '$$\na < b, c > d\n$$',
    '$$ a < b, c > d $$',
    '$a < b$ and $c > d$ and $x_i < y_i$\n\n$$\np < q \\\\\nr > s\n$$',
    r'$a < b \quad \text{price \$3} > c$',
    '$a &lt; b$ and $c &gt; d$',
])
def test_actual_api_review_preview_publish_preserves_math_metadata_and_assets(client,tmp_path,math):
    rev,parsed,_=setup_note(client,read=True,image=True);vault(tmp_path)
    title='R1 <Graph> &lt;Literal&gt; 中文: "标题"\nstatus: "not a field"\n---\n作者'
    response=client.post('/v1/notes',json={'paper_file_id':parsed['paper_file_id'],'parse_run_id':parsed['id'],
        'title':title,'operation_key':'r1-title-create-key'})
    assert response.status_code==201;rev=response.json()
    asset=client.get('/v1/notes/'+rev['note_id']+'/assets').json()[0]
    code='```python\nif a < b and c > d:\n    print("<script>code only</script>")\n![example](https://example.invalid/image.png)\n```'
    inline='`<Type> ![example](asset:not-a-resource)`'
    tilde='~~~~text\n<Graph> a < b\n![example](file:///C:/not-an-asset.png)\n~~~~'
    body=math+'\n\n'+code+'\n\n'+inline+'\n\n'+tilde+'\n\n![actual](asset:'+asset['id']+')\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))'
    response=client.patch('/v1/notes/'+rev['note_id']+'/sections',json={'expected_revision':rev['id'],
        'operation_key':'r1-save-body-key','section_id':'s06','markdown':body})
    assert response.status_code==200;rev=response.json()
    reviewed=client.post('/v1/notes/'+rev['note_id']+'/review',json={'revision_id':rev['id'],'content_hash':rev['content_hash']})
    assert reviewed.status_code==200 and reviewed.json()['reviewed']
    response=client.post('/v1/notes/'+rev['note_id']+'/export-preview',json={'revision_id':rev['id'],
        'content_hash':rev['content_hash'],'operation_key':'r1-publish-preview'})
    assert response.status_code==200,response.text
    record=response.json();assert not target(record).exists()
    response=client.post('/v1/note-exports/'+record['id']+'/commit');assert response.status_code==200,response.text
    assert response.json()['status']=='succeeded';raw=target(record).read_bytes().decode('utf-8')
    assert math in raw and code in raw and inline in raw and tilde in raw
    front=re.split(r'^---\s*$',raw,flags=re.M)[1];metadata=yaml.safe_load(front)
    assert all(metadata[k]==v for k,v in rev['snapshot']['metadata'].items())
    assert metadata['title']==title
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in raw and '[unsafe](blocked-unsafe-url)' in raw
    assert len(record['plan']['files'])==2
    for item in record['plan']['files']:
        import hashlib
        assert hashlib.sha256((target(record).parent/item['relative']).read_bytes()).hexdigest()==item['sha256']

@pytest.mark.parametrize('danger',['javascript:alert(1)','JaVaScRiPt:alert(1)','javascript&#58;alert(1)','java\tscript:alert(1)','data:text/html,test','file:///C:/secret','vbscript:test'])
def test_prose_urls_remain_blocked_with_region_aware_export(danger):
    output=export_markdown('[unsafe]('+danger+')',lambda m:pytest.fail('unexpected image'))
    assert output.startswith('[unsafe](blocked-unsafe-url)')

def test_region_boundaries_escaped_dollars_code_examples_and_split_html():
    text='---\ntitle: "<Graph>\\n---"\n---\n\n$ a < b $\n\n$$\nc > d\n$$\n\n`<inline>`\n\n<img src="`literal`" onerror=bad>\n\n\\$ not math <script>bad</script>\n'
    output=export_markdown(text,lambda m:pytest.fail('unexpected image'))
    assert output.startswith('---\ntitle: "<Graph>\\n---"\n---\n')
    assert '$ a < b $' in output and '$$\nc > d\n$$' in output and '`<inline>`' in output
    assert '<img' not in output and '<script>bad' not in output and '&lt;img src=' in output
    assert ''.join(part for _,part in regions(text))==text

def test_old_pending_export_plan_rejected_without_rewriting_history(client,tmp_path):
    from backend import note_exports,notes
    from backend.db import engine,write_tx,note_exports as table
    from sqlalchemy import select
    rev,_,_=setup_note(client);vault(tmp_path);rev=notes.review(rev['note_id'],rev['id'],rev['content_hash'])
    planned=note_exports.preview(rev['note_id'],rev['id'],rev['content_hash'],'r1-plan-version-key')
    with engine.connect() as c:old=dict(c.execute(select(table.c.plan).where(table.c.id==planned['id'])).scalar_one())
    del old['render_version']
    with write_tx() as c:c.execute(table.update().where(table.c.id==planned['id']).values(plan=old))
    before=note_exports.get(planned['id'])
    response=client.post('/v1/note-exports/'+planned['id']+'/commit')
    assert response.status_code==409 and '旧导出计划' in response.text
    assert note_exports.get(planned['id'])==before and not target(before).exists()
    replay=client.post('/v1/notes/'+rev['note_id']+'/export-preview',json={'revision_id':rev['id'],'content_hash':rev['content_hash'],'operation_key':'r1-plan-version-key'})
    assert replay.status_code==409 and note_exports.get(planned['id'])==before
    fresh=note_exports.preview(rev['note_id'],rev['id'],rev['content_hash'],'r1-new-plan-version-key')
    assert fresh['plan']['render_version']=='note-markdown-2-regions'
    assert note_exports.commit(fresh['id'])['status']=='succeeded'
