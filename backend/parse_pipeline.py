"""Docling structure plus PyMuPDF text/regions; explicit native-only fallback."""
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from sqlalchemy import select
from .db import STORAGE, engine, paper_files, uid
from .files import file_path
from .geometry import page_info, region
from . import parsing

os.environ.setdefault('HF_HOME', str(STORAGE/'models'/'huggingface'))
os.environ.setdefault('DOCLING_CACHE_DIR', str(STORAGE/'models'/'docling-cache'))
os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
os.environ.setdefault('OMP_NUM_THREADS', '4')

def native_document(path, rid):
    import pymupdf as fitz
    pages, native = [], []
    with fitz.open(path) as pdf:
        for p in pdf:
            info = page_info(p)
            pages.append(info)
            for block in p.get_text('blocks', sort=True):
                if block[6] != 0 or not block[4].strip():
                    continue
                native.append({'page_index': p.number, 'text': block[4].strip(),
                    'region': region(p.number, block[:4], info['width_points'], info['height_points'])})
    return pages, native

def make_block(rid, order, kind, text, regions, source, flags=None, data=None, section_id=None):
    return {'id': f'{rid}:b{order:06}', 'section_id': section_id, 'type': kind,
        'text': text, 'reading_order': order, 'regions': regions, 'source': source,
        'quality_flags': flags or [], 'data': data or {}}

def native_parse(path, rid, config, work, report):
    pages, native = native_document(path, rid)
    blocks = [make_block(rid, n, 'text', b['text'], [b['region']], 'pymupdf', ['native_only', 'reading_order_unverified'])
              for n, b in enumerate(native)]
    warnings = ['原生降级模式：没有 Docling 章节/表格/公式识别；阅读顺序未核验，不计入 Docling 完成。']
    if not blocks:
        warnings.append('未提取到原生文字；可能为扫描 PDF，本配置未启用 OCR。')
    return {'pages': pages, 'sections': [], 'blocks': blocks, 'warnings': warnings,
            'native_text': native, 'raw_docling': None}

_converters = {}

def link_compound_figures(blocks):
    """Retain both panels when an explicit left/right caption describes split items.

    This is a visible candidate relation, not a quality certification. Never merge
    unrelated pages or infer a missing caption from title similarity.
    """
    for b in blocks:
        caption=b['data'].get('caption') or ''
        if b['type']!='picture' or not re.search(r'(?i)\bleft\b',caption) or not re.search(r'(?i)\bright\b',caption) or len(b['regions'])!=1:
            continue
        main=b['regions'][0];mx0,my0,mx1,my1=main['bbox']
        for other in blocks:
            if other is b or other['type']!='picture' or other['data'].get('caption') or len(other['regions'])!=1:continue
            r=other['regions'][0]
            if r['page_index']!=main['page_index']:continue
            x0,y0,x1,y1=r['bbox']
            overlap=max(0,min(y1,my1)-max(y0,my0))
            height=min(y1-y0,my1-my0)
            gap=max(x0-mx1,mx0-x1,0)
            if height>0 and overlap/height>=.7 and 0<gap<=.15:
                b['regions']=sorted(b['regions']+[r],key=lambda a:a['bbox'][0])
                b['data']['assets']=list(dict.fromkeys(b['data']['assets']+other['data'].get('assets',[])))
                b['data'].setdefault('companion_picture_refs',[]).append(other['data'].get('docling_ref'))
                b['quality_flags'].append('compound_figure_relation_candidate')

def docling_parse(path, rid, config, work, report):
    session=None
    try:
        from .source_adapter import prepare_source,align_document
        source_document=prepare_source(config,work)
        if config.get('formula_backend')=='pdf_math_layout+RapidLaTeXOCR' and config['formulas']:
            report({'stage':'math_initialization','message':'初始化独立数学增强组件：阶段内处理中'})
            from .local_math_backend import RapidSession
            session=RapidSession(work,config,source_path=path)
            session.source_document=source_document
        result=_docling_parse(path,rid,config,work,report,session)
        result['source_document']=align_document(source_document,result['blocks'])
        if source_document['status']!='available':result['warnings'].append('源文件路线未使用：'+source_document.get('reason',source_document['status'])+'；执行PDF路线。')
        if session is not None:
            result['object_routing']={'events':session.route_events,'cache_events':session.cache.events,'verification':'unverified'}
        present={n['page_index'] for n in result['native_text']}
        missing=[p['page_index'] for p in result['pages'] if p['page_index'] not in present]
        result['capabilities']={'native_text_pages':sorted(present),'ocr':'disabled','pages_without_native_text':missing}
        if missing:result['warnings'].append('部分页面没有PDF原生文字，当前OCR未启用；扫描内容能力缺失，不能推断已识别。')
        return result
    finally:
        if session is not None:session.close()


def _docling_parse(path,rid,config,work,report,session):
    import pymupdf as fitz
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat, ConversionStatus
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
        from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
    except ImportError as exc:
        raise parsing.ParseFailure('Docling 依赖不可用；请运行 setup.ps1 完成默认安装（不要选 -CoreOnly）。未自动降级。') from exc
    report({'stage':'docling','message':'Docling 正在识别版面、表格'+('与公式' if config['formulas'] else '（公式增强关闭）')})
    key = (bool(config['formulas']),config.get('model_manifest_sha256'),id(report))
    models=STORAGE/'models'/'docling-cache'/'models'
    required=[models/'ds4sd--docling-layout-heron'/'model.safetensors',
              models/'ds4sd--docling-models'/'model_artifacts'/'tableformer'/'accurate'/'tm_config.json']
    if config['formulas'] and config.get('formula_backend')!='pdf_math_layout+RapidLaTeXOCR':
        required.append(models/'ds4sd--CodeFormulaV2'/'config.json')
        required.append(models/'ds4sd--CodeFormulaV2'/'model.safetensors')
    if not all(p.is_file() for p in required):
        raise parsing.ParseFailure('Docling 模型未就绪，请先完成 setup-models.py 或 setup-models-resumable.py；未自动降级。')
    if key not in _converters:
        _converters.clear()
        options = PdfPipelineOptions()
        options.artifacts_path=models
        options.do_ocr = False
        options.do_table_structure = True
        options.table_structure_options.mode = TableFormerMode.ACCURATE
        options.do_formula_enrichment = bool(config['formulas']) and config.get('formula_backend')!='pdf_math_layout+RapidLaTeXOCR'
        options.generate_page_images = True
        options.images_scale = 1.0
        options.document_timeout = 1200
        options.accelerator_options = AcceleratorOptions(num_threads=4, device=AcceleratorDevice.CPU)
        from .parse_progress import progress_pipeline
        records={}
        _converters[key] = (DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(
            pipeline_cls=progress_pipeline(report,config,records,session=session,source_path=path),pipeline_options=options)}),records)
    converter,records=_converters[key]
    converted = converter.convert(path, raises_on_error=True)
    if converted.status != ConversionStatus.SUCCESS:
        raise parsing.ParseFailure('Docling 未完整成功，产物未发布；请查看 Worker 日志')
    doc = converted.document
    report({'stage': 'mapping', 'message': '映射 Docling 来源区域并提取原生文字'})
    pages, native = native_document(path, rid)
    sections, blocks, warnings, stack = [], [], [], []
    numbered_sections={}
    if not config['formulas']:
        warnings.append('公式增强未启用：公式仅作为候选和原文区域，不保证 LaTeX 识别。')
    if not native:
        warnings.append('没有原生可选文字；OCR 未启用，扫描/无文字页面可能缺失。')
    with fitz.open(path) as pdf:
        for item, level in doc.iterate_items():
            kind = getattr(getattr(item, 'label', None), 'value', str(getattr(item, 'label', 'unknown')))
            if kind in ('list', 'ordered_list', 'inline', 'chapter', 'section'):
                continue
            provs = getattr(item, 'prov', [])
            regions, flags = [], ['semantic_quality_unverified']
            for prov in provs:
                index = prov.page_no - 1
                if not 0 <= index < len(pages):
                    flags.append('invalid_page_provenance')
                    continue
                dp = doc.pages[prov.page_no]
                size = dp.size
                page = pdf[index]
                rendered = page.rect
                if abs(rendered.width/rendered.height - size.width/size.height) > .03:
                    flags.append('page_dimensions_mismatch')
                    continue
                b = prov.bbox.to_top_left_origin(page_height=size.height)
                display = fitz.Rect(b.l*rendered.width/size.width, b.t*rendered.height/size.height,
                                    b.r*rendered.width/size.width, b.b*rendered.height/size.height)
                unrotated = display * page.derotation_matrix
                mapped=region(index, list(unrotated), pages[index]['width_points'], pages[index]['height_points'])
                x0,y0,x1,y1=mapped['bbox']
                if x1<=x0 or y1<=y0:
                    flags.append('invalid_bbox')
                    continue
                regions.append(mapped)
            text = getattr(item, 'text', '') or ''
            data = {'docling_ref': item.self_ref, 'caption': None, 'caption_refs': [], 'references': [],
                    'reference_status': 'unknown', 'assets': []}
            data['provenance_page_sizes']=[{'page_index':p.page_no-1,'width':doc.pages[p.page_no].size.width,
                'height':doc.pages[p.page_no].size.height} for p in provs if p.page_no in doc.pages]
            if kind == 'table':
                try:
                    text = item.export_to_markdown(doc=doc)
                    data['raw_markdown']=text
                    # Docling's export prepends the linked caption. Keep table content
                    # separate so an erroneous caption relation cannot relabel it.
                    lines=text.splitlines()
                    first_row=next((n for n,line in enumerate(lines) if line.lstrip().startswith('|')),None)
                    if first_row is not None:text='\n'.join(lines[first_row:])
                    data['table'] = item.data.model_dump(mode='json')
                except Exception:
                    flags.append('table_export_missing')
            if kind in ('table', 'picture'):
                data['caption_refs'] = [ref.cref for ref in getattr(item, 'captions', [])]
                try:
                    data['caption'] = item.caption_text(doc) or None
                except Exception:
                    flags.append('caption_unknown')
                caption=data['caption']
                if kind=='table' and caption and re.match(r'(?i)^fig(?:ure)?\b',caption):
                    data['original_object_label']='figure';data['object_type_evidence']='structured_table_cells'
                if caption and ((kind=='table' and re.match(r'(?i)^fig(?:ure)?\b',caption)) or
                                (kind=='picture' and re.match(r'(?i)^table\b',caption))):
                    data['raw_caption']=caption
                    # A printed Figure label does not invalidate a real cell grid.
                    if kind!='table' or not data.get('table'):
                        data['caption']=None;flags.append('caption_label_mismatch')
                if not data['caption'] and 'caption_unknown' not in flags:
                    flags.append('caption_unknown')
            if kind == 'formula':
                data['math']=records.get(item.self_ref,{'verification':'unverified','check_status':'not_enriched','latex':text,'candidates':[]})
                if data['math'].get('refined_regions'):
                    data['raw_regions']=regions;regions=data['math']['refined_regions']
                flags.append('formula_content_unverified')
                if not text:
                    flags.append('formula_text_missing')
            if not regions:
                flags.append('unmapped')
            if kind in ('section_header', 'title'):
                heading_level = int(getattr(item, 'level', 1) or 1)
                prefix=re.match(r'^\s*(\d+(?:\.\d+)*)(?:\s|\.)',text)
                if prefix:
                    heading_level=len(prefix[1].split('.'))
                    data['heading_level_source']='explicit_number_prefix'
                if kind == 'title':
                    heading_level = 0
                while stack and stack[-1]['level'] >= heading_level:
                    stack.pop()
                parent=stack[-1]['id'] if stack else None
                if prefix and kind!='title':
                    parts=prefix[1].split('.')
                    ancestors=['.'.join(parts[:n]) for n in range(len(parts)-1,0,-1)]
                    parent=next((numbered_sections[p]['id'] for p in ancestors if p in numbered_sections),
                                next((s['id'] for s in sections if s['level']==0),None))
                section = {'id': f'{rid}:s{len(sections):05}', 'title': text,
                    'level': heading_level, 'parent_id': parent,
                    'reading_order': len(blocks), 'regions': regions}
                sections.append(section)
                if prefix and kind!='title':numbered_sections[prefix[1]]=section
                stack.append(section)
            block = make_block(rid, len(blocks), kind, text, regions, 'docling', flags, data,
                               stack[-1]['id'] if stack else None)
            if kind in ('table', 'picture', 'formula'):
                for n, r in enumerate(regions):
                    page = pdf[r['page_index']]
                    original_rotation = page.rotation
                    page.set_rotation(0)
                    w,h = page.rect.width,page.rect.height
                    x0,y0,x1,y1=r['bbox']
                    clip=fitz.Rect(x0*w,y0*h,x1*w,y1*h) & page.rect
                    if not clip.is_empty:
                        asset = f'b{len(blocks):06}-r{n}.png'
                        page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=clip).save(work/asset)
                        data['assets'].append(asset)
                    page.set_rotation(original_rotation)
            blocks.append(block)
    link_compound_figures(blocks)
    ref_map={b['data']['docling_ref']:b['id'] for b in blocks}
    for block in blocks:
        for ref in (block['data']['caption_refs'] if block['data']['caption'] else []):
            if ref in ref_map:
                block['data']['references'].append({'kind':'caption','target_block_id':ref_map[ref]})
        caption=block['data']['caption']
        if caption:
            label=re.match(r'(?i)((?:fig(?:ure)?\.?|table)\s*\d+)',caption.strip())
            if label:
                pattern=re.compile(re.escape(label[1]),re.I)
                for other in blocks:
                    if other['id']!=block['id'] and other['type'] not in ('caption','table','picture') and pattern.search(other['text']):
                        block['data']['references'].append({'kind':'text_reference_candidate','target_block_id':other['id']})
        if block['data']['references']:
            block['data']['reference_status']='extracted_candidates_unverified'
    unmapped=sum('unmapped' in b['quality_flags'] for b in blocks)
    if unmapped:
        warnings.append(f'{unmapped} 个块没有可靠来源区域。')
    warnings.append('结构、公式、表格内容与引用关系尚待质量核验；不能由解析成功推断识别完整。')
    if config.get('structure_refinement')=='r1':
        from .structure_refinement import refine_structure
        with fitz.open(path) as pdf:blocks,removed_sections=refine_structure(pdf,blocks,rid,session=session,report=report,work=work)
        sections=[s for s in sections if s['id'] not in removed_sections]
        for section in sections:
            if section['parent_id'] in removed_sections:section['parent_id']=removed_sections[section['parent_id']]
        by_section={b['section_id']:b for b in blocks if b['type'] in ('section_header','title')}
        current=None;byid={b['id']:b for b in blocks};section_ids={s['id'] for s in sections}
        for block in blocks:
            if block['type'] in ('section_header','title') and block['section_id'] in section_ids:current=block['section_id']
            elif block['data'].get('parent_block_id') in byid:block['section_id']=byid[block['data']['parent_block_id']]['section_id']
            else:block['section_id']=current
        for section in sections:
            if section['id'] in by_section:section['reading_order']=by_section[section['id']]['reading_order']
    return {'pages':pages,'sections':sections,'blocks':blocks,'warnings':warnings,
            'native_text':native,'raw_docling':doc.export_to_dict()}

def write_artifacts(output,work):
    (work/'structure.json').write_text(json.dumps(output,ensure_ascii=False),encoding='utf-8')
    markdown=[]
    for block in output['blocks']:
        if block['data'].get('parent_block_id'):continue
        markdown.append(('## ' if block['type'] in ('section_header','title') else '')+block['text'])
        if block['type']=='code' and block['data'].get('caption_block_id'):
            caption=next((b['text'] for b in output['blocks'] if b['id']==block['data']['caption_block_id']),'')
            markdown.insert(len(markdown)-1,caption)
        assets=block['data'].get('assets',[])+[a for b in output['blocks'] if b['id'] in block['data'].get('children',[]) for a in b['data'].get('assets',[])]
        for asset in dict.fromkeys(assets):markdown.append(f'![source region](assets/{asset})')
    (work/'document.md').write_text('\n\n'.join(markdown),encoding='utf-8')


def execute_parse(job, worker, report, converter=None):
    rid=job['payload']['parse_run_id']
    run=parsing.get_run(rid)
    if run is None:
        raise parsing.ParseFailure('解析运行不存在')
    parsing.mark_running(rid,job['id'],worker)
    if run['config_version'] != parsing.CONFIG_VERSION:
        raise parsing.ParseFailure('结构映射配置版本已变化，请创建新的解析运行')
    if parsing.parser_version(run['parser']) != run['parser_version']:
        raise parsing.ParseFailure('解析器版本已变化，请创建新的解析运行以保持版本绑定')
    if run['parser']=='docling' and run['config'].get('model_manifest_sha256')!=parsing.model_manifest_hash():
        raise parsing.ParseFailure('模型清单已变化，请创建新的解析运行以保持版本绑定')
    if run['parser']=='docling' and run['config'].get('adapter_sha256')!=parsing.adapter_hash():
        raise parsing.ParseFailure('解析适配器已变化，请创建新的解析运行')
    if run['parser']=='docling' and run['config']['formulas'] and run['config'].get('math_manifest_sha256')!=parsing.math_manifest_hash():
        raise parsing.ParseFailure('数学增强清单已变化，请创建新的解析运行')
    descriptor=run['config'].get('source',{})
    if descriptor.get('status')=='available':
        if descriptor.get('pdf_sha256')!=run['file_sha256']:raise parsing.ParseFailure('源文件绑定的PDF哈希不匹配')
        archive=file_path(descriptor['archive_path'])
        if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest()!=descriptor['archive_sha256']:
            raise parsing.ParseFailure('源文件哈希已变化，请重新获取并创建新运行')
    with engine.connect() as conn:
        file=conn.execute(select(paper_files).where(paper_files.c.id==run['paper_file_id'])).mappings().one()
    source=file_path(file['relative_path'])
    with source.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=run['file_sha256']:
            raise parsing.ParseFailure('PDF 哈希与解析输入不一致，拒绝解析')
    attempt=uid()
    rel=f"parses/{rid}/{attempt}"
    work=file_path(rel)
    work.mkdir(parents=True)
    started=time.monotonic()
    published=False
    try:
        report({'stage':'extract','message':f"正在执行 {run['parser']} 结构解析"})
        if run['parser']=='docling' and converter is None:
            from .parse_subprocess import run_conversion
            limit=run['config'].get('wall_timeout_seconds',float(os.getenv('PAPERMIND_PARSE_TIMEOUT_SECONDS','1200')))
            run_conversion({'source':str(source),'rid':rid,'config':run['config'],
                'work':str(work),'file_sha256':run['file_sha256']},report,timeout=limit)
            output=json.loads((work/'structure.json').read_text(encoding='utf-8'))
            if time.monotonic()-started>=limit:raise parsing.ParseFailure('解析全流程硬超时，旧成功结果保留')
            if output.get('parse_run_id')!=rid or output.get('file_sha256')!=run['file_sha256']:
                raise parsing.ParseFailure('解析子进程输出身份不匹配，拒绝发布')
            if not (work/'document.md').is_file():raise parsing.ParseFailure('解析产物不完整，拒绝发布')
        else:
            output=(converter or native_parse)(source,rid,run['config'],work,report)
            output.update(file_sha256=run['file_sha256'],parse_run_id=rid)
            write_artifacts(output,work)
        report({'stage':'publishing','message':'完整产物已生成，正在校验租约并发布'})
        if run['parser']=='docling' and run['config'].get('adapter_sha256')!=parsing.adapter_hash():
            raise parsing.ParseFailure('执行期间解析适配器发生变化，拒绝发布，请新建运行')
        parsing.publish(rid,job['id'],worker,output,rel,time.monotonic()-started)
        published=True
    finally:
        if not published:
            # Only this internally generated attempt directory; never source or old run.
            shutil.rmtree(work)
