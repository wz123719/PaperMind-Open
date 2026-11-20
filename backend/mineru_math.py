"""Bounded local MinerU math fallback; does not replace layout/table defaults."""
import json,os,subprocess,time,uuid,hashlib
from pathlib import Path
from .db import STORAGE,ROOT
from .files import file_path
from .parsing import ParseFailure
from .process_guard import start_owned,stop_owned
from .math_recognition import latex_checks,normalize_latex

def manifest_hash():
    path=STORAGE/'evaluation/mineru-math-manifest.json'
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

def validate(expected):
    manifest=STORAGE/'evaluation/mineru-math-manifest.json'
    if not expected or manifest_hash()!=expected:raise ParseFailure('MinerU数学模型清单与提交指纹不一致')
    declared=json.loads(manifest.read_text(encoding='utf-8'))
    if declared.get('package')!='4.2.1' or not declared.get('files'):raise ParseFailure('MinerU模型清单无效')
    lock=STORAGE/'evaluation/mineru-runtime-lock.txt'
    if not lock.is_file() or hashlib.sha256(lock.read_bytes()).hexdigest()!=declared['runtime_lock_sha256']:
        raise ParseFailure('MinerU隔离运行环境清单与指纹不一致')
    for item in declared['files']:
        path=file_path(item['path'])
        if not path.is_file():raise ParseFailure('MinerU模型缺失')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=item['sha256']:raise ParseFailure('MinerU模型哈希与指纹不一致')

def recognize(image,work,limit=120):
    manifest=STORAGE/'evaluation/mineru-math-manifest.json'
    executable=STORAGE/'evaluation/mineru-env/Scripts/python.exe'
    if not manifest.exists() or not executable.exists():raise ParseFailure('受限MinerU数学备选未准备')
    uid=uuid.uuid4().hex;folder=Path(work)/('_mineru-'+uid);folder.mkdir()
    source=folder/'input.png';image.save(source);output=folder/'result.json';log=folder/'runtime.log'
    env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONUNBUFFERED':'1','MINERU_HOME':str(STORAGE/'evaluation/mineru-models'),
         'MINERU_MODEL_SOURCE':'local','HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_XET':'1','OMP_NUM_THREADS':'2'}
    command=[str(executable),'-u','-m','backend.mineru_math_child',str(source.resolve()),str(output.resolve())]
    start=time.monotonic()
    with log.open('w',encoding='utf-8') as stream:
        proc,job=start_owned(command,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
        try:
            try:proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:raise ParseFailure('MinerU局部数学识别超过对象预算')
            if proc.returncode!=0 or not output.is_file():raise ParseFailure('MinerU局部数学识别失败，原始日志已保留')
        finally:stop_owned(proc,job)
    raw=json.loads(output.read_text(encoding='utf-8'));latex=raw.get('latex')
    if not isinstance(latex,str) or not latex.strip():raise ParseFailure('MinerU未返回独立数学表达式')
    latex=normalize_latex(latex)
    return {'source':'MinerU-4.2.1-standard-local','raw':raw,'normalized_latex':latex,'checks':latex_checks(latex),
            'elapsed_seconds':round(time.monotonic()-start,3),'budget_seconds':limit,'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'verification':'unverified','model_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
