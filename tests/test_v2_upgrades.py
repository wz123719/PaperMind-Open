"""Regression tests for PaperMind V2 desktop, DPAPI, math, Obsidian same-title sync, and cross-lingual FTS5."""
import json
from pathlib import Path
import httpx
import pymupdf as fitz
import pytest

from backend import chat_sources, dpapi, knowledge_reading, note_exports, notes, paper_note_template, parsing, queue, reading, translation
from test_parsing import create, run, uploaded


def test_windows_dpapi_roundtrip_and_settings_never_leak_secret(client):
    dpapi.save_secret('workspace', 'sk-live-super-secret-123456')
    assert dpapi.load_secret('workspace') == 'sk-live-super-secret-123456'
    meta = dpapi.secret_metadata('workspace')
    assert meta['has_saved_key'] is True and '123456' not in meta['masked_key'] or meta['masked_key'].endswith('3456')
    assert 'super-secret' not in json.dumps(meta)

    resp = client.post('/v1/reading-settings', json={
        'endpoint': 'https://api.deepseek.com/chat/completions',
        'model': 'deepseek-chat',
        'api_key': 'sk-ui-configured-secret-9999',
        'use_system_proxy': True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['has_saved_key'] is True
    assert body['use_system_proxy'] is True
    assert 'sk-ui-configured-secret-9999' not in resp.text
    assert dpapi.load_secret('workspace') == 'sk-ui-configured-secret-9999'


def test_connectivity_probe_uses_dpapi_secret(client, monkeypatch):
    dpapi.save_secret('workspace', 'sk-probe-key-8888')
    real_client = httpx.Client

    def mock_handler(request: httpx.Request):
        assert request.headers['Authorization'] == 'Bearer sk-probe-key-8888'
        return httpx.Response(200, json={'model': 'deepseek-chat', 'choices': [{'message': {'content': 'OK'}}]})

    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(**{k: v for k, v in kw.items() if k != 'trust_env'}, transport=httpx.MockTransport(mock_handler)))
    res = client.post('/v1/reading-settings/test', json={
        'endpoint': 'https://api.deepseek.com/chat/completions',
        'model': 'deepseek-chat',
        'use_system_proxy': True,
    })
    assert res.status_code == 200 and res.json()['ok'] is True


def test_obsidian_note_preserves_latex_and_same_title_inplace_sync(client, tmp_path):
    f = uploaded(client)
    p = create(client, f['file_id'])
    assert run(p)['status'] == 'succeeded'

    fake_report = {
        'run': {'id': 'r-1', 'parse_run_id': p['id']},
        'pipeline_version': knowledge_reading.VERSION,
        'evidence_contract': reading.EVIDENCE_CONTRACT,
        'synthesis': {'overview': ['method:1'], 'contributions': ['method:1']},
        'warnings': [],
        'sections': [{
            'section_key': 'method',
            'title': '架构、算法与公式',
            'summary': '方法导览',
            'claims': [{
                'id': 'method:1',
                'category': 'formula',
                'topic': '公式作用与变量',
                'text': r'总损失定义为 $\mathcal{L}_{total} = \alpha L_1 + \beta L_2$，并使用 **自适应权重**。',
                'kind': 'fact',
                'verification': 'unreviewed',
                'formulas': [{'id': 'f1', 'latex': r'\mathcal{L}_{total} = \sum_{i=1}^{N} w_i \ell_i'}],
                'evidence': [],
            }],
        }],
    }
    sections = paper_note_template.render(fake_report, {'title': 'Attention Is All You Need', 'authors': ['Vaswani'], 'year': 2017})
    full_md = '\n\n'.join(s['markdown'] for s in sections)
    # Inline math and bold must NOT be escaped with backslashes
    assert r'$\mathcal{L}_{total} = \alpha L_1 + \beta L_2$' in full_md
    assert r'\\mathcal' not in full_md
    assert '**自适应权重**' in full_md
    # Display equations must use $$ ... $$ instead of ```latex
    assert '$$\n\\mathcal{L}_{total} = \\sum_{i=1}^{N} w_i \\ell_i\n$$' in full_md
    assert '```latex' not in full_md

    vault_dir = tmp_path / 'ObsidianVault'
    vault_dir.mkdir()
    note_exports.configure(str(vault_dir), 'Papers', None)
    rev = notes.create(f['file_id'], p['id'], title='Attention: Is All You Need?', key='same-title-note-1')
    rev = notes.edit(rev['note_id'], rev['id'], 'edit-math-1', 's05', '核心推导：$\\alpha_i < \\beta_i$\n\n$$\nE = mc^2\n$$')

    sync1 = client.post(f"/v1/notes/{rev['note_id']}/sync-obsidian", json={'bundle_pdf': False, 'force_overwrite': False})
    assert sync1.status_code == 200, sync1.text
    target_path = vault_dir / 'Papers' / 'Attention Is All You Need.md'
    assert target_path.is_file()
    content1 = target_path.read_text(encoding='utf-8')
    assert '$\\alpha_i < \\beta_i$' in content1 and '$$\nE = mc^2\n$$' in content1
    # bundle_pdf=False keeps vault clean without copying raw PDF
    assert not list((vault_dir / 'Papers').rglob('*.pdf'))

    # Second revision updates the EXACT SAME filename (<论文标题>.md), NOT （2）.md!
    rev2 = notes.edit(rev['note_id'], notes.revision(rev['note_id'])['id'], 'edit-math-2', 's05', '更新后的公式：$\\gamma > 0$')
    sync2 = client.post(f"/v1/notes/{rev2['note_id']}/sync-obsidian", json={'bundle_pdf': False, 'force_overwrite': False})
    assert sync2.status_code == 200, sync2.text
    assert target_path.read_text(encoding='utf-8').find('$\\gamma > 0$') >= 0
    md_files = list((vault_dir / 'Papers').glob('*.md'))
    assert [m.name for m in md_files] == ['Attention Is All You Need.md']


def test_cross_lingual_chinese_question_retrieves_english_paper_blocks():
    doc = {
        'run': {'id': 'run-xl'},
        'sections': [
            {'id': 's1', 'title': '3. Proposed Architecture and Loss Function'},
            {'id': 's2', 'title': '4.2 Ablation Study'},
        ],
        'blocks': [
            {'id': 'b1', 'section_id': 's1', 'type': 'text', 'reading_order': 0,
             'text': 'We propose a novel contrastive objective and regularization loss to stabilize gradient optimization.',
             'regions': [{'page_index': 2, 'bbox': [0.1, 0.1, 0.9, 0.2]}], 'quality_flags': []},
            {'id': 'b2', 'section_id': 's2', 'type': 'table', 'reading_order': 1,
             'text': 'Table 3: Ablation results comparing baseline variants on accuracy.',
             'regions': [{'page_index': 5, 'bbox': [0.1, 0.3, 0.9, 0.5]}], 'quality_flags': []},
        ],
    }
    source, meta = chat_sources.context(doc, '本文提出的损失函数和消融实验结果如何？')
    assert meta['status'] == 'matched' and meta['hits'] == 2
    assert {s['block_id'] for s in source} == {'b1', 'b2'}


def test_multiline_equation_crop_retains_all_rows_and_universal_cancel(client):
    import backend.math_regions as regions
    from test_structure_refinement import glyph

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 100), 'x = a + b', fontsize=10)
    page.insert_text((50, 122), 'y = c + d', fontsize=10)
    cs = [
        glyph('x', 50, 100), glyph('=', 62, 100), glyph('a', 74, 100),
        glyph('y', 50, 122), glyph('=', 62, 122), glyph('c', 74, 122),
    ]
    cs[0]['line'] = cs[1]['line'] = cs[2]['line'] = 1
    cs[3]['line'] = cs[4]['line'] = cs[5]['line'] = 2
    cropped = regions.crop_math(page, fitz.Rect(45, 88, 120, 130))
    assert cropped is not None
    # Both equation lines at y=100 and y=122 must be inside cropped bbox!
    assert cropped['bbox'][1] <= 95 and cropped['bbox'][3] >= 122

    # Universal cancel works on parse_pdf and arxiv_import too
    f = uploaded(client)
    p = create(client, f['file_id'])
    cancelled = client.post(f"/jobs/{p['job_id']}/cancel")
    assert cancelled.status_code == 202 and cancelled.json()['status'] == 'cancelled'
    assert parsing.get_run(p['id'])['status'] == 'cancelled'


def test_three_rule_booktabs_algorithm_recognized_and_preserved_without_needs_review():
    from backend.algorithm_layout import boxed_algorithms, step_bands
    doc = fitz.open()
    p = doc.new_page(width=400, height=500)
    # 3-rule booktabs Algorithm box (no vertical lines, no colon after Algorithm 1, Procedure + Output)
    p.draw_line((40, 60), (360, 60))
    p.insert_text((42, 74), 'Algorithm 1 Sectioning Hierarchical Inputs under a Token Budget', fontsize=10)
    p.draw_line((40, 80), (360, 80))
    lines = [
        '1: Procedure: PARTITION(v, B)',
        '2: Output: ordered section list K',
        '3: if tok(v) <= B then return [v]',
        '4: if leaf(v) then return SplitText(v, B)',
        '5: end if',
        '6: return K',
    ]
    for i, text in enumerate(lines):
        p.insert_text((45, 98 + i * 16), text, fontsize=9.5)
    p.draw_line((40, 200), (360, 200))

    found = boxed_algorithms(p)
    assert len(found) == 1 and found[0]['evidence'] == 'three_rule_booktabs_algorithm'
    steps = step_bands(p, found[0]['rect'])
    assert len(steps) >= 5

    # Translation preserves algorithm boxes and misclassified algorithm tables cleanly without needs_review!
    assert translation.units({'id': 'a1', 'type': 'algorithm', 'text': '\n'.join(lines), 'data': {}})[1] == 'preserved'
    assert translation.units({'id': 'a2', 'type': 'algorithm_step', 'text': '4: if leaf(v) then return SplitText(v, B)', 'quality_flags': ['content_unverified'], 'data': {}})[1] == 'preserved'
    assert translation.units({'id': 't1', 'type': 'table', 'text': 'Algorithm 1 Sectioning\n1: Procedure: P\n2: Output: K\n3: if x then return [v]\n4: end if', 'data': {}})[1] == 'preserved'


def test_persistent_highlights_and_save_to_note_workflow(client, tmp_path):
    f = uploaded(client)
    fid, pid = f['file_id'], f['paper_id']

    # 1. Create two persistent highlights
    r1 = client.post(f'/v1/files/{fid}/highlights', json={
        'page_index': 0,
        'text': 'We introduce a lightweight sparse attention block.',
        'regions': [{'page_index': 0, 'bbox': [0.1, 0.2, 0.85, 0.24]}],
        'color': 'yellow',
        'note': '核心创新点',
    })
    assert r1.status_code == 201
    h1 = r1.json()
    assert h1['color'] == 'yellow' and h1['note'] == '核心创新点'

    r2 = client.post(f'/v1/files/{fid}/highlights', json={
        'page_index': 0,
        'text': 'Our model reduces latency by 3.2x.',
        'regions': [{'page_index': 0, 'bbox': [0.1, 0.35, 0.72, 0.39]}],
        'color': 'green',
    })
    assert r2.status_code == 201
    h2 = r2.json()

    # 2. List & update highlight
    listed = client.get(f'/v1/files/{fid}/highlights')
    assert listed.status_code == 200 and len(listed.json()) == 2
    patched = client.patch(f"/v1/highlights/{h2['id']}", json={'color': 'blue', 'note': '关键性能数据'})
    assert patched.status_code == 200 and patched.json()['color'] == 'blue' and patched.json()['note'] == '关键性能数据'

    # 3. Save first highlight to note (auto-creates a paper note)
    saved1 = client.post('/v1/highlights/save-to-note', json={'highlight_ids': [h1['id']]})
    assert saved1.status_code == 200
    body1 = saved1.json()
    nid = body1['note_id']
    assert body1['count'] == 1
    assert '> [!quote] 原文高亮 · 第 1 页' in body1['revision']['markdown']
    assert 'We introduce a lightweight sparse attention block.' in body1['revision']['markdown']
    assert '**批注**：核心创新点' in body1['revision']['markdown']

    # 4. Append second highlight to a specific section of the same note
    saved2 = client.post('/v1/highlights/save-to-note', json={
        'highlight_ids': [h2['id']],
        'note_id': nid,
        'section_id': 's02',
    })
    assert saved2.status_code == 200 and saved2.json()['section_id'] == 's02'

    # 5. Evidence endpoint and Obsidian same-title sync handle highlight origins cleanly
    ev = client.get(f'/v1/notes/{nid}/evidence')
    assert ev.status_code == 200
    quotes = [e['quote'] for e in ev.json()['evidence']]
    assert 'We introduce a lightweight sparse attention block.' in quotes
    assert 'Our model reduces latency by 3.2x.' in quotes

    vault = tmp_path / 'obsidian-hl'
    vault.mkdir()
    assert client.post('/v1/vault-settings', json={'root': str(vault), 'subdir': 'Papers', 'expected_revision': None}).status_code == 200
    sync = client.post(f'/v1/notes/{nid}/sync-obsidian', json={'bundle_pdf': False, 'force_overwrite': False})
    assert sync.status_code == 200
    md_path = vault / 'Papers' / sync.json()['plan']['target']
    assert md_path.is_file()
    md_text = md_path.read_text(encoding='utf-8')
    assert '> [!quote] 原文高亮 · 第 1 页' in md_text
    assert 'Our model reduces latency by 3.2x.' in md_text

    # 6. Delete single highlight, clear all highlights for file, and cascade cleanup on delete_paper
    assert client.delete(f"/v1/highlights/{h1['id']}").status_code == 200
    assert len(client.get(f'/v1/files/{fid}/highlights').json()) == 1
    cleared = client.delete(f'/v1/files/{fid}/highlights')
    assert cleared.status_code == 200 and cleared.json()['deleted_count'] == 1
    assert client.get(f'/v1/files/{fid}/highlights').json() == []
    assert client.post(f'/v1/files/{fid}/highlights', json={
        'page_index': 0, 'text': 'Cascade check', 'regions': [{'page_index': 0, 'bbox': [0.1, 0.1, 0.4, 0.15]}],
    }).status_code == 201
    assert client.delete(f'/papers/{pid}').status_code == 200
    assert client.get(f'/v1/files/{fid}/highlights').status_code == 404


def test_unified_workspace_preferences_and_task_model_reset(client):
    # 1. Default workspace preferences & capabilities
    res = client.get('/v1/workspace-preferences')
    assert res.status_code == 200
    data = res.json()
    assert data['parse_mode'] == 'docling'
    assert data['default_reader_mode'] == 'bilingual'
    assert data['default_highlight_color'] == 'yellow'
    assert 'capabilities' in data and 'docling_available' in data['capabilities']

    # 2. Save custom preferences & verify persistence
    saved = client.post('/v1/workspace-preferences', json={
        'parse_mode': 'native',
        'parse_formulas': False,
        'default_reader_mode': 'original',
        'default_highlight_color': 'blue',
        'default_bundle_pdf': True,
        'show_outline_by_default': False,
    })
    assert saved.status_code == 200
    body = saved.json()
    assert body['parse_mode'] == 'native'
    assert body['parse_formulas'] is False
    assert body['default_reader_mode'] == 'original'
    assert body['default_highlight_color'] == 'blue'
    assert body['default_bundle_pdf'] is True
    assert body['show_outline_by_default'] is False

    # 3. Aggregated settings overview returns all 4 domains in one call
    ov = client.get('/v1/settings-overview')
    assert ov.status_code == 200
    ov_data = ov.json()
    assert ov_data['preferences']['parse_mode'] == 'native'
    assert set(ov_data.keys()) >= {'preferences', 'llm', 'translation_model', 'glossary_model', 'vault', 'capabilities'}

    # 4. Override translation task model and then reset back to global default
    over = client.post('/v1/task-model-settings/translation', json={
        'endpoint': 'https://api.deepseek.com/chat/completions',
        'model': 'deepseek-chat',
        'key_env': '',
        'expected_revision': None,
        'use_system_proxy': False,
    })
    assert over.status_code == 200 and over.json()['source'] == 'task'

    reset = client.delete('/v1/task-model-settings/translation')
    assert reset.status_code == 200 and reset.json()['source'] == 'workspace'
