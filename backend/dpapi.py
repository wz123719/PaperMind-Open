"""Windows DPAPI local credential store. Secrets never enter SQLite snapshots or API responses."""
import base64
import ctypes
import json
import os
from pathlib import Path
from . import db

CRYPTPROTECT_UI_FORBIDDEN = 0x01


def _store_path() -> Path:
    return db.STORAGE / 'credentials.dpapi.json'


def _protect_bytes(raw: bytes) -> str:
    if os.name != 'nt':
        return 'b64:' + base64.b64encode(raw).decode('ascii')
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = DATA_BLOB(len(raw), buf)
    out_blob = DATA_BLOB()
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), 'PaperMind Local Credential', None,
        None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        encrypted = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        return 'dpapi:' + base64.b64encode(encrypted).decode('ascii')
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _unprotect_bytes(token: str) -> bytes:
    if token.startswith('b64:'):
        return base64.b64decode(token[4:])
    if not token.startswith('dpapi:') or os.name != 'nt':
        raise ValueError('凭据密文格式与当前系统不兼容')
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    cipher = base64.b64decode(token[6:])
    buf = ctypes.create_string_buffer(cipher, len(cipher))
    in_blob = DATA_BLOB(len(cipher), buf)
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        if out_blob.pbData:
            kernel32.LocalFree(out_blob.pbData)


def _read_store() -> dict:
    path = _store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_store(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def mask_key(secret: str) -> str:
    s = secret.strip()
    if len(s) <= 8:
        return '••••••••'
    return f'{s[:4]}••••{s[-4:]}'


def save_secret(scope: str, secret: str) -> None:
    clean = secret.strip()
    if not clean or len(clean) > 500 or any(ord(c) < 32 for c in clean):
        raise ValueError('API 密钥格式无效')
    store = _read_store()
    store[scope] = {
        'cipher': _protect_bytes(clean.encode('utf-8')),
        'masked': mask_key(clean),
    }
    _write_store(store)


def delete_secret(scope: str) -> None:
    store = _read_store()
    if scope in store:
        del store[scope]
        _write_store(store)


def load_secret(scope: str = 'workspace') -> str:
    store = _read_store()
    entry = store.get(scope) or (store.get('workspace') if scope != 'workspace' else None)
    if not isinstance(entry, dict) or not entry.get('cipher'):
        return ''
    try:
        return _unprotect_bytes(entry['cipher']).decode('utf-8')
    except (OSError, ValueError, UnicodeError):
        return ''


def secret_metadata(scope: str = 'workspace') -> dict:
    store = _read_store()
    entry = store.get(scope)
    if isinstance(entry, dict) and entry.get('cipher'):
        return {'has_saved_key': True, 'masked_key': entry.get('masked') or '••••••••', 'key_source': scope}
    if scope != 'workspace' and isinstance(store.get('workspace'), dict) and store['workspace'].get('cipher'):
        return {'has_saved_key': True, 'masked_key': store['workspace'].get('masked') or '••••••••', 'key_source': 'workspace'}
    return {'has_saved_key': False, 'masked_key': None, 'key_source': None}
