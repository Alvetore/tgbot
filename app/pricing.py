# app/pricing.py
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.config import settings

CURRENCY: str = "RUB"
CURRENCY_SYMBOL: str = "₽"


@dataclass(frozen=True)
class Sku:
    code: str
    title: str
    amount_minor: int  # копейки для RUB (исторически); для XTR не используется

# Исторические рублёвые прайсы (для фолбэка в старых местах UI)
MESSAGE_PACKS: List[Sku] = [
    Sku(code="msgs:10", title="+10 сообщений", amount_minor=49_00),
    Sku(code="msgs:20", title="+20 сообщений", amount_minor=99_00),
    Sku(code="msgs:30", title="+30 сообщений", amount_minor=149_00),
    Sku(code="msgs:40", title="+40 сообщений", amount_minor=199_00),
    Sku(code="msgs:50", title="+50 сообщений", amount_minor=249_00),
]

SUBSCRIPTION_PLANS: List[Sku] = [
    Sku(code="subs:L20", title="Лайт подписка (20/день) на 30 дней", amount_minor=199_00),
    Sku(code="subs:L30", title="Лайт+ подписка (30/день) на 30 дней", amount_minor=349_00),
    Sku(code="subs:L40", title="Про подписка (40/день) на 30 дней", amount_minor=459_00),
]


def fmt_price(amount_minor: int) -> str:
    # Исторический форматтер для RUB (используется как фолбэк)
    rub = amount_minor // 100
    kop = amount_minor % 100
    return f"{rub} {CURRENCY_SYMBOL}".replace(" ", " ")


# ===== Stars price helpers =====

def _read_rate_and_step() -> tuple[float, int]:
    """
    Чтение курса и шага из settings, а при нуле — напрямую из окружения.
    Это устраняет проблемы, если settings создан раньше, чем подхватился .env.
    """
    try:
        rate = float(getattr(settings, "xtr_rub_rate", 0.0) or 0.0)
    except Exception:
        rate = 0.0
    try:
        step = int(getattr(settings, "xtr_rub_round_to", 0) or 0)
    except Exception:
        step = 0

    if rate <= 0.0:
        # Фолбэк напрямую из окружения
        try:
            rate = float(os.getenv("XTR_RUB_RATE", "0") or "0")
        except Exception:
            rate = 0.0
    if step <= 0:
        try:
            step = int(os.getenv("XTR_RUB_ROUND_TO", "1") or "1")
        except Exception:
            step = 1
    if step < 1:
        step = 1
    return rate, step


def _approx_rub_from_settings(xtr: int) -> Optional[int]:
    rate, step = _read_rate_and_step()
    if rate <= 0:
        return None
    approx = xtr * rate
    # Округляем до ближайшего кратного step (шаг в рублях)
    rub = int(step * round(approx / step))
    return max(rub, 0)


def format_xtr_label(title: str, xtr: int) -> str:
    """
    Возвращает:
      '<title> — <xtr> XTR (примерно <rub> ₽)'
      или без скобок, если курс не задан.
    """
    rub = _approx_rub_from_settings(xtr)
    if rub is not None:
        return f"{title} — {xtr} XTR (примерно {rub} ₽)"
    return f"{title} — {xtr} XTR"


# ===== SKU helpers (как были) =====

ALIASES = {
    "msgs10": "msgs:10",
    "msgs20": "msgs:20",
    "msgs30": "msgs:30",
    "msgs40": "msgs:40",
    "msgs50": "msgs:50",
    "L20": "subs:L20",
    "L30": "subs:L30",
    "L40": "subs:L40",
}

def normalize_sku(code: str) -> str:
    code = (code or "").strip()
    if not code:
        return code
    if code in ALIASES:
        return ALIASES[code]
    if re.fullmatch(r"msgs:\d+", code):
        return code
    if code.startswith("subs:"):
        return code
    m = re.match(r"subs:([a-zA-Z]\d+)$", code)
    if m:
        return code
    return ALIASES.get(code, code)


def resolve_sku(code: str) -> Optional[Sku]:
    norm = normalize_sku(code)
    all_skus = {s.code: s for s in MESSAGE_PACKS + SUBSCRIPTION_PLANS}
    return all_skus.get(norm)
