"""Prefetch only models used by this CPU parser into project storage."""
import logging
import json
import hashlib
from backend import parse_pipeline
from docling.utils.model_downloader import download_models

logging.basicConfig(level=logging.INFO)
if __name__=='__main__':
    print('Downloading Docling layout, table and formula models into project storage',flush=True)
    path=download_models(with_layout=True,with_tableformer=True,with_code_formula=True,
        with_picture_classifier=False,with_rapidocr=False,progress=True)
    manifest=[]
    for folder in sorted(path.iterdir()):
        if not folder.is_dir():continue
        files=[]
        for file in sorted(folder.rglob('*')):
            if not file.is_file() or '.cache' in file.relative_to(folder).parts:continue
            with file.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            files.append({'path':file.relative_to(folder).as_posix(),'sha256':digest,'size':file.stat().st_size})
        manifest.append({'model_folder':folder.name,'files':files})
    (path.parent/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Models ready:',path,flush=True)
