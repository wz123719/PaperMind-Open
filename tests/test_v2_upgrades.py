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
