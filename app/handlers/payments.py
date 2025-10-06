# app/handlers/payments.py
from __future__ import annotations

import logging
import math
import time
from typing import Optional, List

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import (
    LabeledPrice,
    PreCheckoutQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from app.config import settings
from app.keyboards import (
    payments_root_kb,
    message_packs_kb,
    subscription_plans_kb,
    choose_payment_method_kb,
)
from app.pricing import resolve_sku, normalize_sku, SUBSCRIPTION_PLANS
from app import referrals
from app.limits import ensure_user, add_bonus_messages, set_user_tier
from app.security import hash_user_id

log = logging.getLogger(__name__)
router = Router(name="payments")

DEBUG_PAYMENTS = bool(getattr(settings, "DEBUG_PAYMENTS", False))


# -------------------- УТИЛИТЫ ТЕКСТА/ОТВЕТОВ --------------------

def _format_long_caption_for_code(code: str, title_fallback: str) -> str:
    """
    Возвращает многострочный текст вида:
        <Название>
        Стоимость: N XTR (примерно M ₽)      # если XTR_RUB_RATE задан в .env/config
    """
    xmap_p = (getattr(settings, "xtr_price_packages", {}) or {})
    xmap_s = (getattr(settings, "xtr_price_subs", {}) or {})
    xtr = None
    title = title_fallback

    if code.startswith("msgs:"):
        try:
            qty = int(code.split(":", 1)[1])
            x = xmap_p.get(qty)
            if x is None:
                x = xmap_p.get(str(qty))
            xtr = x
            if title is None:
                title = f"+{qty} сообщений"
        except Exception:
            pass
    elif code.startswith("subs:"):
        tier = code.split(":", 1)[1]
        x = xmap_s.get(tier) or xmap_s.get(tier.upper()) or xmap_s.get(tier.lower())
        xtr = x

    try:
        from app.pricing import format_xtr_label  # если есть
        if xtr is not None:
            tmp = format_xtr_label(title, int(xtr))
            if " — " in tmp:
                t, rest = tmp.split(" — ", 1)
                return f"{t}\nСтоимость: {rest}"
            return f"{title}\nСтоимость: {xtr} XTR"
    except Exception:
        pass

    return title


async def _safe_edit_or_send(cb: types.CallbackQuery, text: str, kb: types.InlineKeyboardMarkup):
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await cb.message.answer(text, reply_markup=kb)
        except Exception:
            pass
    try:
        await cb.answer()
    except Exception:
        pass


async def _get_bot_username(bot: types.Bot) -> Optional[str]:
    try:
        me = getattr(bot, "me", None)
        if me and getattr(me, "username", None):
            return me.username
    except Exception:
        pass
    try:
        me = await bot.get_me()
        return getattr(me, "username", None)
    except Exception:
        return None


# -------------------- РЕФЕРАЛКА --------------------

def _build_ref_link(bot_username: str, code: str) -> str:
    return f"https://t.me/{bot_username}?start={code}"


@router.callback_query(F.data == "ref:link")
async def referral_link_cb(cb: types.CallbackQuery):
    try:
        bot_username = await _get_bot_username(cb.bot)
        if not bot_username:
            await cb.answer("Не удалось получить username бота.", show_alert=True)
            return
        code = await referrals.get_or_create_code(cb.from_user.id)
        link = _build_ref_link(bot_username, code)
        await cb.message.answer("Делись ссылкой и получай бонусы:\n" + link)
        await cb.answer()
    except Exception:
        log.exception("referral_link_cb failed")
        await cb.answer("Не получилось выдать ссылку, попробуйте позже.", show_alert=True)


async def handle_start_deeplink_ref(message: types.Message, code: str) -> bool:
    try:
        if not code or not code.strip():
            await message.answer("Некорректная реферальная ссылка.")
            return False
        ok = await referrals.accept_referral(ref_code=code.strip(), invitee_user_id=message.from_user.id)
        if ok:
            await message.answer("Реферальная ссылка применена ✅ Спасибо!")
            return True
        await message.answer("Реферальная ссылка распознана, но применить не удалось.")
        return False
    except Exception:
        log.exception("handle_start_deeplink_ref failed")
        await message.answer("Не удалось применить реферальную ссылку. Напишите /feedback — поможем.")
        return False


# -------------------- ВИТРИНА --------------------

@router.message(F.text.in_({"/buy", "Купить", "Оплатить"}))
async def payments_root(message: types.Message):
    await message.answer("Выберите раздел:", reply_markup=payments_root_kb())


@router.callback_query(F.data == "pay:packs")
async def open_packs(cb: types.CallbackQuery):
    await _safe_edit_or_send(cb, "Пакеты сообщений (разовый платёж):", message_packs_kb())


@router.callback_query(F.data == "pay:subs")
async def open_subs(cb: types.CallbackQuery):
    await _safe_edit_or_send(cb, "Подписка (30 дней):", subscription_plans_kb())


@router.callback_query(F.data == "pay:back")
async def pay_back(cb: types.CallbackQuery):
    await _safe_edit_or_send(cb, "Выберите раздел:", payments_root_kb())


@router.callback_query(F.data.startswith("pay:back_to_skus"))
async def back_to_skus(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass

    code = None
    try:
        suffix = cb.data.split("pay:back_to_skus", 1)[1]
        if suffix.startswith(":"):
            code = suffix[1:]
    except Exception:
        code = None

    if code:
        norm = normalize_sku(code)
        if norm.startswith("msgs:"):
            await open_packs(cb);  return
        if norm.startswith("subs:"):
            await open_subs(cb);   return

    txt = (cb.message.text or "").lower()
    if "сообщени" in txt:
        await open_packs(cb)
    else:
        await open_subs(cb)


# -------------------- ВЫБОР ТОВАРА → ВЫБОР МЕТОДА --------------------

@router.callback_query(F.data.startswith("buy:"))
async def buy_sku(cb: types.CallbackQuery):
    raw = cb.data.split("buy:", 1)[1]
    sku = resolve_sku(raw)

    if not sku:
        try:
            log.warning("BUY SKU NOT FOUND: raw=%r norm=%r", raw, normalize_sku(raw))
        except Exception:
            pass
        await cb.message.edit_text(
            "Не удалось распознать товар. Выберите из списка:",
            reply_markup=message_packs_kb() if "msg" in raw.lower() else subscription_plans_kb(),
        )
        await cb.answer()
        return

    canon = sku.code
    norm = normalize_sku(canon)
    caption = _format_long_caption_for_code(norm, sku.title) + "\n\nВыберите способ оплаты:"
    await cb.message.edit_text(
        caption,
        reply_markup=choose_payment_method_kb(canon),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("paymethod:"))
async def choose_method(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass

    # cb.data = "paymethod:<sku_code>:<method>"
    try:
        _, rest = cb.data.split(":", 1)         # rest = "<sku_code>:<method>"
        raw_code, method = rest.rsplit(":", 1)  # метод берём справа, SKU может содержать ':'
    except ValueError:
        await cb.message.answer("Некорректный запрос")
        return

    sku = resolve_sku(raw_code)
    if not sku:
        await cb.message.edit_text(
            "Не удалось распознать товар. Выберите из списка:",
            reply_markup=message_packs_kb() if "msg" in raw_code.lower() else subscription_plans_kb(),
        )
        return

    m = (method or "").lower().strip()
    if m == "stars":
        await _send_invoice_stars(cb, sku.code)
    else:
        await cb.message.answer("Неизвестный способ оплаты")


# -------------------- МОСТЫ ДЛЯ РАЗНЫХ callback_data --------------------

@router.callback_query(F.data.startswith("pay_stars:"))   # наследие
async def legacy_pay_stars(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except Exception:
        pass
    raw_code = cb.data.split("pay_stars:", 1)[1]
    sku = resolve_sku(raw_code)
    if not sku:
        await cb.message.answer("Товар не найден"); return
    await _send_invoice_stars(cb, sku.code)

@router.callback_query(F.data.startswith("pay:stars:"))
async def pay_stars_prefixed(cb: types.CallbackQuery):
    try:
        raw_code = cb.data.split("pay:stars:", 1)[1]
    except Exception:
        await cb.answer("Некорректный запрос", show_alert=True); return
    sku = resolve_sku(raw_code)
    if not sku:
        await cb.message.answer("Товар не найден"); return
    await _send_invoice_stars(cb, sku.code)

@router.callback_query(F.data.startswith("buy:stars:"))
async def buy_stars_prefixed(cb: types.CallbackQuery):
    try:
        raw_code = cb.data.split("buy:stars:", 1)[1]
    except Exception:
        await cb.answer("Некорректный запрос", show_alert=True); return
    sku = resolve_sku(raw_code)
    if not sku:
        await cb.message.answer("Товар не найден"); return
    await _send_invoice_stars(cb, sku.code)

@router.callback_query(F.data.startswith("paystars:"))
async def paystars_compact(cb: types.CallbackQuery):
    raw_code = cb.data.split("paystars:", 1)[1]
    sku = resolve_sku(raw_code)
    if not sku:
        await cb.message.answer("Товар не найден"); return
    await _send_invoice_stars(cb, sku.code)

# ДЕБАГ-ловец: покажет точное callback_data, если ни один из обработчиков выше не сработал
@router.callback_query(F.data.startswith("pay"))
async def pay_debug_tap(cb: types.CallbackQuery):
    data = cb.data or ""
    if any(data.startswith(p) for p in ("pay:stars:", "buy:stars:", "paystars:", "pay_stars:", "paymethod:")):
        return
    try:
        await cb.answer(f"cb={data}", show_alert=False)
    except Exception:
        pass


# -------------------- ИНВОЙСЫ: Stars (XTR) --------------------

def _fallback_xtr_amount_for_sku(sku) -> int:
    """
    Возвращает количество XTR, если явного маппинга нет.
    1) Пересчёт из RUB по settings.xtr_rub_rate (руб за 1⭐), если есть цена в копейках.
    2) Вменяемые дефолты.
    """
    # Попытка конвертации из RUB
    try:
        rub_minor = int(getattr(sku, "amount_minor", 0) or 0)  # копейки
        rate = float(getattr(settings, "xtr_rub_rate", 0) or 0)  # руб за 1 ⭐
        if rub_minor > 0 and rate > 0:
            rub = rub_minor / 100.0
            xtr = max(1, int(math.ceil(rub / rate)))
            return xtr
    except Exception:
        pass

    code = (getattr(sku, "code", "") or "").lower()
    if code.startswith("msgs:"):
        try:
            qty = int(code.split(":", 1)[1])
        except Exception:
            qty = 10
        if qty <= 10:   return 5
        if qty <= 30:   return 12
        if qty <= 50:   return 18
        if qty <= 100:  return 35
        return max(1, qty // 3)
    if code.startswith("subs:"):
        return 120
    return 5


async def _stars_invoice_or_error(msg_or_cb, *, title: str, description: str, payload: str, amount_xtr: int):
    """
    Абсолютно «шумный» помощник:
    1) send_invoice (без provider_token)
    2) если не вышло — create_invoice_link (кнопка)
    3) если и это падает — печатает точную ошибку
    """
    safe_title = (title or "Пакет")[:32]
    safe_desc  = (description or "")[:255]
    safe_label = (title or "Пакет")[:32]
    prices = [LabeledPrice(label=safe_label, amount=int(amount_xtr))]

    bot = msg_or_cb.bot
    chat = getattr(msg_or_cb, "message", None) or msg_or_cb
    chat_id = getattr(getattr(chat, "chat", None), "id", None) or getattr(chat, "chat", None) or getattr(chat, "id", None)

    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=safe_title,
            description=safe_desc,
            payload=payload,
            currency="XTR",
            prices=prices,
            provider_token="",
            start_parameter="bot_pay",
        )
        try:
            if hasattr(msg_or_cb, "answer"):
                await msg_or_cb.answer()
        except Exception:
            pass
        return
    except Exception as e1:
        try:
            link = await bot.create_invoice_link(
                title=safe_title,
                description=safe_desc,
                payload=payload,
                currency="XTR",
                prices=prices,
            )
            kb = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Оплатить Stars", url=link)]]
            )
            await chat.answer("Открой оплату по кнопке ниже:", reply_markup=kb)
            await chat.answer(f"DEBUG send_invoice: <code>{type(e1).__name__}: {e1}</code>")
            return
        except Exception as e2:
            await chat.answer(
                f"send_invoice ERROR: <code>{type(e1).__name__}: {e1}</code>\n"
                f"create_invoice_link ERROR: <code>{type(e2).__name__}: {e2}</code>"
            )
            return


async def _send_invoice_stars(cb: types.CallbackQuery, canon_code: str):
    sku = resolve_sku(canon_code)
    if not sku:
        await cb.message.answer("Товар не найден")
        try: await cb.answer()
        except Exception: pass
        return

    code = normalize_sku(sku.code)

    # 1) Пытаемся взять XTR из конфига (если есть)
    amount_xtr = None
    try:
        if code.startswith("msgs:"):
            qty = int(code.split(":", 1)[1])
            xmap = (getattr(settings, "xtr_price_packages", {}) or {})
            amount_xtr = xmap.get(qty) or xmap.get(str(qty))
        elif code.startswith("subs:"):
            tier = code.split(":", 1)[1]
            xmap = (getattr(settings, "xtr_price_subs", {}) or {})
            amount_xtr = xmap.get(tier) or xmap.get(tier.upper()) or xmap.get(tier.lower())
            if amount_xtr is None and "L30" in xmap:
                base_xtr = xmap["L30"]
                base_rub_minor = next((s.amount_minor for s in SUBSCRIPTION_PLANS if s.code == "subs:L30"), None)
                if base_rub_minor:
                    amount_xtr = int(round(base_xtr / base_rub_minor * getattr(sku, "amount_minor", base_rub_minor)))
    except Exception:
        amount_xtr = None

    # 2) Фолбэк, чтобы не зависеть от .env
    if not amount_xtr or int(amount_xtr) <= 0:
        amount_xtr = _fallback_xtr_amount_for_sku(sku)

    await _stars_invoice_or_error(
        cb,
        title=sku.title or "Пакет",
        description=sku.title or "Пакет для оплаты",
        payload=f"stars:{code}",
        amount_xtr=int(amount_xtr),
    )


# -------------------- PRE-CHECKOUT / УСПЕШНАЯ ОПЛАТА --------------------

@router.pre_checkout_query()
async def process_pre_checkout(pcq: PreCheckoutQuery):
    try:
        await pcq.answer(ok=True)
    except Exception:
        log.exception("pre_checkout answer failed")


@router.message(F.successful_payment)
async def on_success_payment(message: types.Message):
    try:
        sp = message.successful_payment
        if not sp:
            return

        payload = sp.invoice_payload or ""
        if ":" not in payload:
            await message.answer("Оплата прошла ✅")
            return

        base, code = payload.split(":", 1)  # base: rub|stars (используем stars)
        sku = resolve_sku(code)
        if not sku:
            await message.answer("Оплата прошла, но не опознали товар.\nНапишите /feedback — всё починим.")
            return

        tg_hash = hash_user_id(message.from_user.id)
        await ensure_user(tg_hash)

        if code.startswith("msgs:"):
            qty = int(code.split(":", 1)[1])
            await add_bonus_messages(tg_hash, qty)
            await message.answer(f"Оплата прошла ✅\nНачислено +{qty} сообщений.")
            return

        if code.startswith("subs:"):
            tier = code.split(":", 1)[1]  # L30 / P30 / M30
            try:
                days = int(''.join(c for c in tier if c.isdigit()) or "30")
            except Exception:
                days = 30
            until = int(time.time()) + days * 24 * 3600
            await set_user_tier(tg_hash, tier, until)
            await message.answer(
                f"Оплата прошла ✅\nПодписка активирована ({tier}) до "
                f"{time.strftime('%Y-%m-%d', time.localtime(until))}."
            )
            return

        await message.answer("Оплата прошла ✅")
    except Exception:
        log.exception("apply purchase failed")
        await message.answer("Оплата прошла, но не удалось применить покупку. Напишите /feedback — всё починим.")


# -------------------- ТЕСТ-КОМАНДЫ (можно оставить, мешать не будут) --------------------

@router.message(Command("test_stars"))
async def test_stars(msg: types.Message):
    await _stars_invoice_or_error(
        msg,
        title="Тест Stars",
        description="Проверка инвойса",
        payload="stars:test",
        amount_xtr=5,
    )

@router.message(Command("ref"))
async def test_ref_link(msg: types.Message):
    try:
        me = getattr(msg.bot, "me", None) or await msg.bot.get_me()
        uname = getattr(me, "username", None)
        if not uname:
            await msg.answer("Не удалось получить username бота.")
            return
        code = f"ref{msg.from_user.id}"
        link = f"https://t.me/{uname}?start={code}"
        await msg.answer(f"Твоя реферальная ссылка:\n{link}")
    except Exception as e:
        await msg.answer(f"Ошибка рефералки: <code>{type(e).__name__}: {e}</code>")
