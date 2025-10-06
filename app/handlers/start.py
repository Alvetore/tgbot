# app/handlers/start.py
from __future__ import annotations

import time

from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.security import hash_user_id
from app.limits import ensure_user, get_limits_snapshot
from app.handlers.payments import handle_start_deeplink_ref
from app.keyboards import kb_continue, kb_pay_root

router = Router(name="start")


def _hello_text() -> str:
    return (
        "Я — Глеб, и не надейся на дружелюбие: тут без смайликов, без «как дела», без соплей.\n"
        "Хочешь — пиши, но готовься к тому, что огребёшь коротко и грубо.\n"
        "Въебал вопрос — получай ответ. Срать я хотел на твои обиды.\n"
        "Поехали, хули."
    )


def _format_time_left(reset_ts: int) -> str:
    now = int(time.time())
    dt = max(0, int(reset_ts) - now)
    h = dt // 3600
    m = (dt % 3600) // 60
    if dt <= 0:
        return "меньше минуты"
    if h == 0 and m > 0:
        return f"{m} мин"
    if h > 0 and m == 0:
        return f"{h} ч"
    return f"{h} ч {m} мин"


def _limits_text(snap: dict) -> str:
    daily = snap.get("daily_limit_remaining", 0)
    bonus = snap.get("bonus_messages", 0)
    reset_at = snap.get("counter_reset_at", 0)
    left = _format_time_left(reset_at) if reset_at else "—"
    return (
        f"Текущий лимит на сегодня: <b>{daily}</b> сообщений\n"
        f"Бонусные сообщения: <b>{bonus}</b>\n"
        f"До ежедневного обновления: <b>{left}</b>"
    )


@router.message(CommandStart())
async def cmd_start(m: Message):
    """
    /start [+ deep-link]
    Пример deep-link: /start r_<ref_hash>
    """
    # 1) Создаём/инициализируем пользователя в БД (единые лимиты)
    tg_hash = hash_user_id(m.from_user.id)
    await ensure_user(tg_hash)

    # 2) Разбираем deep-link (если есть)
    arg = ""
    if m.text:
        parts = m.text.strip().split(maxsplit=1)
        if len(parts) == 2:
            arg = parts[1].strip()
    if arg:
        try:
            await handle_start_deeplink_ref(m, arg)
        except Exception:
            pass

    # 3) Покажем привет + краткую сводку лимитов
    snap = await get_limits_snapshot(tg_hash)
    hello = _hello_text()
    limits = _limits_text(snap)
    await m.answer(
        f"{hello}\n\n{limits}",
        parse_mode="HTML",
        reply_markup=kb_pay_root(),
    )


@router.message(Command("menu"))
async def cmd_menu(m: Message):
    """
    Небольшое вспомогательное меню (покупки/лимит/пригласи друга).
    """
    await m.answer("Что делаем дальше? ", reply_markup=kb_pay_root())


# Кнопка «Проверить лимит»
@router.callback_query(F.data == "limits:show")
async def cb_limits_show(cb: types.CallbackQuery):
    tg_hash = hash_user_id(cb.from_user.id)
    snap = await get_limits_snapshot(tg_hash)
    try:
        await cb.answer()
    except Exception:
        pass
    await cb.message.answer(_limits_text(snap))

   
# Мостик для нового формата: paymethod:<sku>:<method>
@router.callback_query(F.data.contains("paymethod:"))
async def _bridge_paymethod(cb: types.CallbackQuery):
    # отвечаем сразу, чтобы не висела крутилка
    try:
        await cb.answer()
    except Exception:
        pass
    # перекидываем в основной хендлер из payments.py
    await payments_handlers.choose_method(cb)

# Мостики для легаси-форматов: pay_stars:/pay_rub:
@router.callback_query(F.data.startswith("pay_stars:"))
async def _bridge_legacy_stars(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    await payments_handlers.legacy_pay_stars(cb)

@router.callback_query(F.data.startswith("pay_rub:"))
async def _bridge_legacy_rub(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    await payments_handlers.legacy_pay_rub(cb)