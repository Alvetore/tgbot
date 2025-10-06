from __future__ import annotations

import logging
import re
from typing import Optional, Dict, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

router = Router(name="stars_diag")
log = logging.getLogger(__name__)

# Подхватываем твои конфиги
try:
    from app.config import SKUS  # {"sku": {"title": "...", "desc": "...", "price_xtr": 30}}
except Exception:
    SKUS = {}

try:
    from app.texts import PAYMENT_TITLE_PREFIX
except Exception:
    PAYMENT_TITLE_PREFIX = ""


def _normalize_sku_code(raw: str) -> str:
    # Разрешаем двоеточия в SKU (например, "msgs:10")
    return re.sub(r"[^0-9A-Za-z_\-\.:]", "", (raw or "")).strip()


def _get_sku(sku: str) -> Optional[Dict[str, Any]]:
    item = SKUS.get(sku)
    if not item:
        return None
    title = str(item.get("title") or sku)
    desc = str(item.get("desc") or "")
    try:
        price_xtr = int(item.get("price_xtr") or 0)
    except Exception:
        price_xtr = 0
    if price_xtr <= 0:
        return None
    return {"title": title, "desc": desc, "price_xtr": price_xtr}


async def _safe_reply(base: Message | CallbackQuery, text: str, **kwargs):
    msg: Optional[Message] = base if isinstance(base, Message) else getattr(base, "message", None)
    if not msg:
        return
    try:
        return await msg.answer(text, **kwargs)
    except Exception as e:
        log.warning("answer() failed: %s", e)
        try:
            return await msg.bot.send_message(chat_id=msg.chat.id, text=text, **kwargs)
        except Exception as e2:
            log.error("send_message fallback failed: %s", e2)


# Ловим оба формата, допускаем двоеточия внутри SKU
@router.callback_query(
    F.data.regexp(r"^(?:pay:stars:(?P<sku1>.+)|paymethod:(?P<sku2>.+):stars)$")
)
async def stars_entry(cb: CallbackQuery, regexp: re.Match):
    """Перехват «Оплатить Stars»: pay:stars:<sku> ИЛИ paymethod:<sku>:stars. Поддержка SKU с двоеточиями."""
    # Закрываем «часики» и логируем что прилетело
    try:
        await cb.answer("Готовлю оплату Stars…", show_alert=False)
    except Exception:
        pass
    log.info("STARS_CB data=%s chat=%s user=%s", cb.data, getattr(cb.message.chat, "id", None), getattr(cb.from_user, "id", None))

    sku_raw = regexp.group("sku1") or regexp.group("sku2") or ""
    # Если это paymethod:<sku>:stars — извлечённый <sku> может содержать двоеточия; оставляем как есть.
    sku = _normalize_sku_code(sku_raw)
    data = _get_sku(sku)
    if not data:
        await _safe_reply(cb, f"Товар не найден: {sku or '—'}. Попробуй выбрать заново.")
        return

    await _safe_reply(cb, f"⏳ Оформляю: {data['title']} • {data['price_xtr']} XTR")

    await _send_stars_invoice_and_link(
        message=cb.message,
        sku_code=sku,
        title=data["title"],
        description=data["desc"],
        price_xtr=data["price_xtr"],
        payload=f"stars:{sku}",
    )


async def _send_stars_invoice_and_link(
    message: Message,
    sku_code: str,
    title: str,
    description: str,
    price_xtr: int,
    payload: str,
):
    """Пробуем invoice, а также создаём и отправляем ссылку как альтернативу."""
    bot = message.bot
    chat_id = message.chat.id

    safe_title = (f"{PAYMENT_TITLE_PREFIX} {title}").strip()
    safe_desc = (description or "")[:255]
    prices = [LabeledPrice(label=safe_title, amount=price_xtr)]  # XTR в целых

    # 1) Пробуем отправить инвойс XTR (без start_parameter)
    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=safe_title,
            description=safe_desc,
            payload=payload,
            currency="XTR",
            prices=prices,
            # provider_token="",  # можно раскомментировать, если в "Арине" так
        )
        log.info("STARS_INVOICE sent chat=%s sku=%s price=%s", chat_id, sku_code, price_xtr)
    except TelegramBadRequest as e:
        log.warning("STARS_INVOICE bad_request: %s", e)
    except Exception as e:
        log.exception("STARS_INVOICE unexpected: %s", e)

    # 2) Всегда готовим ссылку как альтернативу
    link = None
    try:
        link = await bot.create_invoice_link(
            title=safe_title,
            description=safe_desc,
            payload=payload,
            currency="XTR",
            prices=prices,
        )
        log.info("STARS_LINK created chat=%s sku=%s link_ok=%s", chat_id, sku_code, bool(link))
    except TelegramBadRequest as e:
        log.warning("STARS_LINK bad_request: %s", e)
    except Exception as e:
        log.exception("STARS_LINK unexpected: %s", e)

    if link:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌟 Оплатить Stars (ссылка)", url=link)]])
        await _safe_reply(message, "Если форма оплаты не открылась — нажми кнопку ниже:", reply_markup=kb)
        await _safe_reply(message, link)
    else:
        await _safe_reply(message, "Не смог получить ссылку на оплату Stars. Попробуй позже.")
