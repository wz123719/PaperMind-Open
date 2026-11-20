"""Inline fraction detection from PDF rules and positioned glyphs, not word matches."""
import pymupdf as fitz
from .native_math import characters,horizontal_bars,is_math,latex,bounds


def fraction_candidates(page,clip):
    chars=characters(page,clip);math=[c for c in chars if is_math(c) and c['c'].strip()]
    results=[]
    for bar in horizontal_bars(page,clip):
        if any(c['token']==r'\sqrt' and abs(bar.x0-c['bbox'][2])<3 and c['bbox'][1]-1<=bar.y0<=c['bbox'][3] for c in chars):continue
        if not 5<bar.width<min(180,clip.width*.9):continue
        span=[c for c in math if bar.x0-.6<=(c['bbox'][0]+c['bbox'][2])/2<=bar.x1+.6 and abs(c['origin'][1]-bar.y0)<12]
        above=[c for c in span if c['origin'][1]<bar.y0]
        below=[c for c in span if c['origin'][1]>bar.y0]
        if not above or not below:continue
        # A true fraction has two math bands, with the rule between their baselines.
        if max(c['origin'][1] for c in above)>=min(c['origin'][1] for c in below):continue
        left=[c for c in math if bar.x0-65<c['bbox'][0]<bar.x0 and abs(c['origin'][1]-bar.y0)<5]
        # Stop at the nearest source prose boundary to avoid attaching another clause.
        prose=[c['bbox'][2] for c in chars if not is_math(c) and c['c'].strip()
            and c['bbox'][2]<bar.x0 and abs(c['origin'][1]-bar.y0)<5]
        if prose:left=[c for c in left if c['bbox'][0]>=max(prose)-.3]
        evidence=left+above+below
        bb=bounds(evidence)
        expression=latex(left)+r'\frac{'+latex(above)+'}{'+latex(below)+'}'
        if any(abs(bb[0]-old['bbox'][0])<1 and abs(bb[1]-old['bbox'][1])<1 for old in results):continue
        results.append({'bbox':bb,'latex':expression,'glyphs':evidence,'fraction_rule':list(bar),
            'source':'pdf_fraction_rule_and_glyphs','verification':'unverified'})
    # A short fraction inside prose is not itself the full expression. Recover
    # only a uniquely bounded mathematical run on its physical source line.
    if not results:return []
    from .native_math import group_lines
    from .algorithm_layout import math_runs
    runs=[m for g in group_lines(chars) for m in math_runs(page,g['chars'])]
    complete=[]
    for candidate in results:
        bar=fitz.Rect(candidate['fraction_rule'])
        matching=[m for m in runs if m['bbox'][0]-3<=bar.x0 and m['bbox'][2]+3>=bar.x1
                  and m['bbox'][1]-1<=bar.y0<=m['bbox'][3]+1]
        if len(matching)!=1 or r'\frac{' not in matching[0]['latex']:
            complete.append({**candidate,'checks':['incomplete_inline_fraction_scope'],'verification':'needs_review'});continue
        m=matching[0]
        if not any(c['bbox']==m['bbox'] for c in complete):complete.append({**candidate,'bbox':m['bbox'],'glyphs':m['glyphs'],'latex':m['latex']})
    return complete


def display_line_candidates(page,clip):
    """Independent math lines can be mislabeled as prose without a fraction."""
    from .native_math import group_lines,layout_latex
    results=[]
    for line in group_lines(characters(page,clip)):
        cs=[c for c in line['chars'] if c['c'].strip()]
        if len(cs)<8 or not any(c['token'] in ('=',r'\leftarrow') for c in cs):continue
        if sum(is_math(c) for c in cs)/len(cs)<.7:continue
        prose=''.join(c['c'] for c in cs if not is_math(c))
        if len(__import__('re').findall(r'[A-Za-z]{3,}',prose))>1:continue
        bb=bounds(cs)
        results.append({'bbox':bb,'latex':layout_latex(cs,horizontal_bars(page,__import__('pymupdf').Rect(bb))),
            'glyphs':cs,'source':'independent_math_line_glyphs','verification':'unverified'})
    return results


def merge_candidates(fractions,displays):
    results=list(fractions)
    def area(r):return max(0,r.width)*max(0,r.height)
    for candidate in displays:
        rect=fitz.Rect(candidate['bbox']);overlap=[c for c in results if area(rect & fitz.Rect(c['bbox']))>min(area(rect),area(fitz.Rect(c['bbox'])))*.5]
        if not overlap:results.append(candidate)
        elif all(area(rect)>area(fitz.Rect(c['bbox']))*1.2 for c in overlap):
            results=[c for c in results if c not in overlap]+[candidate]
    return results
