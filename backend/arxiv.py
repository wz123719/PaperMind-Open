import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urljoin
import httpx
from .db import MAX_BYTES

ID = r'(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+(?:\.[A-Z]{2})?/\d{7})'
PATTERN = re.compile(rf'(?P<id>{ID})(?:v(?P<version>[1-9]\d*))?')
ALLOWED = {'arxiv.org', 'export.arxiv.org'}

class ImportFailure(ValueError):
    pass

def normalize(value: str):
    value = value.strip()
    if '://' in value:
        u = urlsplit(value)
        if (u.scheme != 'https' or u.hostname not in ALLOWED or u.port not in (None, 443)
                or u.username or u.password or u.query or u.fragment):
            raise ValueError('仅支持 HTTPS arXiv 官方 abs/pdf 链接或 arXiv ID')
        match = re.fullmatch(r'/(?:abs|pdf)/(.+)', u.path)
        if not match:
            raise ValueError('arXiv 链接路径无效')
        value = match[1]
        if value.endswith('.pdf'):
            value = value[:-4]
    m = PATTERN.fullmatch(value)
    if not m:
        raise ValueError('arXiv ID 格式无效')
    base = m['id']
    # Modern identifiers encode YYMM; invalid months cannot be papers.
    if base[0].isdigit() and not 1 <= int(base[2:4]) <= 12:
        raise ValueError('arXiv ID 月份无效')
    version = int(m['version']) if m['version'] else None
    return {'arxiv_id': base, 'arxiv_version': version,
            'canonical': base + (f'v{version}' if version else '')}

def safe_url(url):
    u = urlsplit(url)
    if (u.scheme != 'https' or u.hostname not in ALLOWED or u.port not in (None, 443)
            or u.username or u.password or u.fragment
            or not (u.path.startswith('/pdf/') or u.path == '/api/query')):
        raise ImportFailure('arXiv 返回了不允许访问的重定向地址')
    return url

def fetch(client, url, limit, target=None, progress=lambda _: None):
    """Every redirect is checked before request; never follows arbitrary locations."""
    for _ in range(5):
        safe_url(url)
        with client.stream('GET', url, follow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('location', ''))
                safe_url(url)
                continue
            response.raise_for_status()
            if int(response.headers.get('content-length', '0')) > limit:
                raise ImportFailure('下载超过大小限制')
            total, chunks = 0, []
            started = time.monotonic()
            for chunk in response.iter_bytes(65536):
                if time.monotonic() - started > 180:
                    raise ImportFailure('arXiv 下载超过总时限')
                total += len(chunk)
                if total > limit:
                    raise ImportFailure('下载超过大小限制')
                if target:
                    target.write(chunk)
                else:
                    chunks.append(chunk)
                progress(total)
            return b''.join(chunks)
    raise ImportFailure('arXiv 重定向次数过多')

def download(payload, target, progress, client=None):
    from .llm_provider import trust_system_proxy
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=10), trust_env=trust_system_proxy(),
                                    headers={'User-Agent': 'PaperMindWorkspace/1.0 (local research importer)'})
    try:
        canonical = payload['canonical']
        raw = fetch(client, f'https://export.arxiv.org/api/query?id_list={canonical}', 2 * 1024 * 1024)
        ns = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom'}
        entry = ET.fromstring(raw).find('a:entry', ns)
        if entry is None or entry.findtext('a:title', '', ns) == 'Error':
            raise ImportFailure('arXiv 未找到该论文')
        returned = entry.findtext('a:id', '', ns).rsplit('/abs/', 1)[-1]
        resolved = normalize(returned)
        if resolved['arxiv_id'] != payload['arxiv_id'] or (payload['arxiv_version'] and resolved['arxiv_version'] != payload['arxiv_version']):
            raise ImportFailure('arXiv 返回的论文身份或版本不匹配')
        info = {**resolved, 'title': ' '.join(entry.findtext('a:title', '', ns).split()) or None,
                'authors': [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)],
                'year': int(entry.findtext('a:published', '', ns)[:4]),
                'doi': entry.findtext('x:doi', None, ns)}
        with target.open('wb') as output:
            fetch(client, f"https://arxiv.org/pdf/{resolved['canonical']}", MAX_BYTES, output, progress)
        return info
    finally:
        if own:
            client.close()
