# app/handlers/admin_feedback.py
from __future__ import annotations
from typing import List, Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..config import settings
from ..db import open_db, get_user_kv, set_user_kv
from ..security import decrypt_feedback

router = Router(name="admin_feedback")

def _is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in set(int(x) for x in settings.admin_ids)
    except Exception:
        return False

# ---- БД helpers ----

async def _fetch_feedback(limit: int = 10) -> List[dict]:
    """
    Читаем из таблицы feedback(tg_hash, created_at, blob).
    Возвращаем список словарей {id, tg_hash, created_at, text}.
    """
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT id, tg_hash, created_at, blob FROM feedback ORDER BY id DESC LIMIT ?",
            (int(limit),)
        )
        rows = await cur.fetchall()
        await cur.close()
        out = []
        for r in rows:
            text = decrypt_feedback(r[3])
            out.append({"id": int(r[0]), "tg_hash": r[1], "created_at": int(r[2]), "text": text})
        return out
    finally:
        await db.close()

async def _fetch_new_feedback(since_id: int) -> List[dict]:
    db = await open_db()
    try:
        cur = await db.execute(
            "SELECT id, tg_hash, created_at, blob FROM feedback WHERE id > ? ORDER BY id ASC",
            (int(since_id),)
        )
        rows = await cur.fetchall()
        await cur.close()
        out = []
        for r in rows:
            text = decrypt_feedback(r[3])
            out.append({"id": int(r[0]), "tg_hash": r[1], "created_at": int(r[2]), "text": text})
        return out
    finally:
        await db.close()

def _fmt_row(r: dict) -> str:
    user = (r.get("tg_hash") or "")[:8]
    ts = r.get("created_at") or ""
    txt = (r.get("text") or "").strip()
    if len(txt) > 400:
        txt = txt[:400] + "…"
    return f"• <b>{user}</b> — <i>{ts}</i>\n{txt}"

def _kb_more() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Показать ещё", callback_data="fb:more")
    kb.adjust(1)
    return kb.as_markup()

# ---- Команды ----

@router.message(Command("feedback"))
async def cmd_feedback(msg: Message):
    if not _is_admin(msg.from_user.id):
        await msg.answer("Недостаточно прав.")
        return
    rows = await _fetch_feedback(limit=10)
    if not rows:
        await msg.answer("🗒 Фидбэк: пока пусто.", parse_mode="HTML")
        return
    text = "🗒 <b>Последние отзывы</b>:\n\n" + "\n\n".join(_fmt_row(r) for r in rows)
    await msg.answer(text, parse_mode="HTML", reply_markup=_kb_more())

@router.callback_query(F.data == "fb:more")
async def cb_fb_more(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True); return
    rows = await _fetch_feedback(limit=20)
    text = "🗒 <b>Последние отзывы</b>:\n\n" + ("\n\n".join(_fmt_row(r) for r in rows) if rows else "—")
    await cb.message.answer(text, parse_mode="HTML", reply_markup=_kb_more())
    await cb.answer()

# Новое: только «новые» с прошлого просмотра
_KV_KEY_LAST_FB_ID = "admin:last_fb_id"

@router.message(Command("newfb"))
async def cmd_newfb(msg: Message):
    if not _is_admin(msg.from_user.id):
        await msg.answer("Недостаточно прав.")
        return
    last_raw = await get_user_kv("admin", _KV_KEY_LAST_FB_ID)
    last_id = int(last_raw) if last_raw and str(last_raw).isdigit() else 0
    rows = await _fetch_new_feedback(last_id)
    if not rows:
        await msg.answer("🆕 Новых отзывов нет.", parse_mode="HTML")
        return
    text = "🆕 <b>Новые отзывы</b>:\n\n" + "\n\n".join(_fmt_row(r) for r in rows)
    await msg.answer(text, parse_mode="HTML")
    await set_user_kv("admin", _KV_KEY_LAST_FB_ID, str(rows[-1]["id"]))

# ---- Экспортируемые хелперы для меню ----

async def feedback_list_text(limit: int = 10) -> str:
    rows = await _fetch_feedback(limit=limit)
    if not rows:
        return "🗒 Фидбэк: пока пусто."
    return "🗒 <b>Последние отзывы</b>:\n\n" + "\n\n".join(_fmt_row(r) for r in rows)

def feedback_kb():
    return _kb_more()
