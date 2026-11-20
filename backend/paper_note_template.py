"""Render the user's paper-note layout using only stored metadata and reading results."""
import re
from urllib.parse import quote

VERSION = 'paper_note_v1'
TITLES = (
    '论文基本信息', '研究背景与问题', '核心设计原则与贡献', '整体架构与数据流',
    '核心算法与执行流程', '关键机制与数学公式', '实验设置', '实验结果',
    '优势、局限与适用条件', '官方代码与实践入口', '工程实现建议（扩展）',
    '核心总结', '关联笔记', '参考资料',
)
MISSING = '当前精读报告未提供足够信息。'


def prose(value):
    # Prevent source/model text from introducing headings, links, images, or tables.
    return re.sub(r'([\\`*_[\]<>|])', r'\\\1', ' '.join(str(value).split()))


def paper_link(meta):
    if meta.get('arxiv_id'):
        aid = quote(str(meta['arxiv_id']), safe='./')
        return f'[arXiv:{aid}](https://arxiv.org/abs/{aid})'
    if meta.get('doi'):
        doi = quote(str(meta['doi']), safe='/')
        return f'[DOI:{doi}](https://doi.org/{doi})'
    return '未提供公开链接'


def render(report, metadata):
    by_stage = {s['section_key']: s for s in report['sections']}
    claims = {c['id']: c for s in by_stage.values() for c in s['claims']}
    synthesis = report.get('synthesis') or {}

    def selected(key):
        return [claims[i] for i in synthesis.get(key, []) if i in claims]

    def stage(key, *categories):
        return [c for c in by_stage.get(key, {}).get('claims', [])
                if not categories or c.get('category') in categories]

    def text(claim):
        status = {'inferred':'推断', 'unsupported':'证据不足', 'conflicted':'存在冲突'}
        label = status.get(claim['verification'], '推断' if claim['kind']=='inference' else None)
        return prose(claim['text']) + (f'（{label}）' if label else '')

    def pages(claim):
        ids = sorted({r['page_index'] + 1 for e in claim.get('evidence', []) if e.get('matched')
                      for r in e.get('regions', [])})
        return '原文第 ' + '、'.join(map(str, ids)) + ' 页' if ids else '未定位'

    def items(rows, ordered=False):
        return ('\n'.join(f'{str(i)+"." if ordered else "-"} {text(c)}（{pages(c)}）'
                         for i, c in enumerate(rows, 1)) if rows else MISSING)

    def table(rows):
        if not rows:
            return MISSING
        return '\n'.join(['| 类型 | 内容 | 原文位置 |', '| --- | --- | --- |',
                          *(f'| {prose(c["topic"])} | {text(c)} | {pages(c)} |' for c in rows)])

    def part(sid, title, body, linked=()):
        ids = list(dict.fromkeys(c['id'] for c in linked))
        return {'id': sid, 'title': title, 'markdown': body, 'claim_ids': ids}

    overview = selected('overview')
    contributions = selected('contributions')
    background = stage('method', 'motivation')
    prereq = stage('prerequisite')
    architecture = stage('method', 'architecture')
    algorithms = stage('method', 'algorithm')
    algorithm_formulas = [c for c in stage('method') if c.get('category') == 'formula' or c.get('formulas')]
    design = stage('experiment', 'design')
    results = stage('experiment', 'main_results', 'ablation', 'efficiency')
    limits = selected('limitations') or stage('experiment', 'limitations')
    implementation = stage('method', 'implementation')
    review = (selected('review_points') or overview or contributions)[:3]
    source = paper_link(metadata)
    authors = metadata.get('authors') or []
    info = '\n'.join([
        f'- **标题**：{prose(metadata.get("title") or "未提供")}',
        f'- **作者**：{prose("、".join(authors) or "未提供")}',
        '- **机构**：未提供',
        f'- **发布时间**：{prose(metadata.get("year") or "未提供")}',
        f'- **论文**：{source}',
        '- **官方代码**：当前报告未核实',
        '- **代码许可**：当前报告未核实',
    ])
    formula_lines, seen = [], set()
    for c in algorithm_formulas:
        for f in c.get('formulas', []):
            latex = f.get('latex')
            if not latex or f['id'] in seen:
                continue
            seen.add(f['id'])
            latex = latex.strip()
            if latex.startswith(r'\[') and latex.endswith(r'\]'):
                latex = latex[2:-2].strip()
            # A fenced code block preserves literal parser output, even for malformed LaTeX.
            fence = '`' * (max([2] + [len(m) for m in re.findall(r'`+', latex)]) + 1)
            formula_lines.append(f'{fence}latex\n{latex}\n{fence}')
    experiment = by_stage.get('experiment')
    no_experiment = experiment is not None and experiment.get('applicable') is False
    experiment_note = '综合精读报告将实验标为不适用。'
    references = []
    if source != '未提供公开链接':
        references.append('- '+source)
    references.append('- PaperMind 绑定的原始论文 PDF（导出时附离线来源链接）。')
    if report.get('warnings'):
        references.extend(['', '### 核验提示', '', *('- '+prose(w) for w in report['warnings'])])
    body = [
        (info, []),
        ('### 2.1 研究背景与问题\n\n'+items(background)+'\n\n### 2.2 前置知识\n\n'+items(prereq), background+prereq),
        (table(contributions), contributions),
        (items(architecture), architecture),
        (items(algorithms, ordered=True), algorithms),
        ('\n\n'.join([items(algorithm_formulas), *formula_lines]), algorithm_formulas),
        (experiment_note if no_experiment else items(design), design),
        (experiment_note if no_experiment else table(results), results),
        ('### 优势\n\n'+items(contributions)+'\n\n### 局限与适用条件\n\n'+items(limits), contributions+limits),
        ('- **官方代码**：当前报告未核实。\n- **代码许可**：当前报告未核实。', []),
        ('可作为复现时的核对项；当前报告未验证生产环境中的表现。\n\n'+items(implementation), implementation),
        ('> [!important] 最值得记住的要点\n'+('\n'.join(f'> {i}. {text(c)}' for i,c in enumerate(review,1)) if review else '> '+MISSING), review),
        ('_待手动添加关联笔记。_', []),
        ('\n'.join(references), []),
    ]
    abstract = overview[:1] or contributions[:1]
    return [part('s00','一句话总结','> [!abstract] 一句话总结\n> '+(text(abstract[0]) if abstract else MISSING),abstract),
            *(part(f's{i:02d}',f'{i}. {title}',content,linked)
              for i,(title,(content,linked)) in enumerate(zip(TITLES,body),1))]
