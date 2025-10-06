# app/handlers/admin_limits.py
from __future__ import annotations

import json
import time
from typing import Dict, Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BotCommand

from app.config import settings
from app.db import get_user_kv, set_user_kv
from app.security import hash_user_id
from app.limits import (
    get_quota_map, set_quota_map,
    get_limits_snapshot, set_user_tier, force_reset_today_limit,
)

router = Router(name="admin_limits")

def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(int(x) for x in settings.admin_ids)
    except Exception:
        return False

@router.message(Command("quota"))
async def cmd_quota(m: Message):
    if not _is_admin(m.from_user.id):
        await m.answer("Недостаточно прав.")
        return
    qmap = await get_quota_map()
    kv_raw = await get_user_kv("global", "limits:daily_map")
    text = (
        "🧮 <b>Карта дневных квот</b>\n"
        f"<code>{json.dumps(qmap, ensure_ascii=False)}</code>\n\n"
        "KV raw (если есть):\n"
        f"<code>{kv_raw or '—'}</code>\n\n"
        "Пример установки:\n"
        "<code>/setquota {\"FREE\":12, \"PLUS\":30, \"PREMIUM\":100}</code>"
    )
    await m.answer(text, parse_mode="HTML")

@router.message(Command("setquota"))
async def cmd_setquota(m: Message):
    if not _is_admin(m.from_user.id):
        await m.answer("Недостаточно прав.")
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Нужно передать JSON: /setquota {\"FREE\":12,\"PLUS\":30}", parse_mode="HTML")
        return
    try:
        obj = json.loads(parts[1])
        await set_quota_map(obj)
        qmap = await get_quota_map()
        await m.answer(
            "✅ Квоты обновлены.\nТекущая карта:\n"
            f"<code>{json.dumps(qmap, ensure_ascii=False)}</code>\n\n"
            "Вступят в силу при ближайшем сбросе (полночь) или сразу после /forcereset для конкретного пользователя.",
            parse_mode="HTML",
        )
    except Exception as e:
        await m.answer(f"Ошибка парсинга JSON: <code>{e}</code>", parse_mode="HTML")

@router.message(Command("userlimit"))
async def cmd_userlimit(m: Message):
    if not _is_admin(m.from_user.id):
        await m.answer("Недостаточно прав.")
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Использование: /userlimit <tg_id|hash>")
        return
    raw = parts[1].strip()
    tg_hash = raw if len(raw) >= 16 else hash_user_id(int(raw))
    snap = await get_limits_snapshot(tg_hash)
    await m.answer(
        "📊 <b>Лимиты пользователя</b>\n"
        f"user: <code>{tg_hash[:8]}</code>\n"
        f"<code>{json.dumps(snap, ensure_ascii=False, indent=2)}</code>",
        parse_mode="HTML",
    )

@router.message(Command("settier"))
async def cmd_settier(m: Message):
    if not _is_admin(m.from_user.id):
        await m.answer("Недостаточно прав.")
        return
    parts = (m.text or "").split()
    if len(parts) < 3:
        await m.answer("Использование: /settier <tg_id|hash> <tier> [days]\nПример: /settier 905244203 PREMIUM 60")
        return
    ident, tier = parts[1], parts[2].upper()
    days = int(parts[3]) if len(parts) > 3 else 30
    tg_hash = ident if len(ident) >= 16 else hash_user_id(int(ident))
    until = int(time.time()) + days * 24 * 3600
    await set_user_tier(tg_hash, tier, subscription_until=until)
    await m.answer(f"✅ Установлен tier={tier}, срок={days} дней для user={tg_hash[:8]}.\n"
                   f"Новые дневные квоты подтянутся при сбросе (или /forcereset).")

@router.message(Command("forcereset"))
async def cmd_forcereset(m: Message):
    if not _is_admin(m.from_user.id):
        await m.answer("Недостаточно прав.")
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Использование: /forcereset <tg_id|hash>")
        return
    raw = parts[1].strip()
    tg_hash = raw if len(raw) >= 16 else hash_user_id(int(raw))
    await force_reset_today_limit(tg_hash)
    await m.answer(f"🔄 Пересобран дневной лимит для user={tg_hash[:8]}.")
