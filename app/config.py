# app/config.py
from pydantic import BaseModel
from typing import List, Dict, Optional
import os
import json
from dotenv import load_dotenv
from pathlib import Path

# Попробуем python-dotenv, а если нет — ручной парсер
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()  # читает .env из текущей рабочей директории
except Exception:
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _parse_int_list(env_value: Optional[str]) -> List[int]:
    """
    Преобразует строку вида "111,222,333" в [111, 222, 333].
    Пустые значения игнорирстилься. Невалидные элементы пропускаются.
    """
    if not env_value:
        return []
    out: List[int] = []
    for chunk in env_value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            # пропускаем нечисловые значения
            continue
    return out

def _parse_json_dict(env_value: Optional[str]) -> Optional[Dict]:
    """
    Читает JSON-словарь из ENV. Возвращает dict или None.
    Пример: DAILY_QUOTA_MAP='{"FREE":10,"PLUS":30,"PREMIUM":100}'
    """
    if not env_value:
        return None
    try:
        obj = json.loads(env_value)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return None


class Settings(BaseModel):
    # --- Telegram bots ---
    bot_token: str = os.getenv("BOT_TOKEN", "")
    admin_bot_token: str = os.getenv("ADMIN_BOT_TOKEN", "")

    # --- Admins ---
    # Список Telegram ID админов, через запятую: ADMIN_IDS=111111111,222222222
    admin_ids: List[int] = _parse_int_list(os.getenv("ADMIN_IDS"))

    # --- LLM ---
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # --- Security / Privacy ---
    user_id_salt: str = os.getenv("USER_ID_SALT", "change_me")
    feedback_fernet_key: str = os.getenv("FEEDBACK_FERNET_KEY", "")

    # --- Payments: classic providers (RUB) ---
    # Russia → YooKassa; CIS/other → (не используется)
    tg_provider_token_ru: str = os.getenv("TG_PROVIDER_TOKEN_RU", "")
    tg_provider_token_cis: str = os.getenv("TG_PROVIDER_TOKEN_CIS", "")

    # --- Database ---
    # Убедись, что этот путь совпадает у пользователя и админ-бота
    db_path: str = os.getenv("DB_PATH", "./data/bot.db")

    # --- Daily limits / quotas ---
    # Базовые квоты на день (использстилься, если карта ниже не задана)
    free_daily_limit: int = int(os.getenv("FREE_DAILY_LIMIT", "10"))
    paid_daily_limit: int = int(os.getenv("PAID_DAILY_LIMIT", "100"))

    # Опциональная карта квот из ENV (перебивает free/paid, если задана):
    # DAILY_QUOTA_MAP='{"FREE":10,"PLUS":30,"PREMIUM":100}'
    daily_quota_map: Optional[Dict[str, int]] = _parse_json_dict(os.getenv("DAILY_QUOTA_MAP"))

    # --- Telegram Stars (XTR) pricing ---
    # Telegram ждёт amount в "центах" валюты → XTR * 100 в sendInvoice.
    # Значения ниже — примеры; подправь под свою экономику.
    xtr_price_packages: Dict[int, int] = {
        10: 30,    # +10 сообщений
        20: 60,
        30: 90,
        40: 120,
        50: 150,
    }
    xtr_price_subs: Dict[str, int] = {
        "L20": 60,     # 20/день
        "L30": 120,    # 30/день
        "L40": 170,    # 40/день
    }

# --- Stars → ₽ отображение ---
# Если 0 или не задано — «примерно ₽» не показываем
# Округление ₽ до шага (например 10 → до десятков)



settings = Settings()
