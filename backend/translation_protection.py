"""Exact, nonce-scoped protection. Checks are syntactic, never semantic approval."""
import re
import uuid
from collections import Counter

VERSION = 'protection-2'
TOKEN = re.compile(r'⟦PM:[^⟧\n]+⟧')
ELEMENT = re.compile(
    r'```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]+`|\$\$[\s\S]*?\$\$|(?<!\\)\$(?:\\.|[^$])+?\$'
    r'|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)'
    r'|\([A-Z][A-Za-z .,&;-]{0,70},?\s*\d{4}[a-z]?(?:\s*;[^)\n]{1,70})?\)'
    r'|\[(?:\d+[a-z]?(?:\s*[,;–—-]\s*\d+[a-z]?)*|[A-Z][^\]\n]{0,60}\d{4})\]'
    r'|\b(?:Fig(?:ure)?\.?|Table|Eq(?:uation)?\.?|Algorithm|Theorem)\s*\(?\d+[a-z]?(?:\.\d+)*\)?'
    r'|(?<![\w])(?:[+−–-]?\d+(?:[.,]\d+)*(?:[eE][+−-]?\d+)?'
    r'(?:\s*[×x]\s*10\s*\^\s*[+−-]?\d+|\s*\^\s*[+−-]?\d+|[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+)?'
    r'(?:\s*[–—-]\s*[+−-]?\d+(?:\.\d+)*)?(?:\s*(?:%|ms|GHz|MHz|kHz|Hz|GB|MB|KB|mm|cm|km|kg|mg|mV|mA|°C|K|s)\b|%)?)'
    r'|[≤≥≠≈∑∏∫∞∂∇±×÷→←↔√α-ωΑ-Ω]')


def normalize(term):
    return ' '.join(term.casefold().split())


def protect(text, entries):
    nonce = uuid.uuid4().hex
    while nonce in text:
        nonce = uuid.uuid4().hex
    mapping = {}
    def token(value):
        key = f'⟦PM:{nonce}:{len(mapping)}⟧'
        mapping[key] = value
        return key
    def protect_terms(plain):
        candidates=[]
        for entry in entries:
            priority=3 if entry.get('locked') else (2 if entry.get('priority')=='confirmed' else (1 if entry.get('priority')=='default' else 0))
            pattern=r'(?<!\w)'+r'\s+'.join(re.escape(w) for w in entry['english'].split())+r'(?!\w)'
            for match in re.finditer(pattern,plain,re.I):
                candidates.append((priority,match.end()-match.start(),match.start(),match.end(),entry['chinese']))
        chosen=[]
        for priority,length,start,end,chinese in sorted(candidates,key=lambda item:(-item[0],-item[1],item[2],item[4])):
            if not any(start<old[1] and end>old[0] for old in chosen):chosen.append((start,end,chinese))
        pieces=[];offset=0
        for start,end,chinese in sorted(chosen):
            pieces.extend([plain[offset:start],token(chinese)]);offset=end
        return ''.join(pieces)+plain[offset:]
    # Existing token-looking source is data and gets its own protected token.
    pieces = []
    offset = 0
    combined = re.compile(TOKEN.pattern+'|'+ELEMENT.pattern)
    for match in combined.finditer(text):
        plain = protect_terms(text[offset:match.start()])
        pieces.extend([plain, token(match[0])]); offset = match.end()
    tail = protect_terms(text[offset:])
    pieces.append(tail)
    return ''.join(pieces), mapping


def restore(source, protected, output, mapping):
    if not isinstance(output, str) or not output.strip() or len(output) > 40000:
        raise ValueError('empty_or_oversized_output')
    if Counter(TOKEN.findall(output)) != Counter(mapping.keys()):
        raise ValueError('protected_token_set_or_count_mismatch')
    if output.strip() == protected.strip() and re.search(r'[A-Za-z]{3}', TOKEN.sub('', protected)):
        raise ValueError('unchanged_source')
    plain_source = TOKEN.sub('', protected)
    plain_output = TOKEN.sub('', output)
    if len(plain_source.strip()) > 100 and len(plain_output.strip()) < len(plain_source.strip()) * .18:
        raise ValueError('obvious_truncation_or_summary')
    if re.search(r'[A-Za-z]{3}', plain_source) and not re.search(r'[\u3400-\u9fff]', plain_output):
        raise ValueError('missing_chinese_translation')
    # Numeric/citation/mathematical inventions outside tokens are rejected too.
    if ELEMENT.search(plain_output):
        raise ValueError('unprotected_numeric_or_math_invention')
    return TOKEN.sub(lambda m: mapping[m[0]], output)
