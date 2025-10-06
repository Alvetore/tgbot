# app/keyboards.py
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from .pricing import MESSAGE_PACKS, SUBSCRIPTION_PLANS, fmt_price, format_xtr_label
from app.config import settings


def payments_root_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Пакеты сообщений", callback_data="pay:packs")],
        [InlineKeyboardButton(text="🗓 Подписка на 30 дней", callback_data="pay:subs")],
        [InlineKeyboardButton(text="🎁 Реферальная ссылка", callback_data="ref:link")],
    ])


def message_packs_kb() -> InlineKeyboardMarkup:
    rows = []
    xmap = (getattr(settings, "xtr_price_packages", {}) or {})
    if xmap:
        title_by_qty = {}
        for sku in MESSAGE_PACKS:
            try:
                qty = int(sku.code.split(":", 1)[1])
                title_by_qty[qty] = sku.title
            except Exception:
                pass
        for qty, xtr in sorted(xmap.items()):
            title = title_by_qty.get(qty, f"+{qty} сообщений")
            rows.append([InlineKeyboardButton(
                text=format_xtr_label(title, int(xtr)),
                callback_data=f"buy:msgs:{qty}"
            )])
    else:
        for sku in MESSAGE_PACKS:
            rows.append([InlineKeyboardButton(
                text=f"{sku.title} — {fmt_price(sku.amount_minor)}",
                callback_data=f"buy:{sku.code}"
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def subscription_plans_kb() -> InlineKeyboardMarkup:
    rows = []
    xmap = (getattr(settings, "xtr_price_subs", {}) or {})
    title_by_code = {sku.code: sku.title for sku in SUBSCRIPTION_PLANS}
    if xmap:
        for code, xtr in xmap.items():
            code_norm = code if code.startswith("subs:") else f"subs:{code}"
            title = title_by_code.get(code_norm, code_norm)
            tier = code_norm.split(":", 1)[1]
            rows.append([InlineKeyboardButton(
                text=format_xtr_label(title, int(xtr)),
                callback_data=f"buy:subs:{tier}"
            )])
    else:
        for sku in SUBSCRIPTION_PLANS:
            rows.append([InlineKeyboardButton(
                text=f"{sku.title} — {fmt_price(sku.amount_minor)}",
                callback_data=f"buy:{sku.code}"
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choose_payment_method_kb(sku_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌟 Оплатить Stars", callback_data=f"paymethod:{sku_code}:stars")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"pay:back_to_skus:{sku_code}")],
    ])


# ===== Backward-compat aliases (для старого кода) =====

def kb_pay_root() -> InlineKeyboardMarkup:
    """Старое имя для корневого меню оплаты"""
    return payments_root_kb()


def kb_continue() -> InlineKeyboardMarkup:
    """Простая кнопка «Продолжить». Если стартовый код слушает другой callback, обновите здесь."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Продолжить", callback_data="continue")
    ]])
