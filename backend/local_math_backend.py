"""PDF mathematical layout enhancement with independently retained local OCR evidence."""
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid
from .db import STORAGE,ROOT
from .parsing import ParseFailure
from .process_guard import start_owned,stop_owned
from .math_recognition import latex_checks,normalize_latex
from .native_math import layout_latex,horizontal_bars


def runtime_paths():
    root=STORAGE/'evaluation'
    python=root/'latex-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    return python,root/'rapid-models'


class RapidSession:
    def __init__(self,work,config=None,source_path=None):
        from .object_cache import ObjectCache
        self.config=config or {};self.source_path=source_path
        source_hash=hashlib.sha256(Path(source_path).read_bytes()).hexdigest() if source_path else None
        self.cache=ObjectCache({'pdf_sha256':source_hash,'config':self.config,'component':'object-router-2'})
        self.work=Path(work);self.events=queue.Queue();self.closed=False;self.proc=None;self.route_events=[]
        self.mineru_validated=False
    def recognize_alternative(self,image):
        from .mineru_math import validate,recognize
        if not self.mineru_validated:
            validate(self.config.get('mineru_math_manifest_sha256'));self.mineru_validated=True
        return recognize(image,self.work,120)
    def start(self):
        if self.proc is not None:return
        python,models=runtime_paths()
        manifest=models/'manifest.json'
        if not python.is_file() or not manifest.is_file():raise ParseFailure('独立数学增强运行环境或模型未准备；请执行setup-math.py。未自动关闭公式。')
        declared=json.loads(manifest.read_text(encoding='utf-8'))
        for item in declared['files']:
            path=models/item['file']
            if not path.is_file():raise ParseFailure('数学增强模型缺失，拒绝解析')
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            if digest!=item['sha256']:raise ParseFailure('数学增强模型哈希不匹配，拒绝解析')
        self.proc,self.group=start_owned([str(python),'-u','-m','backend.rapid_child'],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=None,
            env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1'})
        def read():
            for line in self.proc.stdout:
                try:self.events.put(json.loads(line))
                except (ValueError,UnicodeError):pass
            self.events.put({'event':'closed'})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        try:
            self.send({'model_root':str(models)})
            ready=self.receive(60)
            if ready.get('event')!='ready' or ready.get('version')!='0.0.9':raise ParseFailure('数学识别组件版本与配置不一致')
            if ready.get('runtime_packages')!=declared['runtime_packages']:raise ParseFailure('独立数学运行环境依赖与清单不一致')
        except BaseException:self.close();raise
    def send(self,value):
        self.proc.stdin.write((json.dumps(value)+'\n').encode('utf-8'));self.proc.stdin.flush()
    def receive(self,timeout):
        try:
            event=self.events.get(timeout=timeout)
            if event.get('event')=='closed':raise ParseFailure('独立数学识别子进程提前退出，请查看本地Worker日志')
            return event
        except queue.Empty:raise ParseFailure('局部数学图像识别超时；子进程将终止，旧结果保留')
    def recognize(self,image):
        self.start()
        image_path=self.work/('_math-input-'+uuid.uuid4().hex+'.png');image.save(image_path)
        try:
            self.send({'image':str(image_path)})
            result=self.receive(60)
            if result.get('event')!='result':raise ParseFailure('局部数学图像识别失败')
            raw=result['raw'];text=normalize_latex(raw)
            return {'source':'RapidLaTeXOCR-0.0.9','raw':raw,'normalized_latex':text,
                'elapsed_seconds':round(result['elapsed_seconds'],4),'checks':latex_checks(text)}
        finally:image_path.unlink(missing_ok=True)
    def close(self):
        if self.closed:return
        self.closed=True
        if self.proc is None:return
        stop_owned(self.proc,self.group)
        if self.proc.stdin:self.proc.stdin.close()
        self.reader.join(timeout=3)
        if self.proc.stdout:self.proc.stdout.close()


def recognize_region(page,localized,session,parts=()):
    import io
    from .math_structure import math_tree
    image_bytes=io.BytesIO();localized['image'].save(image_bytes,format='PNG')
    features={'page_index':page.number,'bbox':localized['bbox'],'image_sha256':hashlib.sha256(image_bytes.getvalue()).hexdigest(),
              'component':'math-object-router-5','budget':{'image_calls':2,'mineru_seconds':120,'rapid_seconds':60}}
    cached=session.cache.get(features)
    if cached is not None:
        session.route_events.append({'type':'cache_hit','page_index':page.number,'bbox':localized['bbox']});return cached
    candidates=[]
    cs=localized['glyphs'];bars=horizontal_bars(page,__import__('pymupdf').Rect(localized['bbox']))
    native=layout_latex(cs,bars)
    checks=latex_checks(native)
    from .math_layout_checks import layout_checks
    checks+=layout_checks(cs,bars,native)
    unknown=[c for c in cs if (ord(c['c'])<32 or '\ue000'<=c['c']<='\uf8ff') and c['token']==c['c'] and c['c'].strip()]
    if unknown:checks.append('unmapped_pdf_glyph')
    from .native_math import decorations
    if decorations(cs)[1]:checks.append('unresolved_math_decoration')
    # Extensible TeX font pieces may carry printable ASCII codes (e.g. root
    # segments encoded as v/u/t). Printable text is not evidence of a mapping.
    if any(c['font'].startswith('CMEX') and not c.get('glyph') for c in cs):checks.append('unmapped_extensible_math_glyph')
    if any(c['glyph'].startswith(('bracketlefttp','bracketleftbt','bracketleftex','bracketrighttp','bracketrightbt','bracketrightex')) for c in cs):checks.append('matrix_layout_requires_review')
    native_candidate={'source':'pdf_glyph_rule_layout','raw':''.join(c['c'] for c in cs),
        'normalized_latex':native,'checks':checks,'glyphs':cs,'rule_segments':[list(b) for b in bars]}
    candidates.append(native_candidate)
    from .source_adapter import match_math
    source_candidate=match_math(getattr(session,'source_document',None),native,page,localized['bbox'],native_checks=checks)
    if source_candidate:candidates.append(source_candidate)
    supported=not checks and sum(c['font'].startswith(('CM','MSAM','MSBM')) for c in cs)>=3
    route_events=[{'route':'pdf_glyph_rule_layout','status':'supported' if supported else 'unsupported',
                   'reason':'mapped_math_fonts_and_rules' if supported else checks or ['insufficient_math_font_evidence']}]
    source_selected=source_candidate is not None and not source_candidate['checks']
    if source_selected:
        selected=len(candidates)-1;route_events.insert(0,{'route':'restricted_tex','status':'candidate_aligned','source_object_id':source_candidate['source_object_id']})
    elif supported:selected=0
    else:
        try:
            ocr=None
            if getattr(session,'config',{}).get('mineru_math_manifest_sha256'):
                try:
                    alternative=session.recognize_alternative(localized['image'])
                    candidates.append(alternative)
                    if not alternative['checks']:ocr=alternative
                    route_events.append({'route':'MinerU-4.2.1-standard-local','status':'completed_candidate',
                        'seconds':alternative['elapsed_seconds'],'checks':alternative['checks']})
                except ParseFailure as exc:
                    route_events.append({'route':'MinerU-4.2.1-standard-local','status':'failed','reason':str(exc)})
                    session.cache.record({'type':'route_failed','route':'mineru','input':features,'reason':str(exc)})
            if ocr is None:
                ocr=session.recognize(localized['image']);candidates.append(ocr)
                route_events.append({'route':'RapidLaTeXOCR-0.0.9','status':'completed','seconds':ocr['elapsed_seconds']})
            selected=len(candidates)-1
        except ParseFailure as exc:
            session.route_events.append({'type':'route_failed','page_index':page.number,'bbox':localized['bbox'],'reason':str(exc)})
            session.cache.record({'type':'route_failed','input':features,'reason':str(exc)})
            # Successful earlier objects stay private and can be reused on queue retry.
            raise
    chosen=candidates[selected]
    result={'source':chosen['source'],'latex':chosen['normalized_latex'],'candidates':candidates,
        'selected_candidate':selected,'check_status':'needs_review' if chosen['checks'] else 'syntax_checks_only',
        'verification':'unverified','selection_reason':'exact_version_source_unique_alignment' if source_selected else 'mapped_pdf_glyphs_and_rules' if supported else 'unsupported_pdf_layout_use_image_candidate',
        'route_history':route_events,'math_structure':math_tree(chosen['normalized_latex']),
        'crop_checks':{'source_bbox':localized['bbox'],'image_size':list(localized['image'].size),'partition_candidates':len(parts),
                       'evidence':localized.get('crop_evidence',{})}}
    session.cache.put(features,result);session.route_events+=route_events
    return result
