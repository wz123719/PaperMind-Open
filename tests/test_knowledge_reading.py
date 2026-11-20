import json
from collections import Counter
from threading import Barrier

import pytest
from sqlalchemy import select

from backend import knowledge_reading as knowledge, parsing, queue, reading
from backend.db import engine, reading_stages
from backend.files import LeaseLost
from backend.reading_provider import ReadingFailure
from test_reading import ready


def create(client, parse_id, **body):
    response = client.post(f'/v1/parse-runs/{parse_id}/reading-runs',
                           json={'pipeline_version': knowledge.VERSION, **body})
    assert response.status_code == 202, response.text
    return response.json()


def fixture_provider(config, messages, cancelled):
    payload = json.loads(messages[-1]['content'])
    stage = payload['stage']
    if stage == 'planner':
        ids = [b['block_id'] for b in payload['source']]
        data = {'paper_type': 'Fixture', 'research_problem': 'Fixture only',
                'analysis_plan': dict.fromkeys(knowledge.ANALYZERS, ids)}
    elif stage == 'synthesis':
        ids = [c['id'] for c in payload['claims']]
        data = {'overview': ids[:1], 'contributions': ids[1:2], 'limitations': [], 'review_points': []}
    else:
        src = next(x for x in payload['source'] if len(x['text'].strip()) >= 8)
        data = {'summary': f'{stage} fixture guide', 'claims': [{'topic': next(iter(knowledge.TOPICS[stage])),
                'text': f'{stage} fixture claim', 'kind': 'fact', 'verification': 'supported',
                'evidence': [{'block_id': src['block_id'], 'quote': src['text'][:40]}]}]}
    return json.dumps(data), {'prompt_tokens': 23, 'completion_tokens': 17}


def call(run, provider):
    job = queue.claim('specialist')
    assert job['id'] == run['job_id']
    reading.execute(job, 'specialist', lambda data: queue.progress(job['id'], 'specialist', data), lambda: False, provider)


def test_five_calls_parallel_publish_markdown_notes_and_reuse(client):
    parsed = ready(client)
    run = create(client, parsed['id'])
    assert run['pipeline_version'] == knowledge.VERSION
    assert client.get(f"/v1/reading-runs/{run['id']}/report").status_code == 409
    parallel = Barrier(3, timeout=3)
    seen = []

    def provider(config, messages, cancelled):
        stage = json.loads(messages[-1]['content'])['stage']
        seen.append(stage)
        assert config['max_output_tokens'] == knowledge.ALLOCATION[stage]
        if stage in knowledge.ANALYZERS:
            parallel.wait()
        return fixture_provider(config, messages, cancelled)

    call(run, provider)
    report = reading.report(run['id'])
    assert seen[0] == 'planner' and seen[-1] == 'synthesis' and Counter(seen) == Counter(knowledge.LABELS.keys())
    assert report['usage'] == {'calls': 5, 'input_tokens': 115, 'output_tokens': 85, 'estimated_calls': 0}
    assert report['run']['report_status'] in ('completed', 'completed_with_warnings')
    assert all(c['evidence'][0]['matched'] for s in report['sections'] for c in s['claims'])
    assert create(client, parsed['id'])['id'] == run['id']
    md = client.get(f"/v1/reading-runs/{run['id']}/markdown").json()['markdown']
    assert '## 要点' in md and '架构、算法与公式' in md
    note_body = {'paper_file_id': parsed['paper_file_id'], 'parse_run_id': parsed['id'],
                 'reading_run_id': run['id'], 'operation_key': 'knowledge-test-idempotent'}
    note = client.post('/v1/notes', json=note_body)
    assert note.status_code == 201, note.text
    saved = note.json()
    assert saved['snapshot']['template'] == 'paper_note_v1'
    assert saved['markdown'].startswith('> [!abstract] 一句话总结\n')
    assert '## 5. 核心算法与执行流程' in saved['markdown']
    assert '## 14. 参考资料' in saved['markdown']
    assert '> [!important]' in saved['markdown'] and 'fixture claim' in saved['markdown']
    assert 'LLM-Wiki' not in saved['markdown']
    from backend.note_exports import resources
    exported, _ = resources(saved)
    assert exported.startswith('> [!abstract] 一句话总结\n') and '> [!important]' in exported
    assert client.post('/v1/notes', json=note_body).json()['note_id'] == note.json()['note_id']


def test_failed_specialty_keeps_report_and_retry_only_runs_changed_stages(client):
    parsed = ready(client)
    run = create(client, parsed['id'])
    seen = []
    def provider(config, messages, cancelled):
        stage = json.loads(messages[-1]['content'])['stage']
        seen.append(stage)
        if stage == 'method':
            raise ReadingFailure('fixture method unavailable')
        return fixture_provider(config, messages, cancelled)
    call(run, provider)
    partial = reading.report(run['id'])
    assert seen.count('method') == 2
    assert partial['status'] == 'partially_completed' and partial['failed_stages'] == ['method']
    response = client.post(f"/v1/reading-runs/{run['id']}/retry-specialties")
    assert response.status_code == 202, response.text
    retry = response.json()
    assert retry['id'] != run['id']
    seen.clear()
    def recovered(config, messages, cancelled):
        stage = json.loads(messages[-1]['content'])['stage']
        seen.append(stage)
        raw, usage = fixture_provider(config, messages, cancelled)
        if stage == 'method':
            data = json.loads(raw)
            data['claims'] = [None, {**data['claims'][0], 'topic':'unknown'}, *data['claims'] * 14]
            raw = json.dumps(data)
        return raw, usage
    call(retry, recovered)
    assert seen == ['method', 'synthesis']
    completed = reading.report(retry['id'])
    assert completed['status'] == 'completed_with_warnings'
    sections = {s['section_key']:s for s in completed['sections']}
    assert sections['experiment'] == next(s for s in partial['sections'] if s['section_key']=='experiment')
    assert len(sections['method']['claims']) == 12 and sections['method']['omitted_claims'] == 4
    assert all(c['evidence'][0]['matched'] for c in sections['method']['claims'])
    assert reading.report(run['id']) == partial


def test_budget_and_cancel_prevent_model_calls_and_publishing(client):
    parsed = ready(client)
    low = create(client, parsed['id'], budget={'max_total_tokens': 512})
    with pytest.raises(ReadingFailure, match='预算'):
        call(low, lambda *args: pytest.fail('budget should reject admission before model call'))
    assert client.get(f"/v1/reading-runs/{low['id']}/report").status_code == 409
    assert client.post(f"/jobs/{low['job_id']}/cancel").status_code == 202
    run = create(client, parsed['id'], force=True)
    def cancel(config, messages, cancelled):
        assert client.post(f"/jobs/{run['job_id']}/cancel").status_code == 202
        assert cancelled()
        return fixture_provider(config, messages, cancelled)
    with pytest.raises(LeaseLost):
        call(run, cancel)
    assert queue.get_job(run['job_id'])['status'] == 'cancelled'
    assert client.get(f"/v1/reading-runs/{run['id']}/report").status_code == 409
    with engine.connect() as conn:
        assert conn.execute(select(reading_stages.c.stage_key).where(reading_stages.c.run_id == run['id'])).scalars().all() == ['_knowledge_usage']


def test_experimental_value_validation_and_synthesis_reference_boundary(client):
    parsed = ready(client)
    doc = parsing.structure(parsed['id'])
    source = knowledge.corpus(doc)
    blocks = {b['id']:b for b in doc['blocks']}
    src = source[0]
    output = {'summary': 'fixture', 'claims': [{'text': '准确率达到 96.2%', 'kind': 'fact',
               'verification': 'supported', 'evidence':[{'block_id': src['block_id'], 'quote': src['text'][:40]}]}]}
    checked = knowledge.analyzed(json.dumps(output), 'experiment', blocks, source, parsed['id'], {})['claims'][0]
    assert checked['evidence'][0]['matched'] and checked['verification'] == 'unsupported'
    for ids in (['fabricated:2'], ['experiment:1', 'fabricated:2']):
        with pytest.raises(ReadingFailure):
            knowledge.synthesized(json.dumps({'overview': ids, 'contributions': [], 'limitations': [], 'review_points': []}), [checked])


def test_switch_restores_legacy_submission(client, monkeypatch):
    parsed = ready(client)
    monkeypatch.setenv('PAPERMIND_KNOWLEDGE_READING', '0')
    assert not client.get('/v1/reading-settings').json()['knowledge_reading_enabled']
    assert create(client, parsed['id'], pipeline_version=None)['pipeline_version'] == knowledge.LEGACY
    assert client.post(f"/v1/parse-runs/{parsed['id']}/reading-runs", json={'pipeline_version': knowledge.VERSION}).status_code == 409


def test_short_formula_requires_exact_version_and_preserves_parser_latex():
    formula = {'id':'f', 'type':'formula', 'text':'x^2', 'parse_run_id':'p', 'section_id':None,
               'regions':[{'page_index':0,'bbox':[0,0,.5,.5]}], 'quality_flags':[],
               'data':{'math':{'latex':'x^{2}', 'verification':'unverified'}}}
    doc = {'run':{'id':'p'},'sections':[],'blocks':[formula]}
    source, _, formulas = knowledge.build_context(knowledge.corpus(doc), 'method')
    base = {'topic':'formula', 'text':'解释平方项', 'kind':'fact','verification':'supported',
            'formula_ids':['f'], 'evidence':[{'block_id':'f','quote':'x^2'}]}
    def claim(raw, parse_id):
        return knowledge.analyzed(json.dumps({'summary':'公式','claims':[raw]}), 'method', {'f':formula},
                                  source, parse_id, formulas)['claims'][0]
    matched = claim(base, 'p')
    assert matched['evidence'][0]['matched'] and matched['formulas'][0]['latex'] == 'x^{2}'
    stale = claim(base, 'other')
    assert stale['verification'] == 'unsupported' and stale['formulas'] == []


def test_no_experiment_is_distinct_from_failed_and_numeric_spacing_normalized():
    result = knowledge.analyzed(json.dumps({'summary':'理论论文、没有实验','applicable':False,'claims':[]}),
                                'experiment', {}, [], 'p', {})
    assert result == {'summary':'理论论文、没有实验', 'applicable':False, 'claims':[]}
    assert knowledge.numbers('误差 1.83%，另一个为 2.00%') == knowledge.numbers('1 . 83 % / 2 . 00 %')
    with pytest.raises(ReadingFailure):
        knowledge.analyzed(json.dumps({'summary':'上下文不足','applicable':True,'claims':[]}), 'experiment', {}, [], 'p', {})


def test_targeted_repair_keeps_valid_original_claims(client):
    parsed = ready(client)
    run = create(client, parsed['id'])
    seen = []
    def provider(config, messages, cancelled):
        payload = json.loads(messages[-1]['content'])
        stage = payload['stage']
        seen.append((stage, 'needs_review' in payload))
        if stage != 'experiment':
            return fixture_provider(config, messages, cancelled)
        quote = next(b for b in payload['source'] if len(b['text']) >= 8)
        citation = [{'block_id':quote['block_id'], 'quote':quote['text'][:40]}]
        claim = {'topic':'design', 'text':'保留有效的原始条目', 'kind':'fact',
                 'verification':'supported', 'evidence':citation}
        if 'needs_review' in payload:
            assert set(payload['needs_review']) == {'experiment:2'}
            return json.dumps({'repairs':{'experiment:2':{**claim, 'text':'对有疑问的条目缩小范围'}}})
        return json.dumps({'summary':'实验导览', 'claims':[claim, {**claim, 'text':'错误的准确率 99.5%'}]})
    call(run, provider)
    experiment = next(s for s in reading.report(run['id'])['sections'] if s['section_key'] == 'experiment')
    assert [c['text'] for c in experiment['claims']] == ['保留有效的原始条目', '对有疑问的条目缩小范围']
    assert [c for c in seen if c[1]] == [('experiment', True)]
