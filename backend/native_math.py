"""PDF glyph/position evidence. No paper identifiers or expected expressions."""
import re
import statistics
import unicodedata
from collections import defaultdict
import pymupdf as fitz
ADOBE_PUA={'bracketlefttp':'\uf8ee','bracketleftex':'\uf8ef','bracketleftbt':'\uf8f0',
    'bracketrighttp':'\uf8f9','bracketrightex':'\uf8fa','bracketrightbt':'\uf8fb'}
CMEX_ENCODING={0:'parenleftbig',1:'parenrightbig',16:'parenleftBig',17:'parenrightBig',
    18:'parenleftbigg',19:'parenrightbigg',20:'bracketleftbigg',21:'bracketrightbigg',
    32:'parenleftBigg',33:'parenrightBigg',34:'bracketleftBigg',35:'bracketrightBigg',
    80:'summationtext',88:'summationdisplay',98:'hatwide',112:'radicalbig',113:'radicalBig',115:'radicalBigg'}

GLYPHS={'summationdisplay':r'\sum','summationtext':r'\sum','productdisplay':r'\prod',
    'producttext':r'\prod','hatwide':r'\widehat','tildewide':r'\widetilde'}
UNICODE={'α':r'\alpha','β':r'\beta','γ':r'\gamma','θ':r'\theta','Θ':r'\Theta','ϵ':r'\epsilon',
    'ε':r'\varepsilon','Φ':r'\Phi','φ':r'\phi','∆':r'\Delta','Δ':r'\Delta','λ':r'\lambda',
    '∈':r'\in','∇':r'\nabla','∞':r'\infty','≤':r'\le','≥':r'\ge','−':'-',
    '·':r'\cdot','×':r'\times','←':r'\leftarrow','→':r'\rightarrow','∑':r'\sum','√':r'\sqrt',
    '∥':r'\Vert','‖':r'\Vert','{':r'\{','}':r'\}','⊙':r'\odot'}
UNICODE.update({'δ':r'\delta','ζ':r'\zeta','η':r'\eta','ι':r'\iota','κ':r'\kappa','μ':r'\mu',
    'ν':r'\nu','ξ':r'\xi','π':r'\pi','ρ':r'\rho','σ':r'\sigma','τ':r'\tau','υ':r'\upsilon',
    'χ':r'\chi','ψ':r'\psi','ω':r'\omega','φ':r'\varphi','ϕ':r'\phi'})
UNICODE.update({'Γ':r'\Gamma','Λ':r'\Lambda','Ξ':r'\Xi','Π':r'\Pi','Σ':r'\Sigma','Υ':r'\Upsilon',
    'Ψ':r'\Psi','Ω':r'\Omega','ϑ':r'\vartheta','ϱ':r'\varrho','ς':r'\varsigma','⊤':r'\top'})
UNICODE.update({'¯':r'\bar','\u0304':r'\bar','ˆ':r'\hat','\u0302':r'\hat'})
UNICODE.update({'ℓ':r'\ell','ǫ':r'\epsilon'})
UNICODE.update({'≡':r'\equiv','∪':r'\cup'})
# Adobe ITC Zapf Dingbats glyph names (not character-code substitutions).
# https://github.com/adobe-type-tools/agl-aglfn/blob/master/zapfdingbats.txt
DINGBATS={'a19':'✓','a20':'✔','a21':'✕','a22':'✖','a23':'✗','a24':'✘'}

def type1_encoding(data):
    """Read only literal cleartext encoding entries; never execute PostScript."""
    prefix=data[:65536].split(b'currentfile eexec',1)[0]
    return {int(n):name.decode('ascii') for n,name in re.findall(rb'\bdup\s+(\d{1,3})\s+/([A-Za-z0-9_.]+)\s+put\b',prefix) if int(n)<256}


def font_encodings(page):
    result={}
    for xref,ext,kind,name,*_ in page.get_fonts():
        font=name.split('+')[-1]
        try:
            typ,value=page.parent.xref_get_key(xref,'Encoding')
            text=page.parent.xref_object(int(value.split()[0])) if typ=='xref' else value
            match=re.search(r'/Differences\s*\[([^]]*)\]',text,re.S)
            mapping={};code=0
            if match:
                for token in re.findall(r'\d+|/[^\s\[\]]+',match[1]):
                    if token.startswith('/'):mapping[code]=token[1:];code+=1
                    else:code=int(token)
            for glyph in list(mapping.values()):
                unicode=ADOBE_PUA.get(glyph,'')
                if len(unicode)==1:mapping.setdefault(ord(unicode),glyph)
            if not mapping and 'dingbat' in font.lower():
                _,extension,kind,data=page.parent.extract_font(xref)
                if extension=='pfa' and kind=='Type1':mapping=type1_encoding(data)
            if 'dingbat' in font.lower():
                # With no ToUnicode, MuPDF can expose glyph a19 as U+0013.
                # Alias only glyph names proven by this embedded encoding.
                for name in list(mapping.values()):
                    if name in DINGBATS:mapping.setdefault(int(name[1:]),name)
            result[font]={**(CMEX_ENCODING if font.startswith('CMEX') else {}),**mapping}
        except (ValueError,RuntimeError):result[font]={}
    return result


def characters(page,clip):
    enc=font_encodings(page);result=[];line_id=0;span_id=0
    for block in page.get_text('rawdict',clip=clip)['blocks']:
        if block['type']!=0:continue
        for line in block['lines']:
            for span in line['spans']:
                for char in span['chars']:
                    c=char['c'];glyph=enc.get(span['font'],{}).get(ord(c),'') if len(c)==1 else ''
                    if not glyph and span['font'].startswith('CMEX'):
                        glyph=next((k for k,v in ADOBE_PUA.items() if c==v),'')
                    canonical=unicodedata.normalize('NFKC',c)
                    token=GLYPHS.get(glyph,UNICODE.get(c,UNICODE.get(canonical,canonical)))
                    if span['font'].startswith('CMSY') and len(c)==1 and 'A'<=c<='Z':token=r'\mathcal{'+c+'}'
                    if span['font'].startswith('MSBM') and len(c)==1 and 'A'<=c<='Z':token=r'\mathbb{'+c+'}'
                    if glyph.startswith('parenleft'):token='('
                    if glyph.startswith('parenright'):token=')'
                    if glyph.startswith('bracketleft'):token='['
                    if glyph.startswith('bracketright'):token=']'
                    if glyph.startswith('radical'):token=r'\sqrt'
                    if 'dingbat' in span['font'].lower() and glyph in DINGBATS:token=DINGBATS[glyph]
                    result.append({'c':c,'token':token,'glyph':glyph,'font':span['font'],'size':span['size'],
                        'origin':list(char['origin']),'bbox':list(char['bbox']),'line':line_id,'span':span_id,
                        'span_text':''.join(x['c'] for x in span['chars']),
                        'pdf_encoding_code':next((code for code,name in enc.get(span['font'],{}).items() if name==glyph and code>=32),None)
                            if 'dingbat' in span['font'].lower() else None})
                span_id+=1
            line_id+=1
    return result


def bounds(chars):
    return [min(c['bbox'][0] for c in chars),min(c['bbox'][1] for c in chars),
        max(c['bbox'][2] for c in chars),max(c['bbox'][3] for c in chars)]


def group_lines(chars):
    if not chars:return []
    base=statistics.median(c['size'] for c in chars if c['c'].strip())
    native=defaultdict(list)
    for c in chars:native[c['line']].append(c)
    groups=[]
    for line in native.values():
        anchors=[c['origin'][1] for c in line if c['size']>=base*.88 and c['token'] not in (r'\sqrt',r'\widehat',r'\widetilde')]
        if not anchors:continue
        y=statistics.median(anchors)
        existing=next((g for g in groups if abs(g['baseline']-y)<base*.22),None)
        if existing:existing['chars']+=line
        else:groups.append({'baseline':y,'chars':list(line)})
    used={id(c) for g in groups for c in g['chars']}
    for line in native.values():
        extra=[c for c in line if id(c) not in used]
        if extra and groups:
            g=min(groups,key=lambda g:abs(g['baseline']-statistics.median(c['origin'][1] for c in extra)))
            g['chars']+=extra
    return sorted(groups,key=lambda g:g['baseline'])


def latex(chars,*,base=None,bars=()):
    chars=[dict(c) for c in chars if c['c'].strip()]
    if not chars:return ''
    index=0
    while index<len(chars):
        end=index
        while (end<len(chars) and len(chars[end]['c'])==1 and chars[end]['c'].isascii()
               and chars[end]['c'].isalpha() and chars[end]['token']==chars[end]['c']
               and (end==index or abs(chars[end]['origin'][1]-chars[index]['origin'][1])<.5)):end+=1
        group=chars[index:end]
        word=''.join(c['c'] for c in group)
        named=word in ('argmin','argmax','max','min','log','exp','lim')
        function=(end<len(chars) and chars[end]['token'] in ('(','[') and abs(chars[end]['origin'][1]-chars[index]['origin'][1])<.5
                  and not any(c['font'].startswith(('CMMI','CMSY','CMEX')) for c in group))
        if len(group)>1 and (named or function):
            word=''.join(c['c'] for c in group);atom=dict(group[0])
            token=(r'\arg \min' if word=='argmin' else r'\arg \max' if word=='argmax' else '\\'+word if named else r'\operatorname{'+word+'}')
            atom.update(c='◊',token=token,bbox=bounds(group),span=-200-index)
            chars[index:end]=[atom];index+=1
        else:index=max(index+1,end)
    atoms=defaultdict(list)
    for c in chars:
        word=c.get('span_text','').strip()
        if word in ('max','min','log','exp','lim') or (len(word)>1 and word.isdigit()) or (
            re.fullmatch(r'[A-Za-z]{2,}',word) and not c['font'].startswith(('CMMI','CMSY','CMEX'))):
            atoms[c.get('span',-1)].append(c)
    for group in atoms.values():
        word=group[0]['span_text'].strip()
        token=('\\'+word) if word in ('max','min','log','exp','lim') else (word if word.isdigit() else r'\mathrm{'+word+'}')
        atom=dict(group[0]);atom.update(c=word,token=token,bbox=bounds(group))
        chars=[c for c in chars if all(c is not x for x in group)]+[atom]
    for root in [c for c in chars if c['token']==r'\sqrt']:
        choices=[b for b in bars if abs(b.x0-root['bbox'][2])<3 and root['bbox'][1]-1<=b.y0<=root['bbox'][3]]
        if choices:
            bar=min(choices,key=lambda b:abs(b.x0-root['bbox'][2]))
            inner=[c for c in chars if c is not root and bar.x0-.5<=c['bbox'][0] and c['bbox'][2]<=bar.x1+1]
            if inner:
                root['token']=r'\sqrt{'+latex(inner)+'}'
                root['c']='◊'
                anchors=[c['origin'][1] for c in inner if c['size']>=root['size']*.85]
                if anchors:root['origin']=[root['origin'][0],statistics.median(anchors)]
                chars=[c for c in chars if all(c is not x for x in inner)]
    if base is None:base=max(c['size'] for c in chars if c['token'] not in (r'\sum',r'\widehat',r'\widetilde'))
    main=[c for c in chars if c['size']>=base*.86]
    small=[c for c in chars if c['size']<base*.86]
    baselines=defaultdict(int)
    for c in main:
        if c['c'].isalnum() and c['token'] not in (r'\sum',r'\prod'):baselines[round(c['origin'][1]*2)/2]+=1
    if baselines:
        primary=max(baselines,key=baselines.get)
        shifted=[c for c in main if c['c'].isalnum() and c['token'] not in (r'\sum',r'\prod')
            and abs(c['origin'][1]-primary)>max(.75,base*.12) and c['size']<=base*1.01]
        main=[c for c in main if c not in shifted];small+=shifted
    accents=[c for c in main if c['token'] in (r'\widehat',r'\widetilde')]
    main=[c for c in main if c not in accents]
    for accent in accents:
        choices=[c for c in main if min(c['bbox'][2],accent['bbox'][2])>max(c['bbox'][0],accent['bbox'][0])]
        if choices:
            anchor=min(choices,key=lambda c:abs((c['bbox'][0]+c['bbox'][2])-(accent['bbox'][0]+accent['bbox'][2])))
            anchor['token']=accent['token']+'{'+anchor['token']+'}'
    for c in main:c['sub']=[];c['sup']=[]
    # Whole native limit lines associate by their center with a sum/product.
    limits=defaultdict(list)
    for c in small:limits[c['line']].append(c)
    attached=set()
    for line in limits.values():
        if any(c['line']==line[0]['line'] for c in main):continue
        bb=bounds(line);center=(bb[0]+bb[2])/2
        operators=[c for c in main if c['token'] in (r'\sum',r'\prod',r'\max',r'\min',r'\lim') and abs(center-(c['bbox'][0]+c['bbox'][2])/2)<base*1.5]
        if operators:
            anchor=min(operators,key=lambda c:abs(center-(c['bbox'][0]+c['bbox'][2])/2))
            key='sub' if statistics.median(c['origin'][1] for c in line)>anchor['origin'][1] else 'sup'
            anchor[key]+=line;attached.update(id(c) for c in line)
    script_owners={}
    for c in sorted(small,key=lambda c:-c['size']):
        if id(c) in attached:continue
        # A script of a script belongs to that operand, even when its baseline
        # crosses the main expression baseline (e.g. F_{gamma^(k),beta^(k)}).
        nested=[s for s in small if id(s) in script_owners and s['size']>c['size']*1.15
                and s['bbox'][0]<=c['bbox'][0]+.5 and abs(c['bbox'][0]-s['bbox'][2])<base*1.2
                and abs(c['origin'][1]-s['origin'][1])<base]
        if nested:
            s=min(nested,key=lambda s:abs(c['bbox'][0]-s['bbox'][2]))
            anchor,key=script_owners[id(s)];anchor[key].append(c);script_owners[id(c)]=(anchor,key);continue
        choices=[b for b in main if b['bbox'][0]<=c['bbox'][0]+.8 and b['token'] not in (r'\leftarrow',r'\cdot','+','-','=','(',',')]
        if not choices:choices=main
        if not choices:continue
        anchor=min(choices,key=lambda b:abs(c['bbox'][0]-b['bbox'][2]))
        key='sub' if c['origin'][1]>anchor['origin'][1]+.5 else 'sup'
        anchor[key].append(c)
        script_owners[id(c)]=(anchor,key)
    parts=[];previous=None
    for c in sorted(main,key=lambda c:c['bbox'][0]):
        token=c['token']
        transpose=[x for x in c['sup'] if x['token']==r'\top']
        upper=[x for x in c['sup'] if x['token']!=r'\top']
        for group,symbol in [(c['sub'],'_'),(upper,'^')]:
            if group:token+=symbol+'{'+latex(group,base=max(x['size'] for x in group))+'}'
        if transpose:
            token=(r'\left('+token+r'\right)' if upper else token)+r'^{\top}'
        if previous and c['bbox'][0]-previous['bbox'][2]>base*1.5 and abs(c['origin'][1]-previous['origin'][1])<base*.3:parts.append(r'\qquad')
        parts.append(token);previous=c
    result=' '.join(parts)
    for operator in ('max','min','log','exp','lim'):
        pattern=r'(?<![A-Za-z\\])'+r'\s+'.join(operator)+r'(?![A-Za-z])'
        result=re.sub(pattern,lambda _: '\\'+operator,result)
    return result


def is_math(c):
    return bool(re.match(r'^(CM|MSAM|MSBM|STIX|Math)',c['font']))


def formatted_line(chars,bars=()):
    segments=[];current=[];kind=None
    for c in sorted(chars,key=lambda c:c['bbox'][0]):
        new='math' if is_math(c) else 'text'
        if kind and kind!=new:
            segments.append({'type':kind,'text':latex(current,bars=bars) if kind=='math' else ''.join(x['token'] for x in current),'glyphs':current})
            current=[]
        kind=new;current.append(c)
    if current:segments.append({'type':kind,'text':latex(current,bars=bars) if kind=='math' else ''.join(x['token'] for x in current),'glyphs':current})
    return segments


def horizontal_bars(page,clip):
    from .pdf_rules import rule_segments
    return [fitz.Rect(r['bbox']) for r in rule_segments(page,clip) if r['axis']=='horizontal']


def layout_latex(chars,bars,depth=0):
    """Fraction/radical graph from actual rules, then scripts and sum limits."""
    if not chars:return ''
    if depth>6:return latex(chars,bars=bars)
    chars,_=decorations(chars)
    roots=[c for c in chars if c['token']==r'\sqrt']
    root_bars=[b for b in bars if any(abs(b.x0-r['bbox'][2])<3 and r['bbox'][1]-1<=b.y0<=r['bbox'][3] for r in roots)]
    fractions=[b for b in bars if all(b is not r for r in root_bars)]
    remaining=list(chars)
    for bar in sorted(fractions,key=lambda b:b.width,reverse=True):
        base=max(c['size'] for c in remaining)
        relevant=[c for c in remaining if bar.x0-.5<=(c['bbox'][0]+c['bbox'][2])/2<=bar.x1+.5
            and abs(c['origin'][1]-bar.y0)<base*2.5]
        above=[c for c in relevant if c['origin'][1]<bar.y0-.5]
        below=[c for c in relevant if c['origin'][1]>bar.y0+.5]
        if not above or not below:continue
        def local_bars(cs):
            bb=bounds(cs)
            return [b for b in bars if b is not bar and bb[0]-2<=b.x0 and b.x1<=bb[2]+2 and bb[1]-2<=b.y0<=bb[3]+2]
        numerator=layout_latex(above,local_bars(above),depth+1)
        denominator=layout_latex(below,local_bars(below),depth+1)
        atom=dict(relevant[0]);atom.update(c='◊',token=r'\frac{'+numerator+'}{'+denominator+'}',
            bbox=bounds(above+below),origin=[bar.x0,bar.y0+base*.25],size=base,span=-100-depth)
        remaining=[c for c in remaining if all(c is not x for x in above+below)]+[atom]
    return latex(remaining,bars=root_bars)


def decorations(chars):
    """Bind overprinted accent glyphs to a unique underlying symbol."""
    output=[dict(c) for c in chars];unresolved=[]
    for accent in list(output):
        if accent['token'] not in (r'\bar',r'\hat'):continue
        cx=(accent['bbox'][0]+accent['bbox'][2])/2
        options=[c for c in output if c is not accent and c['c'].isalpha() and c['size']>=accent['size']*.85
            and c['bbox'][0]-.5<=cx<=c['bbox'][2]+.5 and abs(c['origin'][1]-accent['origin'][1])<accent['size']*.7]
        if len(options)!=1:unresolved.append(accent);continue
        target=options[0];target['token']=accent['token']+'{'+target['token']+'}'
        target['decoration_evidence']={'glyph':accent,'operation':accent['token']};output.remove(accent)
    return output,unresolved
