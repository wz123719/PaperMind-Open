"""Unified JSON fence normalization, proxy policy, and connectivity probe for LLM providers."""
import json
import os
import re
import time
import httpx
from . import dpapi

FENCE_RE = re.compile(r'^\s*```(?:json|JSON)?\s*\r?\n([\s\S]*?)\r?\n\s*```\s*$')


def strip_json_fence(raw: str) -> str:
    if not isinstance(raw, str):
        return raw
    match = FENCE_RE.match(raw.strip())
    return match.group(1).strip() if match else raw


def trust_system_proxy(config: dict | None = None) -> bool:
    if isinstance(config, dict) and 'use_system_proxy' in config:
        return bool(config['use_system_proxy'])
    return os.getenv('PAPERMIND_USE_SYSTEM_PROXY', '').lower() in ('1', 'true', 'yes', 'on')


def resolve_secret(config: dict, *, scope: str = 'workspace', missing_exc=ValueError) -> str:
    scope_name = config.get('credential_scope') or scope
    saved = dpapi.load_secret(scope_name)
    if saved:
        return saved
    name = config.get('key_env')
    value = os.getenv(name, '') if name else ''
    if name and not value:
        raise missing_exc('模型凭据环境变量未配置，请在模型设置中保存 API 密钥或配置环境变量')
    return value


def probe_connection(config: dict, *, api_key_override: str | None = None, scope: str = 'workspace', failure_cls=ValueError) -> dict:
    key = (api_key_override or '').strip() or resolve_secret(config, scope=scope, missing_exc=failure_cls)
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    payload = {
        'model': config['model'],
        'messages': [{'role': 'user', 'content': 'Reply with OK'}],
        'max_tokens': 16,
        'temperature': 0,
        'stream': False,
    }
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=False,
            trust_env=trust_system_proxy(config),
        ) as client:
            response = client.post(config['endpoint'], headers=headers, json=payload)
            if response.status_code != 200:
                raise failure_cls(f'模型服务返回 HTTP {response.status_code}，请检查端点、模型名或密钥')
            body = json.loads(response.content[:100_000])
            content = body['choices'][0]['message']['content']
            if not isinstance(content, str):
                raise ValueError()
            return {
                'ok': True,
                'latency_ms': round((time.monotonic() - started) * 1000),
                'model': body.get('model') or config['model'],
            }
    except httpx.HTTPError:
        raise failure_cls('无法连接模型服务或请求超时，请检查端点地址与系统代理设置') from None
    except (ValueError, KeyError, IndexError, TypeError):
        raise failure_cls('模型服务响应不是标准 OpenAI Chat Completions JSON 格式') from None
