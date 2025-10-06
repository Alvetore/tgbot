# app/handlers/debugtap.py
from aiogram import Router, types
from app.handlers import payments as ph

router = Router(name="payments_bridge")

@router.callback_query()
async def _bridge(cb: types.CallbackQuery):
    data = cb.data or ""
    try:
        if data.startswith("paymethod:"):
            await ph.choose_method(cb); return
        if data.startswith("pay_stars:"):
            await ph.legacy_pay_stars(cb); return
        if data.startswith("pay_rub:"):
            await ph.legacy_pay_rub(cb); return

        # Витрина/навигация
        if data == "pay:packs":
            await ph.open_packs(cb); return
        if data == "pay:subs":
            await ph.open_subs(cb); return
        if data == "pay:back":
            await ph.pay_back(cb); return
        if data == "pay:back_to_skus":
            await ph.back_to_skus(cb); return

        # Выбор товара
        if data.startswith("buy:"):
            await ph.buy_sku(cb); return
    except Exception as e:
        # не шумим — просто «проглатываем», чтобы не мешать другим роутерам
        try:
            await cb.answer(str(e), show_alert=True)
        except Exception:
            pass
