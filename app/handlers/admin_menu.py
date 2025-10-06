# app/handlers/admin_menu.py
# -*- coding: utf-8 -*-
import time
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.config import settings
from app.db import open_db  # используем твою БД
# Ничего из channel_* не импортируем

router = Router(name="admin_menu")

# ---------- util ----------

def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in set(settings.admin_ids or [])
    except Exception:
        return False

def _menu_text() -> str:
    return (
        "Админ-меню:\n"
        "• /ping — пинг\n"
        "• /astats — базовая статистика (пользователи, сообщения, фидбек)\n"
        "• /newfb — последние 10 фидбеков\n"
        "• /health — быстрая проверка окружения\n"
    )

def _fmt_ts(ts: int | float | None) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ts)

# ---------- меню ----------

@router.message(CommandStart())
async def cmd_start(m: Message):
    if not _is_admin(m.from_user.id):
        return
    await m.answer(_menu_text())

@router.message(F.text.lower() == "/admin")
async def cmd_admin(m: Message):
    if not _is_admin(m.from_user.id):
        return
    await m.answer(_menu_text())

@router.message(F.text.lower() == "/ping")
async def cmd_ping(m: Message):
    if not _is_admin(m.from_user.id):
        return
    await m.answer("pong")

# ---------- статистика ----------

@router.message(F.text.lower() == "/astats")
async def cmd_astats(m: Message):
    if not _is_admin(m.from_user.id):
        return

    now = int(time.time())
    day_ago = now - 86400

    db = await open_db()
    try:
        # всего пользователей
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone() or [0])[0]
        await cur.close()

        # активных за 24ч (по сообщениям в conv_buffer)
        cur = await db.execute(
            "SELECT COUNT(DISTINCT tg_hash) FROM conv_buffer WHERE created_at >= ?",
            (day_ago,),
        )
        active_24h = (await cur.fetchone() or [0])[0]
        await cur.close()

        # всего сообщений в буфере
        cur = await db.execute("SELECT COUNT(*) FROM conv_buffer")
        total_msgs = (await cur.fetchone() or [0])[0]
        await cur.close()

        # фидбек: всего и за 7 дней
        week_ago = now - 7 * 86400
        cur = await db.execute("SELECT COUNT(*) FROM feedback")
        total_fb = (await cur.fetchone() or [0])[0]
        await cur.close()

        cur = await db.execute(
            "SELECT COUNT(*) FROM feedback WHERE created_at >= ?",
            (week_ago,),
        )
        fb_7d = (await cur.fetchone() or [0])[0]
        await cur.close()

        text = (
            "<b>Сводная статистика</b>\n"
            f"Пользователи: <b>{total_users}</b>\n"
            f"Активны за 24ч: <b>{active_24h}</b>\n"
            f"Сообщений (conv_buffer): <b>{total_msgs}</b>\n"
            f"Фидбеков всего: <b>{total_fb}</b>\n"
            f"Фидбеков за 7д: <b>{fb_7d}</b>\n"
        )
        await m.answer(text)
    finally:
        await db.close()

# ---------- новые фидбеки ----------

@router.message(F.text.lower() == "/newfb")
async def cmd_newfb(m: Message):
    if not _is_admin(m.from_user.id):
        return

    db = await open_db()
    try:
        # последние 10 фидбеков
        cur = await db.execute(
            "SELECT id, tg_hash, created_at, blob FROM feedback ORDER BY id DESC LIMIT 10"
        )
        rows = await cur.fetchall()
        await cur.close()

        if not rows:
            await m.answer("Новых фидбеков нет.")
            return

        lines = ["<b>Последние фидбеки:</b>"]
        for row in rows:
            fid, tg_hash, created_at, blob = row
            try:
                # blob -> text (без расшифровки, в твоей БД уже просто текст/или шифр фёрнет — тогда будет нечитаемо)
                text = (blob or b"").decode("utf-8", errors="ignore")
            except Exception:
                text = "(не удалось декодировать)"
            # обрежем тело
            text_short = text.strip().replace("\n", " ")
            if len(text_short) > 160:
                text_short = text_short[:160].rstrip() + "…"
            lines.append(
                f"#{fid} · {_fmt_ts(created_at)} · hash={tg_hash}\n{text_short}"
            )

        await m.answer("\n".join(lines))
    finally:
        await db.close()

# ---------- health ----------

@router.message(F.text.lower() == "/health")
async def cmd_health(m: Message):
    if not _is_admin(m.from_user.id):
        return

    problems = []

    # токены
    if not (settings.bot_token or "").strip():
        problems.append("BOT_TOKEN пуст")
    if not (settings.admin_bot_token or "").strip():
        problems.append("ADMIN_BOT_TOKEN пуст")

    # админы
    if not settings.admin_ids:
        problems.append("ADMIN_IDS пуст")

    # доступ к БД
    db_ok = True
    try:
        db = await open_db()
        await db.execute("SELECT 1")
    except Exception as e:
        db_ok = False
        problems.append(f"DB fail: {type(e).__name__}")
    finally:
        try:
            await db.close()
        except Exception:
            pass

    ok = not problems and db_ok
    msg = "<b>HEALTH:</b> OK" if ok else "<b>HEALTH:</b> issues:\n- " + "\n- ".join(problems or [])
    await m.answer(msg)
