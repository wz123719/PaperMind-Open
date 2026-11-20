"""Isolated whole-crop equation inference, with no layout detector recropping."""
import json,sys,os
from pathlib import Path
from importlib.metadata import version
from PIL import Image
from mineru.model.vlm.runtime import ModelSingleton,shutdown_cached_models

def main():
    if version('mineru')!='4.2.1':raise RuntimeError('MinerU runtime version mismatch')
    lock=Path(os.environ['MINERU_HOME']).resolve().parent/'mineru-runtime-lock.txt'
    for line in lock.read_text(encoding='utf-8').splitlines():
        if '==' not in line or line.startswith('#'):continue
        name,expected=line.split('==',1)
        if version(name)!=expected:raise RuntimeError('MinerU dependency mismatch: '+name)
    # The parent owns the wall deadline and Windows Job. Only installed local
    # GGUF models are used; no document instructions or TeX are executed.
    handle=ModelSingleton().get_model('llama-cpp-engine',None,None,n_threads=2)
    try:
        with Image.open(sys.argv[1]) as image:
            raw=handle.predictor.content_extract(image.convert('RGB'),type='equation')
        if not isinstance(raw,str) or not raw.strip():raise RuntimeError('Empty equation candidate')
        Path(sys.argv[2]).write_text(json.dumps({'producer':'MinerU-4.2.1','route':'whole_crop_equation',
            'latex':str(raw),'runtime_version':version('mineru')},ensure_ascii=False),encoding='utf-8')
    finally:shutdown_cached_models()

if __name__=='__main__':main()
