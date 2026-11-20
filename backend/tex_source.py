"""Read-only, bounded TeX source parsing. No TeX engine or author code execution."""
import gzip,hashlib,io,json,re,tarfile,zipfile
from pathlib import Path,PurePosixPath

VERSION='restricted-tex-1'
class SourceFailure(ValueError):pass

def unpack(data,root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    files={};total=0
    def add(name,content):
        nonlocal total
        name=name.replace('\\','/');part=PurePosixPath(name)
        if part.is_absolute() or '..' in part.parts or ':' in name or '\x00' in name:raise SourceFailure('源文件包含越界路径')
        path=(root/name).resolve()
        if not path.is_relative_to(root):raise SourceFailure('源文件解包路径越界')
        total+=len(content)
        if len(files)>=2000 or total>100*1024*1024 or len(content)>32*1024*1024:raise SourceFailure('源文件解包预算超限')
        if name in files:raise SourceFailure('源文件包含重复路径')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content);files[name]=path
    if data.startswith(b'%PDF'):raise SourceFailure('源接口返回PDF，没有可解析TeX源')
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if info.is_dir():continue
                if (info.external_attr>>16)&0o170000==0o120000:raise SourceFailure('源文件不允许符号链接')
                if info.file_size>32*1024*1024:raise SourceFailure('源文件大小超限')
                add(info.filename,z.read(info))
    else:
        try:
            with tarfile.open(fileobj=io.BytesIO(data),mode='r:*') as tar:
                for member in tar:
                    if member.isdir():continue
                    if not member.isfile():raise SourceFailure('源文件不允许链接或特殊文件')
                    if member.size>32*1024*1024:raise SourceFailure('源文件大小超限')
                    add(member.name,tar.extractfile(member).read())
        except tarfile.ReadError:
            if data.startswith(b'\x1f\x8b'):
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:data=f.read(4*1024*1024+1)
            if len(data)>4*1024*1024 or b'\\' not in data:raise SourceFailure('不是支持的TeX源文件')
            add('main.tex',data)
    return files

def strip_comments(text):return re.sub(r'(?m)(?<!\\)%[^\n]*','',text)

def group(text,pos,opening='{',closing='}'):
    while pos<len(text) and text[pos].isspace():pos+=1
    if pos>=len(text) or text[pos]!=opening:raise SourceFailure('TeX参数不是平衡分组')
    start=pos+1;depth=1;pos+=1
    while pos<len(text):
        if text[pos]=='\\':pos+=2;continue
        if text[pos]==opening:depth+=1
        if text[pos]==closing:
            depth-=1
            if depth==0:return text[start:pos],pos+1
        pos+=1
    raise SourceFailure('TeX参数未闭合')

def load_document(root):
    root=Path(root);texts={p.relative_to(root).as_posix():strip_comments(p.read_text(encoding='utf-8',errors='replace')) for p in root.rglob('*.tex')}
    if any(len(t)>2*1024*1024 for t in texts.values()):raise SourceFailure('TeX文本超限')
    mains=[n for n,t in texts.items() if re.search(r'\\documentclass(?:\[[^]]*\])?\s*\{',t) and r'\begin{document}' in t]
    included={}
    for n,t in texts.items():
        included[n]=[]
        for match in re.finditer(r'\\(?:input|include)\s*\{([^}]+)\}',t):
            relative=(PurePosixPath(n).parent/match[1]).as_posix()
            included[n].append(relative if relative.endswith('.tex') else relative+'.tex')
    candidates=[n for n in mains if not any(n in values for key,values in included.items() if key!=n)]
    if len(candidates)!=1:raise SourceFailure('无法唯一识别主TeX文件')
    ordered=[];active=set();visited=set()
    def visit(name,depth=0):
        if depth>16 or len(ordered)>128:raise SourceFailure('TeX引用预算超限')
        if name in active:raise SourceFailure('TeX文件循环引用')
        if name not in texts:raise SourceFailure('TeX引用缺失或越界：'+name[:120])
        if name in visited:return
        active.add(name);visited.add(name);ordered.append((name,texts[name]))
        for child in included[name]:visit(child,depth+1)
        active.remove(name)
    visit(candidates[0]);return candidates[0],ordered

def macro_definitions(text):
    macros={};warnings=[]
    pattern=re.compile(r'\\(?:newcommand|renewcommand|providecommand)\*?\s*\{(\\[A-Za-z]+)\}(?:\s*\[([0-9])\])?|\\def\s*(\\[A-Za-z]+)((?:#[1-9])*)')
    for m in pattern.finditer(text):
        try:body,end=group(text,m.end())
        except SourceFailure:warnings.append('unsupported_macro_definition');continue
        name=m[1] or m[3];count=int(m[2] or len(m[4] or '')//2)
        if count>4 or len(body)>2048 or re.search(r'\\(?:input|include|write|read|catcode|csname|loop|openout|special)',body):
            warnings.append('unsafe_or_complex_macro:'+name);continue
        macros[name]=(count,body)
    for m in re.finditer(r'\\DeclareMathOperator\*?\s*\{(\\[A-Za-z]+)\}\s*\{',text):
        try:body,_=group(text,m.end()-1)
        except SourceFailure:continue
        if re.fullmatch(r'[A-Za-z ]{1,64}',body):macros[m[1]]=(0,r'\operatorname{'+body+'}')
    return macros,warnings

def mask_discarded(text,macros):
    chars=list(text)
    for m in re.finditer(r'\\[A-Za-z]+',text):
        if m[0] not in macros:continue
        count,body=macros[m[0]]
        if not count or body.strip():continue
        end=m.end()
        try:
            for _ in range(count):_,end=group(text,end)
        except SourceFailure:continue
        chars[m.start():end]=['\n' if c=='\n' else ' ' for c in text[m.start():end]]
    return ''.join(chars)

def expand_macros(text,macros):
    for _ in range(8):
        output=[];pos=0;changed=False
        for m in list(re.finditer(r'\\[A-Za-z]+',text)):
            if m.start()<pos:continue
            if m[0] not in macros:continue
            count,body=macros[m[0]];end=m.end()
            try:
                for i in range(count):arg,end=group(text,end);body=body.replace('#'+str(i+1),arg)
            except SourceFailure:continue
            output.extend([text[pos:m.start()],body]);pos=end;changed=True
        output.append(text[pos:]);new=''.join(output)
        if len(new)>100000:raise SourceFailure('宏展开长度超限')
        text=new
        if not changed:return text,[]
    return text,['macro_expansion_budget']

def split_top(text,separator):
    result=[];start=0;depth=0;pos=0
    while pos<len(text):
        if depth==0 and text.startswith(separator,pos):result.append(text[start:pos]);pos+=len(separator);start=pos;continue
        if text[pos]=='\\':
            pos+=2;continue
        if text[pos]=='{':depth+=1
        if text[pos]=='}':depth-=1
        pos+=1
    result.append(text[start:]);return result

def math_lines(text):
    """Top-level alignment rows; matrix/array rows remain in their own object."""
    result=[];start=0;depth=0;environments=0;pos=0
    while pos<len(text):
        match=re.match(r'\\(begin|end)\{[^}]+\}',text[pos:])
        if match:environments+=1 if match[1]=='begin' else -1;pos+=match.end();continue
        if text.startswith(r'\\',pos) and depth==0 and environments==0:
            result.append((start,pos,text[start:pos]));pos+=2;start=pos;continue
        if text[pos]=='\\':pos+=2;continue
        if text[pos]=='{':depth+=1
        if text[pos]=='}':depth-=1
        pos+=1
    result.append((start,len(text),text[start:]));return [r for r in result if r[2].strip()]

def tabular_model(text):
    m=re.search(r'\\begin\{(?:tabular\*?|tabularx|array)\}',text)
    if not m:return None
    pos=m.end()
    if text[m.start():m.end()].endswith('tabularx}') or text[m.start():m.end()].endswith('tabular*}'):
        _,pos=group(text,pos)
    spec,pos=group(text,pos)
    end=re.search(r'\\end\{(?:tabular\*?|tabularx|array)\}',text[pos:])
    if not end:return None
    body=text[pos:pos+end.start()];cells=[];row=0
    for rawrow in split_top(body,r'\\'):
        rawrow=re.sub(r'\\(?:toprule|midrule|bottomrule|hline|cline|cmidrule)(?:\([^)]*\))?(?:\{[^}]*\})?','',rawrow).strip()
        rawrow=re.sub(r'^\[[^]]*\]','',rawrow).strip()
        if not rawrow:continue
        col=0
        for raw in split_top(rawrow,'&'):
            value=raw.strip();span=1;rs=1
            mm=re.match(r'\\multicolumn\s*\{(\d+)\}',value)
            if mm:
                span=int(mm[1]);_,q=group(value,mm.end());value,_=group(value,q)
            mm=re.match(r'\\multirow\s*\{(\d+)\}',value)
            if mm:
                rs=int(mm[1]);_,q=group(value,mm.end());value,_=group(value,q)
            if not 1<=span<=100 or not 1<=rs<=100:raise SourceFailure('表格跨度超限')
            cells.append({'row':row,'column':col,'row_span':rs,'column_span':span,'raw_text':raw,'text':value});col+=span
        row+=1
    return {'source':'restricted_tex_tabular','column_spec':spec,'cells':cells,'num_rows':row,
            'num_columns':max((c['column']+c['column_span'] for c in cells),default=0),'verification':'unverified'}

def parse_source(root):
    main,files=load_document(root);macros,warnings=macro_definitions('\n'.join(t for _,t in files));objects=[]
    texts={name:mask_discarded(text,macros) for name,text in files}
    def segments(name):
        text=texts[name];start=0
        for m in re.finditer(r'\\(?:input|include)\s*\{([^}]+)\}',text):
            yield name,text[start:m.start()],start
            child=(PurePosixPath(name).parent/m[1]).as_posix()
            if not child.endswith('.tex'):child+='.tex'
            yield from segments(child);start=m.end()
        yield name,text[start:],start
    known=set('frac dfrac tfrac over sqrt sum prod int oint lim max min log exp sin cos tan softmax operatorname mathop mathrm mathit mathbf mathbb mathcal bold boldsymbol bm text textrm textnormal left right big Big bigg Bigg cdot times odot otimes le leq ge geq neq approx sim simeq propto equiv in notin subset subseteq cup cap to mapsto rightarrow leftarrow infty nabla partial top perp vert Vert mid ell hbar circ prime ast quad qquad displaystyle textstyle limits nolimits underbrace overbrace overline underline hat widehat tilde widetilde bar vec dot ddot label tag ref eqref nonumber notag begin end substack acute check breve rm bf sf cal alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi pi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega'.split())
    starts={};ends={}
    for name,(count,body) in macros.items():
        if count:continue
        expanded,_=expand_macros(body,macros)
        m=re.fullmatch(r'\s*\\(begin|end)\{([^}]+)\}\s*',expanded)
        if m:(starts if m[1]=='begin' else ends)[name]=m[2]
    # A single delimited argument that wraps one literal math environment is
    # recognized as an environment alias, without interpreting general TeX.
    for m in re.finditer(r'\\def\s*(\\[A-Za-z]+)#1\s*(\\[A-Za-z]+)\s*\{','\n'.join(t for _,t in files)):
        try:body,_=group('\n'.join(t for _,t in files),m.end()-1)
        except SourceFailure:continue
        env=re.fullmatch(r'\s*\\begin\{([^}]+)\}\s*#1\s*\\end\{\1\}\s*',body)
        if env:starts[m[1]]=env[1];ends[m[2]]=env[1]
    in_document=False
    known.update('cdots ldots vdots ddots dots langle rangle overset underset arg'.split())
    # TeX commands are only scanned as text; never passed to a shell or compiler.
    for filename,text,base_offset in segments(main):
        if not in_document:
            marker=text.find(r'\begin{document}')
            if marker<0:continue
            base_offset+=marker+len(r'\begin{document}');text=text[marker+len(r'\begin{document}'):];in_document=True
        found=[]
        environment_by_span={}
        for m in re.finditer(r'\\(part|chapter|section|subsection|subsubsection|caption|label|ref|eqref)\*?(?:\[[^]]*\])?\s*\{',text):
            try:value,end=group(text,m.end()-1)
            except SourceFailure:continue
            found.append((m.start(),end,m[1],value))
        environments=re.compile(r'\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|table\*?|figure\*?)\}(.*?)\\end\{\1\}',re.S)
        spans=[]
        for m in environments.finditer(text):
            kind='table' if m[1].startswith('table') else 'figure' if m[1].startswith('figure') else 'display_math'
            found.append((m.start(),m.end(),kind,m[2]));spans.append((m.start(),m.end()))
            environment_by_span[(m.start(),m.end())]=m[1]
        for alias,env in starts.items():
            closing=[name for name,target in ends.items() if target==env]
            if not closing or not re.fullmatch(r'(?:equation|align|gather|multline|eqnarray)\*?',env):continue
            pattern=re.compile(re.escape(alias)+r'\b(.*?)'+'(?:'+'|'.join(re.escape(n)+r'\b' for n in closing)+')',re.S)
            for m in pattern.finditer(text):
                if any(a<=m.start()<b for a,b in spans):continue
                found.append((m.start(),m.end(),'display_math',m[1]));spans.append((m.start(),m.end()))
                environment_by_span[(m.start(),m.end())]=env
        for m in re.finditer(r'\$\$(.+?)\$\$|\\\[(.+?)\\\]|(?<!\\)\$([^$\n]+?)(?<!\\)\$|\\\((.+?)\\\)',text,re.S):
            if any(a<=m.start()<b for a,b in spans):continue
            found.append((m.start(),m.end(),'display_math' if m[1] or m[2] else 'inline_math',next(x for x in m.groups() if x is not None)))
        for start,end,kind,raw in sorted(found):
            expanded,checks=expand_macros(raw,macros)
            remaining=[name for name in re.findall(r'\\[A-Za-z]+',expanded) if name in macros]
            if kind in ('display_math','inline_math'):
                checks+=['unknown_command:'+name for name in sorted(set(re.findall(r'\\([A-Za-z]+)',expanded))-known)]
            obj={'id':f'source:{len(objects):06}','kind':kind,'raw':raw,'expanded':expanded,'file':filename,
                 'line':texts[filename].count('\n',0,base_offset+start)+1,'offset':[base_offset+start,base_offset+end],'checks':checks+['unexpanded_macro:'+x for x in remaining],
                 'verification':'unverified','pdf_mapping':{'status':'unknown','regions':[]}}
            obj['environment']=environment_by_span.get((start,end))
            obj['context_before']=texts[filename][max(0,base_offset+start-900):base_offset+start]
            obj['context_after']=texts[filename][base_offset+end:base_offset+end+500]
            if kind=='table':
                try:obj['table_model']=tabular_model(expanded)
                except SourceFailure as exc:obj['checks'].append(str(exc))
            obj['labels']=re.findall(r'\\label\{([^}]+)\}',raw)
            objects.append(obj)
            if kind=='display_math':
                lines=math_lines(raw)
                if len(lines)>1:
                    obj['checks'].append('multi_line_source_parent');obj['children']=[]
                    raw_start=text.find(raw,start,end)
                    for a,b,line_raw in lines:
                        value,line_checks=expand_macros(line_raw,macros)
                        line_checks+=['unknown_command:'+x for x in sorted(set(re.findall(r'\\([A-Za-z]+)',value))-known)]
                        offset=base_offset+(raw_start if raw_start>=0 else start)+a
                        child={**obj,'id':f'source:{len(objects):06}','raw':line_raw,'expanded':value,'checks':line_checks,
                            'offset':[offset,offset+b-a],'line':texts[filename].count('\n',0,offset)+1,
                            'parent_id':obj['id'],'context_before':texts[filename][max(0,offset-900):offset],
                            'context_after':texts[filename][offset+b-a:offset+b-a+500],
                            'labels':re.findall(r'\\label\{([^}]+)\}',line_raw),'children':[]}
                        obj['children'].append(child['id']);objects.append(child)
            if len(objects)>10000:raise SourceFailure('源对象数量超限')
    source_text='\n'.join(texts.values())
    default_equation_counter=not re.search(r'\\(?:setcounter|addtocounter|numberwithin)\s*\{equation\}|\\renewcommand\s*\{\\theequation\}|\\tag\{',source_text)
    if any((o.get('environment') or '').startswith('multline') for o in objects):default_equation_counter=False
    equation_number=0
    stack=[];levels={'part':0,'chapter':1,'section':2,'subsection':3,'subsubsection':4}
    for obj in objects:
        if obj['kind'] in levels:
            level=levels[obj['kind']]
            while stack and stack[-1][0]>=level:stack.pop()
            obj.update(level=level,parent_id=stack[-1][1] if stack else None);stack.append((level,obj['id']))
        else:obj['section_id']=stack[-1][1] if stack else None
        explicit=re.search(r'\\tag\{([^}]+)\}',obj['raw'])
        obj['number']=explicit[1] if explicit else None
        obj['number_status']='explicit_source_tag' if explicit else 'unknown_without_reliable_aux'
        if (default_equation_counter and obj['kind']=='display_math' and obj.get('environment') in ('equation','align','eqnarray','gather')
                and not obj.get('children') and not re.search(r'\\(?:nonumber|notag)\b',obj['raw'])):
            equation_number+=1;obj['number']=str(equation_number);obj['number_status']='derived_unmodified_latex_counter'
    labels={}
    for obj in objects:
        for label in obj.get('labels',[]):labels.setdefault(label,[]).append(obj['id'])
    references=[]
    for obj in objects:
        if obj['kind'] not in ('ref','eqref'):continue
        targets=labels.get(obj['raw'],[])
        references.append({'source_object_id':obj['id'],'label':obj['raw'],'targets':targets,
                           'status':'candidate' if len(targets)==1 else 'unknown_or_ambiguous'})
    return {'parser_version':VERSION,'main_file':main,'included_files':[n for n,_ in files],
            'objects':objects,'cross_references':references,'warnings':warnings,'verification':'unverified','execution':'none'}
