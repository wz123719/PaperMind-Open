"""Conservative Markdown export regions; preserve serialized data/math/code verbatim."""
import re
from html import unescape
EXPORT_VERSION='note-markdown-2-regions'

FRONTMATTER=re.compile(r'\A---\r?\n[\s\S]*?^---[ \t]*(?:\r?\n|$)',re.M)
FENCE=re.compile(r'[ \t]{0,3}(`{3,}|~{3,})[^\r\n]*(?:\r?\n|$)')

def escaped(text,index):
    start=index
    while start and text[start-1]=='\\':start-=1
    return (index-start)%2==1

def ending(text,marker,start,single_line=False):
    index=start
    while True:
        index=text.find(marker,index)
        if index<0 or single_line and '\n' in text[start:index]:return None
        if not escaped(text,index):
            if marker!='$' or (text[index-1:index]!='$' and text[index+1:index+2]!='$'):return index
        index+=len(marker)

def regions(text):
    """Yield protected regions and ordinary prose without rewriting their bytes.

    YAML only at document start; fenced/inline code and balanced $/$$ math.
    Unclosed fences continue to EOF; unbalanced math remains ordinary prose.
    """
    header=FRONTMATTER.match(text);index=header.end() if header else 0
    if header:yield True,text[:index]
    plain=index
    while index<len(text):
        end=None
        if index==0 or text[index-1]=='\n':
            fence=FENCE.match(text,index)
            if fence:
                marker=fence[1];close=re.compile(r'^[ \t]{0,3}'+re.escape(marker[0])+'{'+str(len(marker))+r',}[ \t]*(?:\r?\n|$)',re.M).search(text,fence.end())
                end=close.end() if close else len(text)
        if end is None and text[index]=='`' and not escaped(text,index):
            opener=re.match(r'`+',text[index:])[0]
            close=re.compile(r'(?<!`)'+re.escape(opener)+r'(?!`)').search(text,index+len(opener))
            if close:end=close.end()
        if end is None and text[index]=='$' and not escaped(text,index):
            marker='$$' if text[index:index+2]=='$$' else '$'
            close=ending(text,marker,index+len(marker),marker=='$')
            if close is not None:end=close+len(marker)
        if end is not None:
            if plain<index:yield False,text[plain:index]
            yield True,text[index:end];index=end;plain=end
        else:index+=1
    if plain<len(text):yield False,text[plain:]

def safe_prose(text,image=None):
    if image:text=re.sub(r'!\[([^\]]*)\]\(([^)]+)\)',image,text)
    # Escape every angle bracket in prose, including incomplete tags that cross regions.
    text=text.replace('<','&lt;').replace('>','&gt;')
    def url(match):
        decoded=unescape(match[1]);scheme=re.sub(r'[\x00-\x20]','',decoded).lower()
        return '](blocked-unsafe-url)' if scheme.startswith(('javascript:','data:','vbscript:','file:')) else match[0]
    return re.sub(r'\]\(([^)]*)\)',url,text)

def export_markdown(text,image):
    out=[];offset=0
    for protected,part in regions(text):
        if protected:
            out.append(part)
        else:
            # Preserve Markdown blockquote markers, including Obsidian callouts.
            # Escape angle brackets in the content as before.
            clean=safe_prose(part,image)
            out.append(re.sub(r'(?m)^([ ]{0,3})&gt;(?=[ \t])',r'\1>',clean)
                       if offset==0 or text[offset-1]=='\n' else
                       re.sub(r'(\n[ ]{0,3})&gt;(?=[ \t])',r'\1>',clean))
        offset+=len(part)
    return ''.join(out)
