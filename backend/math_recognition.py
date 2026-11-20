"""Bounded local math inference with immutable candidates; checks are not truth labels."""
import re
import time
from collections import Counter
from PIL import ImageOps


def latex_checks(text):
    flags=[]
    if not text.strip():flags.append('empty')
    if text.count('{')!=text.count('}'):flags.append('unbalanced_braces')
    if any(ord(c)<32 and c not in '\n\t\r' for c in text):flags.append('control_character')
    words=text.split()
    if len(words)>80:
        grams=[tuple(words[n:n+12]) for n in range(len(words)-11)]
        if grams and max(Counter(grams).values())>=4:flags.append('long_repetition')
    return flags


def normalize_latex(raw):
    # Only whitespace/control normalization. Never insert math from an expected answer.
    return re.sub(r'[ \t]+',' ',raw.replace('\r\n','\n')).strip()


class MathRecognizer:
    def __init__(self,model,config):self.model=model;self.config=config
    def recognize(self,image,*,label='formula',retry=True):
        model=self.model;attempts=[]
        for n in range(2 if retry else 1):
            candidate=image if n==0 else ImageOps.expand(image.resize((round(image.width*1.25),round(image.height*1.25))),border=10,fill='white')
            inputs=model._processor(text=[model._get_prompt(label)],images=[candidate],return_tensors='pt').to(model.device)
            start=time.monotonic()
            tokens=model._model.generate(**inputs,max_new_tokens=self.config.get('formula_max_new_tokens',1536),
                max_time=self.config.get('formula_max_seconds',45),use_cache=True,do_sample=False)
            output=tokens[:,inputs.input_ids.shape[1]:]
            raw=model._processor.batch_decode(output,skip_special_tokens=False)[0]
            normalized=normalize_latex(model._post_process([raw])[0])
            checks=latex_checks(normalized)
            eos=model._model.generation_config.eos_token_id
            if int(output[0,-1]) not in (eos if isinstance(eos,list) else [eos]):checks.append('generation_limit_reached')
            attempts.append({'raw':raw,'normalized_latex':normalized,'checks':checks,
                'elapsed_seconds':round(time.monotonic()-start,3),'image_variant':'original' if n==0 else 'upscaled_white_padding'})
            if not checks:break
        selected=min(range(len(attempts)),key=lambda k:len(attempts[k]['checks']))
        return {'candidates':attempts,'selected_candidate':selected,'latex':attempts[selected]['normalized_latex'],
            'check_status':'needs_review' if attempts[selected]['checks'] else 'syntax_checks_only',
            'verification':'unverified','source':'CodeFormulaV2','inference_config':{
                'max_new_tokens':self.config.get('formula_max_new_tokens',1536),'max_seconds':self.config.get('formula_max_seconds',45),'batch_size':1}}
