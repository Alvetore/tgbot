# app/limit_notice.py
import random
from .prompts import LIMIT_NOTICE_VARIANTS
from .db import get_user_kv, set_user_kv

_KEY = "last_limit_idx"

async def pick_limit_notice(tg_hash: str) -> str:
    """
    Вернуть текст про лимит, отличный от предыдущего для этого пользователя.
    Индекс храним в kv как строку, чтобы не терять диапазон.
    """
    raw = await get_user_kv(tg_hash, _KEY)  # str | None
    try:
        last_idx = int(raw) if raw not in (None, "") else -1
    except Exception:
        last_idx = -1

    n = len(LIMIT_NOTICE_VARIANTS)
    choices = [i for i in range(n) if i != last_idx] or [0]
    idx = random.choice(choices)

    await set_user_kv(tg_hash, _KEY, str(idx))
    return LIMIT_NOTICE_VARIANTS[idx]
