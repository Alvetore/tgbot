from __future__ import annotations
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

router = Router(name="diag_ping")
log = logging.getLogger(__name__)

@router.callback_query(F.data == "pay:diag_ping")
async def _diag_ping(cb: CallbackQuery):
    try:
        await cb.answer("pong ✅", show_alert=False)
    except Exception:
        pass
    if cb.message:
        await cb.message.answer("pong ✅ (callback пойман)")
    log.info("DIAG_PING ok user=%s chat=%s", getattr(cb.from_user, "id", None), getattr(getattr(cb, "message", None), "chat", None))
