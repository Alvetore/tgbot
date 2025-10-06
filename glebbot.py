# bot.py
import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.config import settings
from app.handlers import (
    payments_stars_diag,  # перехватчик Stars
    payments,             # твоя основная оплата
    start, dialog, admin_stats, feedback,
    diag_ping,            # опц. тестовая кнопка
    diag_callbacks,       # <-- ВСЕОБЩИЙ ДИАГНОСТ, СТАВИМ ПОСЛЕДНИМ
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("starter")

async def main() -> None:
    # 1) Проверки окружения
    if not settings.bot_token:
        log.error("BOT_TOKEN пуст. Проверь .env / переменные окружения.")
        sys.exit(1)

    log.info("Запуск бота...")
    log.info("Python: %s", sys.version.replace("\n", " "))
    log.info("BOT_TOKEN: %s***", settings.bot_token[:10])

    # 2) Создаём бота/диспетчер
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # 3) Подключаем роутеры
    dp.include_router(payments_stars_diag.router)   # 1) пусть именно он первый ловит Stars
    dp.include_router(payments.router)              # 2) твоя остальная оплата
    dp.include_router(start.router)
    dp.include_router(dialog.router)
    dp.include_router(admin_stats.router)
    dp.include_router(feedback.router)
    dp.include_router(diag_ping.router)             # опционально
    dp.include_router(diag_callbacks.router)    

    # 4) Старт поллинга
    log.info("Стартуем polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception:
        log.exception("Срыв на start_polling")
        raise
    finally:
        log.info("Завершаем работу, закрываем сессию бота")
        try:
            await bot.session.close()
        except Exception:
            log.exception("Ошибка при закрытии сессии")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[CTRL+C] Остановлено пользователем")
