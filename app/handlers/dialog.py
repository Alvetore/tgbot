# -*- coding: utf-8 -*-
from aiogram import Router, F
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionSender

from ..security import hash_user_id
from ..prefilter import rate_limit_ok, is_gibberish
from ..limits import ensure_user, consume_one_message
from ..llm import chat as llm_chat
from ..prompts import gleb_SYSTEM_PROMPT as GLEB_SYSTEM_PROMPT
from ..limit_notice import pick_limit_notice
from ..db import conv_load_history, conv_append

router = Router(name="dialog")

_HISTORY_KEEP = 8

def _clamp(s: str, n: int = 800) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "..."

def _shorten_sentences(reply: str, max_sentences: int = 3) -> str:
    r = (reply or "").strip()
    if not r:
        return r
    import re
    parts = re.split(r"(?<=[\.\!\?])\s+", r)
    if len(parts) > max_sentences:
        return " ".join(parts[:max_sentences]).strip()
    return r

async def _ensure_russian(reply: str) -> str:
    if not reply:
        return reply
    # Если весь ответ латиницей — просим LLM переписать по-русски
    import re
    if re.search(r"[A-Za-z]{3,}", reply) and not re.search(r"[А-Яа-яЁё]", reply):
        sys = "Перепиши ответ СТРОГО на русском языке. Без транслита и англицизмов. Коротко."
        fixed = await llm_chat([{"role":"system","content":sys},{"role":"user","content":reply}], max_tokens=120, temperature=0.3)
        return (fixed or reply).strip()
    return reply

@router.message(F.text)
async def on_dialog(msg: Message):
    uid = msg.from_user.id
    user_text = (msg.text or "").strip()
    tg_hash = hash_user_id(uid)

    if not user_text:
        return

    # Prefilter: частота и бессмыслица
    ok_rate, why = rate_limit_ok(uid, msg.date.timestamp() if msg.date else None)
    if not ok_rate:
        await msg.answer("Ты заебал так быстро писать.")
        return
    if is_gibberish(user_text):
        await msg.answer("Даже слово написать не можешь, хуйня безграмотная.")
        return

    await ensure_user(tg_hash)

    # Лимит: если нет сообщений — отшиваем нейтральным пинком
    ok = await consume_one_message(tg_hash)
    if not ok:
        notice = await pick_limit_notice(tg_hash)
        await msg.answer(notice)
        return

    # История + системный промпт
    hist = await conv_load_history(tg_hash, limit=_HISTORY_KEEP)
    messages = [{"role":"system","content":GLEB_SYSTEM_PROMPT.strip()}]
    for m in hist:
        role = m.get("role")
        content = _clamp(m.get("content",""))
        if role in ("user","assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role":"user","content":_clamp(user_text)})

    # Генерация
    async with ChatActionSender.typing(msg.chat.id, msg.bot):
        reply = await llm_chat(messages, max_tokens=140, temperature=0.6)

    # Постобработка
    reply = _shorten_sentences(reply, max_sentences=3)
    reply = await _ensure_russian(reply)

    # Сохранение истории
    await conv_append(tg_hash, "user", user_text, keep=_HISTORY_KEEP)
    await conv_append(tg_hash, "assistant", reply, keep=_HISTORY_KEEP)

    await msg.answer(reply)
