"""Bounded JSON chat-completions transport. No tools or provider-side file access."""
import asyncio
import json
import time
import httpx
from .reading_provider import ReadingFailure, credential, is_deepseek_flash

async def _call(config, messages, cancelled):
    key = credential(config)
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    payload = {'model':config['model'], 'messages':messages, 'temperature':0.2,
               'max_tokens':3000, 'stream':False}
    if is_deepseek_flash(config):
        payload.update(response_format={'type':'json_object'}, thinking={'type':'disabled'})
    async def request():
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=10),
                                     follow_redirects=False, trust_env=False) as client:
            async with client.stream('POST', config['endpoint'], headers=headers, json=payload) as response:
                if response.status_code != 200:
                    raise ReadingFailure(f'模型服务HTTP {response.status_code}；响应正文未记录')
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 400_000:
                        raise ReadingFailure('模型响应超过400KB上限')
                try:
                    data = json.loads(raw)
                    choice = data['choices'][0]
                    if choice.get('finish_reason') not in (None, 'stop'):
                        raise ReadingFailure('模型输出未完整结束')
                    return choice['message']['content'], data.get('usage')
                except (ValueError, KeyError, IndexError, TypeError):
                    raise ReadingFailure('模型服务响应协议不匹配') from None
    task = asyncio.create_task(request())
    start = time.monotonic()
    try:
        while not task.done():
            if cancelled():
                raise ReadingFailure('翻译已失去租约，已取消模型请求')
            if time.monotonic() - start > 90:
                raise ReadingFailure('模型请求超过90秒硬时限')
            await asyncio.wait({task}, timeout=.2)
        return task.result()
    except httpx.HTTPError:
        raise ReadingFailure('模型连接失败或超时；请检查服务配置') from None
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

def complete(config, messages, cancelled):
    return asyncio.run(_call(config, messages, cancelled))
