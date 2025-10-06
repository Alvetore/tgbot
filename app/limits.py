# app/limits.py — ЕДИНАЯ РЕАЛИЗАЦИЯ
from __future__ import annotations

import time
import json
from typing import Dict, Optional

from .config import settings
from .db import open_db, get_user_kv, set_user_kv


# -------- Конфигурация квот --------

_KV_LIMITS_MAP = "limits:daily_map"  # JSON вида {"FREE":10,"PLUS":30,"PREMIUM":100}


async def get_quota_map() -> Dict[str, int]:
    """
    Источник приоритетов:
    1) kv['limits:daily_map'] (можно менять «на лету»)
    2) settings.daily_quota_map из .env (DAILY_QUOTA_MAP='{"FREE":10,"PLUS":30,"PREMIUM":100}')
    3) fallback: FREE_DAILY_LIMIT / PAID_DAILY_LIMIT
    """
    # 1) KV
    kv = await get_user_kv("global", _KV_LIMITS_MAP)
    if kv:
        try:
            obj = json.loads(kv)
            if isinstance(obj, dict):
                return {k.upper(): int(v) for k, v in obj.items()}
        except Exception:
            pass

    # 2) ENV map
    if settings.daily_quota_map:
        try:
            return {k.upper(): int(v) for k, v in settings.daily_quota_map.items()}
        except Exception:
            pass

    # 3) Fallback
    return {
        "FREE": int(settings.free_daily_limit),
        "PLUS": int(settings.paid_daily_limit),
        "PREMIUM": int(settings.paid_daily_limit),
    }


async def set_quota_map(map_: Dict[str, int]) -> None:
    """
    Устанавливает карту квот «на лету». Пример:
    await set_quota_map({"FREE": 12, "PLUS": 30, "PREMIUM": 100})
    """
    safe = {str(k).upper(): int(v) for k, v in map_.items()}
    await set_user_kv("global", _KV_LIMITS_MAP, json.dumps(safe, ensure_ascii=False))


def _next_midnight_ts(now_ts: int | None = None) -> int:
    """
    Возвращает Unix-время ближайшей полуночи (UTC-нейтрально).
    """
    now = int(now_ts or time.time())
    # вычислим локально: округлим до дней
    # (точная TZ-полночь не критична для счётчика; можно заменить на пользовательскую TZ при желании)
    t = time.gmtime(now)
    midnight = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, t.tm_wday, t.tm_yday, t.tm_isdst))) + 24 * 3600
    return midnight


async def _compute_user_daily_limit(subscription_tier: str, subscription_until: Optional[int]) -> int:
    """
    Вычисляет дневной лимит для пользователя, учитывая подписку.
    Если подписка активна (until > now) — используем её tier (если он есть в карте, иначе PAID).
    """
    m = await get_quota_map()
    tier = (subscription_tier or "FREE").upper()
    now = int(time.time())
    if subscription_until and int(subscription_until) > now:
        # активная подписка
        if tier in m:
            return int(m[tier])
        return int(m.get("PAID", m.get("PLUS", settings.paid_daily_limit)))
    # без подписки
    if tier in m:
        return int(m[tier])
    return int(m.get("FREE", settings.free_daily_limit))


# -------- Публичное API --------

async def ensure_user(tg_hash: str) -> None:
    """
    Создаёт запись о пользователе при первом входе.
    Если наступила новая «полночь» — сбрасывает дневной лимит согласно карте квот.
    """
    db = await open_db()
    try:
        cur = await db.execute("SELECT tg_hash, counter_reset_at, subscription_tier, subscription_until, daily_limit_remaining FROM users WHERE tg_hash=? LIMIT 1", (tg_hash,))
        row = await cur.fetchone()
        await cur.close()
        now = int(time.time())

        if not row:
            # первый вход — установим лимит согласно карте
            # default tier = FREE
            tier = "FREE"
            limit = await _compute_user_daily_limit(tier, None)
            reset_at = _next_midnight_ts(now)
            await db.execute(
                "INSERT INTO users (tg_hash, created_at, counter_reset_at, subscription_tier, subscription_until, daily_limit_remaining) VALUES (?,?,?,?,?,?)",
                (tg_hash, now, reset_at, tier, None, int(limit)),
            )
            await db.commit()
            return

        # существующий: проверим необходимость сброса
        _, counter_reset_at, tier, sub_until, daily_left = row
        if not counter_reset_at or int(counter_reset_at) <= now:
            limit = await _compute_user_daily_limit(tier, sub_until)
            reset_at = _next_midnight_ts(now)
            await db.execute(
                "UPDATE users SET daily_limit_remaining=?, counter_reset_at=? WHERE tg_hash=?",
                (int(limit), int(reset_at), tg_hash),
            )
            await db.commit()
    finally:
        await db.close()


async def consume_one_message(tg_hash: str) -> bool:
    """
    Списывает 1 сообщение: сначала из дневного лимита, потом из bonus_messages.
    Возвращает True, если удалось списать.
    """
    await ensure_user(tg_hash)
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT daily_limit_remaining, bonus_messages FROM users WHERE tg_hash=? LIMIT 1",
            (tg_hash,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return False

        daily, bonus = int(row[0] or 0), int(row[1] or 0)
        if daily > 0:
            await db.execute(
                "UPDATE users SET daily_limit_remaining=daily_limit_remaining-1 WHERE tg_hash=?",
                (tg_hash,),
            )
            await db.commit()
            return True

        if bonus > 0:
            await db.execute(
                "UPDATE users SET bonus_messages=bonus_messages-1 WHERE tg_hash=?",
                (tg_hash,),
            )
            await db.commit()
            return True

        return False
    finally:
        await db.close()


async def add_bonus_messages(tg_hash: str, amount: int) -> None:
    """Начисляет пользователю amount сообщений в bonus_messages."""
    if not amount or amount <= 0:
        return
    await ensure_user(tg_hash)
    db = await open_db()
    try:
        await db.execute(
            "UPDATE users SET bonus_messages=bonus_messages+? WHERE tg_hash=?",
            (int(amount), tg_hash),
        )
        await db.commit()
    finally:
        await db.close()


async def get_limits_snapshot(tg_hash: str) -> dict:
    """
    Возвращает:
      {
        "daily_limit_remaining": int,
        "bonus_messages": int,
        "counter_reset_at": int,
        "subscription_tier": str,
        "subscription_until": int|None
      }
    """
    await ensure_user(tg_hash)
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT daily_limit_remaining, bonus_messages, counter_reset_at, subscription_tier, subscription_until FROM users WHERE tg_hash=? LIMIT 1",
            (tg_hash,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return {}
        return {
            "daily_limit_remaining": int(row[0] or 0),
            "bonus_messages": int(row[1] or 0),
            "counter_reset_at": int(row[2] or 0),
            "subscription_tier": (row[3] or "FREE"),
            "subscription_until": (row[4] if row[4] is not None else None),
        }
    finally:
        await db.close()


# --- Утилиты для «быстрой регулировки» ---

async def set_user_tier(tg_hash: str, tier: str, subscription_until: Optional[int] = None) -> None:
    """
    Устанавливает пользователю тариф (FREE/PLUS/PREMIUM/и т.п.) и срок подписки (unix-ts).
    Следующий сброс пересчитает дневной лимит автоматически.
    """
    tier = (tier or "FREE").upper()
    db = await open_db()
    try:
        await db.execute(
            "UPDATE users SET subscription_tier=?, subscription_until=? WHERE tg_hash=?",
            (tier, subscription_until, tg_hash),
        )
        await db.commit()
    finally:
        await db.close()


async def force_reset_today_limit(tg_hash: str) -> None:
    """
    Принудительно «пересобирает» лимит сейчас (для админских нужд).
    """
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT subscription_tier, subscription_until FROM users WHERE tg_hash=? LIMIT 1",
            (tg_hash,),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return
        tier, sub_until = row
        limit = await _compute_user_daily_limit(tier, sub_until)
        reset_at = _next_midnight_ts()
        await db.execute(
            "UPDATE users SET daily_limit_remaining=?, counter_reset_at=? WHERE tg_hash=?",
            (int(limit), int(reset_at), tg_hash),
        )
        await db.commit()
    finally:
        await db.close()
