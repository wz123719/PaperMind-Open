"""Bounded structural LaTeX reader. Syntax evidence, never a semantic verdict."""
import re

VERSION='math-tree-2'
TOKEN=re.compile(r'\\[A-Za-z]+|\\.|[{}_^()[\]]|[^\s]')

def math_tree(latex):
    tokens=TOKEN.findall(latex);checks=[];pos=0
    if len(tokens)>12000:return {'version':VERSION,'type':'unknown','checks':['token_budget'],'verification':'unverified'}
    def sequence(stop=None,depth=0):
        nonlocal pos
        if depth>48:raise ValueError('depth_budget')
        nodes=[]
        while pos<len(tokens):
            token=tokens[pos]
            if token==stop:pos+=1;return {'type':'sequence','items':nodes}
            if token in ('}',')',']'):
                checks.append('unmatched_closing_group');pos+=1;continue
            if token in ('_','^'):
                pos+=1;arg=argument(depth+1)
                if not nodes:checks.append('script_without_base');nodes.append({'type':'unknown'})
                previous=nodes[-1]
                if previous.get('type')!='scripts':previous={'type':'scripts','base':previous};nodes[-1]=previous
                key='lower' if token=='_' else 'upper'
                if key in previous:checks.append('duplicate_script')
                previous[key]=arg;continue
            nodes.append(argument(depth+1))
        if stop:checks.append('unclosed_group')
        return {'type':'sequence','items':nodes}
    def argument(depth):
        nonlocal pos
        if pos>=len(tokens):checks.append('missing_argument');return {'type':'unknown'}
        t=tokens[pos];pos+=1
        if t in ('{','(','['):
            return {'type':'group','delimiter':t,'body':sequence({'{':'}','(':')','[':']'}[t],depth)}
        if t in (r'\frac',r'\dfrac',r'\tfrac'):
            return {'type':'fraction','numerator':argument(depth+1),'denominator':argument(depth+1)}
        if t==r'\sqrt':
            degree=argument(depth+1) if pos<len(tokens) and tokens[pos]=='[' else None
            return {'type':'root','degree':degree,'radicand':argument(depth+1)}
        if t in (r'\bar',r'\overline',r'\hat',r'\widehat',r'\tilde',r'\widetilde',r'\vec'):
            return {'type':'decoration','operator':t,'operand':argument(depth+1)}
        return {'type':'operator' if t in (r'\sum',r'\prod',r'\int','+','-','=',r'\le',r'\ge',r'\cdot',r'\times') else 'symbol','value':t}
    try:tree=sequence()
    except (ValueError,RecursionError) as exc:tree={'type':'unknown'};checks.append(str(exc))
    # Preserve the sequence and additionally expose sum limits and its following term.
    def relations(node):
        if not isinstance(node,dict):return
        if node.get('type')=='sequence':
            items=node['items']
            for i,n in enumerate(items):
                base=n.get('base',n)
                if base.get('value') in (r'\sum',r'\prod',r'\int'):
                    term=[]
                    for following in items[i+1:]:
                        if following.get('value') in ('+','-','=',r'\le',r'\ge'):break
                        term.append(following)
                    node.setdefault('operator_relations',[]).append({'operator':base['value'],
                        'lower':n.get('lower'),'upper':n.get('upper'),'operand':{'type':'sequence','items':term}})
        for key,value in list(node.items()):
            if key=='operator_relations':continue
            if isinstance(value,dict):relations(value)
            elif isinstance(value,list):
                for child in value:relations(child)
    relations(tree)
    def unary_transpose(node):
        if not isinstance(node,dict):return
        for value in list(node.values()):
            if isinstance(value,dict):unary_transpose(value)
            elif isinstance(value,list):
                for item in value:unary_transpose(item)
        if node.get('type')!='scripts':return
        upper=node.get('upper',{})
        value=upper
        if value.get('type')=='group':value=value.get('body',{})
        items=value.get('items',[]) if value.get('type')=='sequence' else [value]
        if len(items)==1 and items[0].get('value')==r'\top':
            operand={k:v for k,v in node.items() if k!='upper'}
            if 'lower' not in operand:operand=operand['base']
            node.clear();node.update(type='transpose',operand=operand)
    unary_transpose(tree)
    def infix_fractions(node):
        if not isinstance(node,dict):return
        if node.get('type')=='sequence':
            items=node['items'];indices=[i for i,n in enumerate(items) if n.get('value')==r'\over']
            if len(indices)==1:
                i=indices[0];node['items']=[{'type':'fraction','numerator':{'type':'sequence','items':items[:i]},'denominator':{'type':'sequence','items':items[i+1:]}}]
            elif indices:checks.append('ambiguous_infix_fraction')
        for value in node.values():
            if isinstance(value,dict):infix_fractions(value)
            elif isinstance(value,list):
                for child in value:infix_fractions(child)
    infix_fractions(tree)
    return {'version':VERSION,'expression':tree,'checks':list(dict.fromkeys(checks)),'verification':'unverified'}
