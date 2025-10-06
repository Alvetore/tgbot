# app/limit_notice_llm.py
from typing import List, Dict
from .llm import chat as llm_chat

SYSTEM_PROMPT = """
Сгенерируй ОДНУ короткую нейтральную фразу-паузу по-русски (6–14 слов),
чтобы вежливо остановить разговор СЕЙЧАС и дать понять, что продолжим ПОТОМ.
Без эмодзи. Без ссылок на правила, лимиты и кнопки. Одно предложение.
Примеры тона (не копируй):
— На этом остановимся, продолжим позже.
— Поставим паузу и вернёмся к теме позже.
— Сделаем перерыв и продолжим в другое время.
"""

async def build_contextual_pause(last_messages: List[Dict], max_tokens: int = 40) -> str | None:
    """
    Возвращает одну короткую фразу-«мостик» или None при ошибке.
    Контекст последних сообщений передаётся только для стилистики, а не для продолжения темы.
    """
    tail = last_messages[-6:] if last_messages else []
    messages = [{"role": "system", "content": SYSTEM_PROMPT.strip()}]
    messages.extend(tail)
    try:
        text = await llm_chat(messages, max_tokens=max_tokens, temperature=0.35)
        text = (text or "").strip()
        first_line = text.splitlines()[0].strip(" \t\"'`")
        if len(first_line) > 160:
            first_line = first_line[:160].rstrip() + "…"
        return first_line
    except Exception:
        return None
