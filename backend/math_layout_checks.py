"""Support checks flag unsupported geometry; never certify mathematical truth."""
import statistics

def layout_checks(chars,bars,rendered):
    if not chars:return ['no_math_glyph_evidence']
    checks=[];roots=[c for c in chars if c['token']==r'\sqrt']
    for root in roots:
        if not any(abs(b.x0-root['bbox'][2])<3 and root['bbox'][1]-1<=b.y0<=root['bbox'][3] for b in bars):
            checks.append('radical_scope_without_source_rule');break
    if roots and rendered.count(r'\sqrt{')<len(roots):checks.append('unresolved_radical_operand')
    body=statistics.median(c['size'] for c in chars if c['c'].strip())
    primary=[c for c in chars if c['size']>=body*.86 and not c['font'].startswith('CMEX') and c['c'].strip()]
    baselines=[]
    for c in primary:
        if not any(abs(c['origin'][1]-y)<body*.3 for y in baselines):baselines.append(c['origin'][1])
    if len(baselines)>2 and max(baselines)-min(baselines)>body*2.5:
        checks.append('multiline_layout_requires_partition')
    fractions=0
    for b in bars:
        if any(abs(b.x0-r['bbox'][2])<3 and r['bbox'][1]-1<=b.y0<=r['bbox'][3] for r in roots):continue
        local=[c for c in primary if b.x0-.5<(c['bbox'][0]+c['bbox'][2])/2<b.x1+.5 and abs(c['origin'][1]-b.y0)<body*2.5]
        if any(c['origin'][1]<b.y0-.5 for c in local) and any(c['origin'][1]>b.y0+.5 for c in local):fractions+=1
    if fractions>rendered.count(r'\frac{'):checks.append('unconsumed_fraction_rule')
    return checks
