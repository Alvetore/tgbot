# admin_bot.py
import asyncio, logging, os, sys, traceback
print(">>> ENTRY admin_bot.py", flush=True)

try:
    from aiogram import Bot, Dispatcher
    from aiogram.client.default import DefaultBotProperties
    from app.config import settings
    from app.handlers import admin_menu, admin_stats
except Exception as e:
    print(">>> IMPORT FAIL:", repr(e), flush=True)
    traceback.print_exc()
    sys.exit(2)

LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("admin_starter")

async def main() -> None:
    print(">>> main() start (admin)", flush=True)

    token = (settings.admin_bot_token or "").strip()
    if not token:
        log.error("ADMIN_BOT_TOKEN пуст. cwd=%s (.env должен лежать здесь)", os.getcwd())
        # Покажем ещё и BOT_TOKEN, чтобы было видно, .env вообще подхватился
        log.info("BOT_TOKEN startswith: %s", (settings.bot_token or "")[:10])
        sys.exit(1)

    log.info("ADMIN_BOT_TOKEN startswith: %s***", token[:10])

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()

    # Только админ-роутеры, без channel_admin/scheduler
    dp.include_router(admin_menu.router)
    dp.include_router(admin_stats.router)

    # Пробный вызов get_me — сразу видно, если токен некорректен
    try:
        me = await bot.get_me()
        log.info("get_me: id=%s username=@%s", me.id, me.username)
    except Exception:
        log.exception("get_me failed (проверь токен/сеть)")
        raise

    log.info("Starting admin polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception:
        log.exception("start_polling crashed")
        raise
    finally:
        log.info("Closing admin bot session…")
        try:
            await bot.session.close()
        except Exception:
            log.exception("Close session error")
        print(">>> main() end (admin)", flush=True)

if __name__ == "__main__":
    print(">>> __main__ guard (admin)", flush=True)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[CTRL+C] Stopped (admin)", flush=True)
    except SystemExit as e:
        print(f">>> SystemExit: {e.code}", flush=True)
        raise
    except Exception as e:
        print(">>> TOP-LEVEL EXC (admin):", repr(e), flush=True)
        traceback.print_exc()
        raise
