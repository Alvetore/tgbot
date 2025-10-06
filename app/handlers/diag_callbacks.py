from __future__ import annotations
import logging
from aiogram import Router
from aiogram.types import CallbackQuery

router = Router(name="diag_callbacks")
log = logging.getLogger(__name__)

@router.callback_query()
async def _diag_all_callbacks(cb: CallbackQuery):
    data = (cb.data or "").strip()
    chat_id = getattr(getattr(cb, "message", None), "chat", None)
    chat_id = getattr(chat_id, "id", None)

    # 1) закрываем "часики" и показываем тост
    try:
        snippet = (data[:64] + ("…" if len(data) > 64 else "")) or "<empty>"
        await cb.answer(f"cb: {snippet}", show_alert=False, cache_time=0)
    except Exception:
        pass

    # 2) лог в консоль
    log.info("DIAG_CB chat=%s user=%s data=%r", chat_id, getattr(cb.from_user, "id", None), data)

    # 3) echo в чат (чтобы ВИДЕТЬ глазами)
    try:
        if cb.message:
            await cb.message.answer(f"DBG CB: `{data or '<empty>'}`", parse_mode="Markdown")
    except Exception as e:
        log.warning("diag echo failed: %s", e)
