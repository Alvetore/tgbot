# app/referrals.py
from __future__ import annotations

import os
import time
import hashlib
from typing import Optional

from .db import open_db

# ===== Параметры реферальной программы =====
REF_BONUS = 10          # сколько сообщений даём рефереру при активации
REF_CAP = 30            # максимум бонусов сообщений за рефералку
REF_REQUIRED = 5        # сколько «засчитанных» сообщений должен написать приглашённый
REF_DEADLINE_DAYS = 7   # срок на выполнение условий
REF_SALT = os.getenv("REF_SALT", "ref_salt")  # соль для хеша deeplink-кода

# ===== Хеш пользователя для deeplink-кода (детерминированный) =====
def user_hash(user_id: int) -> str:
    """Детерминированный хеш пользователя для deeplink-кода (не PII)."""
    h = hashlib.sha256(f"{REF_SALT}:{int(user_id)}".encode("utf-8")).hexdigest()
    return h  # длина 64; при формировании ссылки можно укоротить

# ===== Публичное API «витрины» =====
async def get_or_create_code(user_id: int) -> str:
    """
    Возвращает реферальный код (хеш реферера).
    Никаких записей в БД создавать не нужно: сам код — это хеш user_id.
    """
    return user_hash(user_id)

async def accept_referral(ref_code: str, invitee_user_id: int) -> bool:
    """
    Применяет реферальный код из deeplink:
      - ref_code — это referrer_hash (хеш реферера);
      - invitee_user_id — id приглашённого (по нему строим invitee_hash).
    Делаем:
      1) set_referrer_if_empty(invitee_hash, referrer_hash) — фиксируем реферера,
      2) create_pending_referral(referrer_hash, invitee_hash) — заводим «ожидание» прогресса.
    """
    if not ref_code or not isinstance(ref_code, str):
        return False

    referrer_hash = ref_code.strip().lower()
    invitee_hash = user_hash(invitee_user_id)

    # не позволяем «пригласить самого себя»
    if referrer_hash == invitee_hash:
        return False

    await set_referrer_if_empty(invitee_hash=invitee_hash, referrer_hash=referrer_hash)
    await create_pending_referral(referrer_hash=referrer_hash, invitee_hash=invitee_hash)
    return True

# ===== НИЖЕ — ВАШИ ИСХОДНЫЕ ФУНКЦИИ (без изменений по логике) =====

async def set_referrer_if_empty(invitee_hash: str, referrer_hash: str):
    db = await open_db()
    try:
        cur = await db.execute("SELECT referrer_hash FROM users WHERE tg_hash=?", (invitee_hash,))
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return
        current = row[0]
        if current:
            return
        await db.execute(
            "UPDATE users SET referrer_hash=? WHERE tg_hash=?",
            (referrer_hash, invitee_hash)
        )
        await db.commit()
    finally:
        await db.close()

async def create_pending_referral(referrer_hash: str, invitee_hash: str):
    now = int(time.time())
    expires = now + REF_DEADLINE_DAYS * 24 * 3600
    db = await open_db()
    try:
        # не создаём, если юзер уже есть
        cur = await db.execute("SELECT tg_hash FROM users WHERE tg_hash=?", (invitee_hash,))
        existing_user = await cur.fetchone()
        await cur.close()
        if existing_user:
            # допустимо — всё равно поставим pending, если ещё нет записи
            pass

        cur = await db.execute("SELECT id FROM referrals WHERE invitee_hash=?", (invitee_hash,))
        existing_ref = await cur.fetchone()
        await cur.close()
        if existing_ref:
            return

        await db.execute(
            "INSERT INTO referrals(referrer_hash, invitee_hash, created_at, status, progress_count, expires_at) "
            "VALUES(?,?,?,?,?,?)",
            (referrer_hash, invitee_hash, now, "pending", 0, expires)
        )
        await db.commit()
    finally:
        await db.close()

async def on_counted_message(invitee_hash: str):
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT id, referrer_hash, progress_count, status, expires_at "
            "FROM referrals WHERE invitee_hash=?",
            (invitee_hash,)
        )
        ref = await cur.fetchone()
        await cur.close()
        if not ref:
            return

        ref_id, referrer_hash, prog, status, expires_at = ref
        if status != "pending":
            return

        if expires_at and int(time.time()) > int(expires_at):
            await db.execute("UPDATE referrals SET status='expired' WHERE id=?", (ref_id,))
            await db.commit()
            return

        prog += 1
        await db.execute("UPDATE referrals SET progress_count=? WHERE id=?", (prog, ref_id))

        if prog >= REF_REQUIRED:
            await db.execute(
                "UPDATE referrals SET status='activated', activated_at=? WHERE id=?",
                (int(time.time()), ref_id)
            )
            # начислить рефереру, но не превысить кэп
            cur = await db.execute(
                "SELECT earned_referral_messages, bonus_messages FROM users WHERE tg_hash=?",
                (referrer_hash,)
            )
            row = await cur.fetchone()
            await cur.close()
            if row:
                earned, _ = row
                if earned < REF_CAP:
                    grant = min(REF_BONUS, REF_CAP - earned)
                    await db.execute(
                        "UPDATE users SET earned_referral_messages=earned_referral_messages+?, "
                        "bonus_messages=bonus_messages+? WHERE tg_hash=?",
                        (grant, grant, referrer_hash)
                    )

        await db.commit()
    finally:
        await db.close()

async def sweep_expired():
    db = await open_db()
    try:
        now = int(time.time())
        await db.execute(
            "UPDATE referrals SET status='expired' "
            "WHERE status='pending' AND expires_at IS NOT NULL AND expires_at < ?",
            (now,)
        )
        await db.commit()
    finally:
        await db.close()
