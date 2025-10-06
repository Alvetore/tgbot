# app/handlers/admin_stats.py
import time
from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from ..config import settings
from ..db import get_active_counts, get_total_users_count, get_user_stats_30d
from ..security import hash_user_id
from ..limits import get_limits_snapshot, add_bonus_messages
from ..db import get_user_flag, set_user_flag  # grace_reset

router = Router()
_START_TS = int(time.time())

# ---------- Утилиты ----------

def _is_admin(user_id: int) -> bool:
    try:
        ids = set(int(x) for x in settings.admin_ids)
    except Exception:
        ids = set()
    return int(user_id) in ids

async def _safe_edit(message, text: str, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None):
    """Безопасное редактирование текста/клавиатуры (не шумим на 'message is not modified')."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            try:
                await message.edit_reply_markup(reply_markup=reply_markup)
            except TelegramBadRequest as e2:
                if "message is not modified" in str(e2).lower():
                    return
                raise
        else:
            raise

def _kb_stats() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить", callback_data="admin:refresh")
    kb.adjust(1)
    return kb.as_markup()

def _fmt_bool(b: bool) -> str:
    return "✅" if b else "—"

def _fmt_top(rows: list[dict], limit: int = 10) -> str:
    if not rows:
        return "_нет данных_"
    lines = []
    for i, row in enumerate(rows[:limit], 1):
        tg_hash = (row.get("tg_hash") or "")[:8]
        cnt = int(row.get("msg_30d", 0) or 0)
        has_p = bool(row.get("has_purchases", False))
        has_s = bool(row.get("has_subscription", False))
        avg = cnt / 30.0 if cnt else 0.0
        lines.append(
            f"{i:>2}. {tg_hash} — {cnt} msg/30d (~{avg:.1f}/d)  "
            f"Покупки: {_fmt_bool(has_p)}  Подписка: {_fmt_bool(has_s)}"
        )
    return "\n".join(lines)

async def _stats_text() -> str:
    dau, wau, mau = await get_active_counts()
    total = await get_total_users_count()
    top = await get_user_stats_30d(limit=20)
    lines = [
        f"*Пользователи*",
        f"DAU: *{dau}*   WAU: *{wau}*   MAU: *{mau}*   Total: *{total}*",
        "",
        "*Топ / активность за 30 дней*",
        _fmt_top(top, limit=10),
    ]
    return "\n".join(lines)

def _parse_target(arg: str | None) -> str | None:
    if not arg:
        return None
    s = arg.strip()
    if s.isdigit():
        return hash_user_id(int(s))
    # допускаем префикс ref_
    if s.startswith("ref_"):
        s = s[4:]
    # простая валидация для tg_hash (строки от security/sha-hex)
    return s if 6 <= len(s) <= 128 else None

# ---------- Хендлеры статистики ----------

@router.message(Command("admin"))
@router.message(Command("stats"))
async def admin_stats_entry(msg: Message):
    if not _is_admin(msg.from_user.id):
        await msg.answer("Эта команда только для админов.")
        return
    text = await _stats_text()
    await msg.answer(text, reply_markup=_kb_stats(), parse_mode="Markdown")

@router.callback_query(F.data == "admin:refresh")
async def admin_refresh(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        await cb.answer("Недостаточно прав", show_alert=True)
        return
    text = await _stats_text()
    await _safe_edit(cb.message, text, reply_markup=_kb_stats(), parse_mode="Markdown")
    await cb.answer("Обновлено")

# ---- бонусы/грейс — (оставьте как было у вас, ниже только пример) ----

@router.message(Command("grant"))
async def admin_grant(msg: Message, command: CommandObject):
    if not _is_admin(msg.from_user.id):
        return
    parts = (command.args or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await msg.answer("Неверные параметры. Пример: <code>/grant 123456789 50</code>", parse_mode="HTML")
        return
    tg_hash = _parse_target(parts[0])
    amount = int(parts[1])
    if not tg_hash:
        await msg.answer("Неверные параметры. Пример: <code>/grant 123456789 50</code>", parse_mode="HTML")
        return
    await add_bonus_messages(tg_hash, amount)
    snap = await get_limits_snapshot(tg_hash)
    paid = snap.get("paid_messages", 0) if snap else "?"
    await msg.answer(f"Готово. Начислено: <b>{amount}</b>. Текущие paid_messages: <b>{paid}</b>", parse_mode="HTML")

@router.message(Command("grace_reset"))
async def admin_grace_reset(msg: Message, command: CommandObject):
    if not _is_admin(msg.from_user.id):
        return
    arg = (command.args or "").strip()
    tg_hash = _parse_target(arg)
    if not tg_hash:
        await msg.answer("Неверные параметры. Пример: <code>/grace_reset 123456789</code>", parse_mode="HTML")
        return
    await set_user_flag(tg_hash, "grace_reset", True)
    await msg.answer("Флаг grace_reset выставлен.", parse_mode="HTML")

# ---------- Обработчик ошибок (совместимость разных версий aiogram) ----------

@router.errors()
async def suppress_not_modified(event=None, exception=None):
    """Тише для 'message is not modified' — поддерживаем разные сигнатуры вызова."""
    if isinstance(exception, TelegramBadRequest) and "message is not modified" in str(exception).lower():
        return True
    return False
