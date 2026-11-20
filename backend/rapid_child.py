"""Isolated optional OCR runtime. Explicit local models, no automatic downloads."""
import importlib.metadata
import json
from pathlib import Path
import sys
import traceback


def main():
    request=json.loads(sys.stdin.buffer.readline())
    root=Path(request['model_root'])
    from rapid_latex_ocr import LaTeXOCR
    model=LaTeXOCR(image_resizer_path=root/'image_resizer.onnx',encoder_path=root/'encoder.onnx',
        decoder_path=root/'decoder.onnx',tokenizer_json=root/'tokenizer.json')
    names=['rapid-latex-ocr','numpy','onnxruntime','pillow','opencv-python','tokenizers']
    versions={n:importlib.metadata.version(n) for n in names}
    print(json.dumps({'event':'ready','version':versions['rapid-latex-ocr'],'runtime_packages':versions}),flush=True)
    for line in sys.stdin.buffer:
        command=json.loads(line)
        try:
            import numpy as np
            np.random.seed(0)
            text,elapsed=model(command['image'])
            print(json.dumps({'event':'result','raw':text,'elapsed_seconds':elapsed}),flush=True)
        except Exception:
            traceback.print_exc();print(json.dumps({'event':'failure'}),flush=True)

if __name__=='__main__':main()
