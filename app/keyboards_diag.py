from __future__ import annotations
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def diag_ping_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧪 ПИНГ Stars CB", callback_data="pay:diag_ping")],
    ])
