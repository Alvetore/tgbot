# app/handlers/feedback.py
from __future__ import annotations

import time
import logging

from aiogram import Router, F
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..config import settings
from ..security import hash_user_id, encrypt_feedback
from ..db import open_db, get_user_kv, set_user_kv

router = Router()
log = logging.getLogger(__name__)


class FeedbackForm(StatesGroup):
    waiting_text = State()


@router.message(F.text == "/feedback")
async def fb_intro(msg: Message, state: FSMContext):
    await state.set_state(FeedbackForm.waiting_text)
    await msg.answer(
        "Напиши, пожалуйста, своё сообщение для создателей.\n"
        "Когда закончишь, отправь одним сообщением.\n\n"
        "Чтобы отменить, введи /cancel."
    )


@router.message(F.text == "/cancel")
async def fb_cancel(msg: Message, state: FSMContext):
    cur = await state.get_state()
    if cur == FeedbackForm.waiting_text:
        await state.clear()
        await msg.answer("Хорошо, отменила. Если решишься — просто введи /feedback ещё раз.")


@router.message(FeedbackForm.waiting_text, F.text)
async def fb_save(msg: Message, state: FSMContext):
    tg_hash = hash_user_id(msg.from_user.id)
    text = (msg.text or "").strip()

    # Кулдаун 60 секунд на пользователя
    key_cd = f"fb:last:{tg_hash}"
    last = await get_user_kv(tg_hash, key_cd)
    try:
        last_ts = float(last) if last else 0.0
    except Exception:
        last_ts = 0.0
    if time.time() - last_ts < 60:
        await msg.answer("Давай сделаем маленькую паузу перед следующим сообщением — минуточку 😊")
        return

    # Запись в БД
    db = await open_db()
    try:
        blob = encrypt_feedback(text)
        await db.execute(
            "INSERT INTO feedback(tg_hash, created_at, blob) VALUES(?,?,?)",
            (tg_hash, int(time.time()), blob),
        )
        await db.commit()
    finally:
        await db.close()

    # Сохраняем метку кулдауна
    await set_user_kv(tg_hash, key_cd, str(time.time()))

    # Только лог и ответ пользователю — уведомления делает админ-бот через watcher
    log.info("Feedback saved: user=%s len=%d preview=%r", tg_hash[:8], len(text), text[:40])
    await msg.answer("Спасибо! Я передала сообщение создателям.")
    await state.clear()
