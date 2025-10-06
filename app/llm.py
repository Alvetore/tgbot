# app/llm.py
import asyncio
import json
import re
from typing import Any, Dict, List

import aiohttp

from .config import settings
from .prompts import CLASSIFIER_PROMPT

API_URL = "https://api.deepseek.com/chat/completions"


async def _post(payload: Dict[str, Any]) -> str:
    """
    Безопасный POST с ретраями и тайм-аутом.
    Возвращает content первой choice.
    """
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    # 3 попытки с простым backoff
    for attempt in range(3):
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(API_URL, headers=headers, json=payload) as r:
                    r.raise_for_status()
                    data = await r.json()
                    return data["choices"][0]["message"]["content"]
        except Exception:
            if attempt == 2:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))
    # теоретически недостижимо
    raise RuntimeError("DeepSeek API failed")


async def chat(messages: List[Dict[str, str]], max_tokens: int = 120, temperature: float = 0.65) -> str:
    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    return await _post(payload)


def _safe_json_extract(text: str) -> str:
    # Если модель вернула что-то вокруг JSON — пытаемся выдрать {...}
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


async def classify(text: str) -> Dict[str, Any]:
    """
    Возвращает dict вида {'label': '...', 'confidence': 0.xx}.
    При ошибке — label='normal' (fail-open).
    """
    messages = [
        {"role": "system", "content": CLASSIFIER_PROMPT.strip()},
        {"role": "user", "content": text.strip()[:1000]},
    ]
    try:
        raw = await chat(messages, max_tokens=120, temperature=0)
        js = _safe_json_extract(raw)
        obj = json.loads(js)
        label = str(obj.get("label", "normal")).lower().strip()
        valid = {"crisis", "illegal", "unsafe", "boundaries", "pro_advice", "romance", "normal"}
        if label not in valid:
            label = "normal"
        return {"label": label, "confidence": float(obj.get("confidence", 0.0))}
    except Exception:
        return {"label": "normal", "confidence": 0.0}


# --- Удобная обёртка для канал-модуля (и вообще) ---

async def ask(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 400,
    temperature: float = 0.6,
) -> str:
    """
    Удобная обёртка: system + user → ответ.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return await chat(messages, max_tokens=max_tokens, temperature=temperature)
