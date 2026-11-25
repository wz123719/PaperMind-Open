"""Bounded JSON chat-completions transport. No tools or provider-side file access."""
import asyncio
import json
import re
import time
from urllib.parse import urlsplit
import httpx
from .llm_provider import resolve_secret, strip_json_fence, trust_system_proxy

DEEPSEEK_ENDPOINT = 'https://api.deepseek.com/chat/completions'
DEEPSEEK_MODEL = 'deepseek-flash'
DEFAULT_KEY_ENV = 'PAPERMIND_MODEL_API_KEY'


class ReadingFailure(ValueError):
    def __init__(self, message, *, usage=None):
        super().__init__(message)
        self.usage = usage


def validate_config(value):
    endpoint = value.get('endpoint', '').strip()
    model = value.get('model', '').strip()
    key_env = value.get('key_env', '').strip()
    url = urlsplit(endpoint)
    if (url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password
            or url.query or url.fragment or len(endpoint) > 1000
            or (url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'))):
        raise ReadingFailure('端点须为HTTPS地址或本机HTTP地址，不可包含凭据、查询或片段')
    if not model or len(model) > 150 or any(ord(c) < 32 for c in model):
        raise ReadingFailure('请填写有效模型名称')
    if key_env and not re.fullmatch(r'[A-Z][A-Z0-9_]{2,100}', key_env):
        raise ReadingFailure('凭据环境变量名无效')
    result = {'endpoint': endpoint, 'model': model, 'key_env': key_env}
    if 'use_system_proxy' in value:
        result['use_system_proxy'] = bool(value['use_system_proxy'])
    return result


def credential(config, scope='workspace'):
    return resolve_secret(config, scope=scope, missing_exc=ReadingFailure)


def is_deepseek_flash(config):
    endpoint = urlsplit(config['endpoint'])
    return endpoint.scheme == 'https' and endpoint.hostname == 'api.deepseek.com' and config['model'] == DEEPSEEK_MODEL


async def _call(config, messages, cancelled):
    key = credential(config, scope=config.get('credential_scope', 'workspace'))
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    payload = {'model': config['model'], 'messages': messages, 'temperature': 0.2,
               'max_tokens': 3000, 'stream': False}
    if is_deepseek_flash(config):
        payload.update(response_format={'type': 'json_object'}, thinking={'type': 'disabled'})
        payload['max_tokens'] = 6000
    if config.get('max_output_tokens') is not None:
        payload['max_tokens'] = config['max_output_tokens']

    async def request():
        async with httpx.AsyncClient(timeout=httpx.Timeout(95.0, connect=10.0),
                                     follow_redirects=False,
                                     trust_env=trust_system_proxy(config)) as client:
            async with client.stream('POST', config['endpoint'], headers=headers, json=payload) as response:
                if response.status_code != 200:
                    raise ReadingFailure(f'模型服务HTTP {response.status_code}；响应正文未记录')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 400_000:
                        raise ReadingFailure('模型响应超过400KB上限')
                try:
                    body = json.loads(raw)
                    choice = body['choices'][0]
                    finish_reason = choice.get('finish_reason')
                    content = choice['message']['content']
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    raise ReadingFailure('模型服务响应协议不匹配') from None
                if finish_reason == 'length':
                    raise ReadingFailure('精读输出达到模型长度上限，JSON 可能被截断', usage=body.get('usage'))
                if finish_reason not in (None, 'stop'):
                    raise ReadingFailure('模型未正常完成精读输出')
                if not isinstance(content, str) or not content.strip():
                    raise ReadingFailure('模型返回空精读正文，请重试')
                cleaned = strip_json_fence(content)
                return (cleaned, body.get('usage')) if config.get('return_usage') else cleaned

    task = asyncio.create_task(request())
    start = time.monotonic()
    try:
        while not task.done():
            if cancelled():
                raise ReadingFailure('精读已失去租约，已取消模型请求')
            if time.monotonic() - start > 90:
                raise ReadingFailure('模型请求超过90秒硬时限')
            await asyncio.wait({task}, timeout=.2)
        return task.result()
    except httpx.HTTPError:
        raise ReadingFailure('模型连接失败或超时；请检查服务配置与代理设置') from None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def complete(config, messages, cancelled):
    return asyncio.run(_call(config, messages, cancelled))
