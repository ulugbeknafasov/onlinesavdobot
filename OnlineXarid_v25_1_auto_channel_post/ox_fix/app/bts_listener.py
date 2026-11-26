"""BTS Telegram arrival listener.

Reads messages from the user's authorized MTProto session, matches the exact
BTS parcel ID to Shipment.tracking_code, and notifies the customer.
"""
import asyncio
import os
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from sqlalchemy import select

from app.config import BOT_TOKEN, WEBAPP_URL, BTS_BOT_SOURCE, BTS_MONITOR_SESSION
from app.db import Session, Shipment, Order, Payment
from app.bts_message_parser import parse_bts_message


FULLY_PAID = {"To‘liq to‘landi", "To‘liq tolandi"}


async def process_bts_message(text, bot=None):
    parsed = parse_bts_message(text)
    if not parsed:
        return {"matched": False, "reason": "parcel_id_missing"}

    parcel_id = parsed["parcel_id"]
    async with Session() as db:
        sh = await db.scalar(select(Shipment).where(Shipment.tracking_code == parcel_id))
        if not sh:
            return {"matched": False, "reason": "parcel_not_found", "parcel_id": parcel_id}

        order = await db.get(Order, sh.order_id)
        if not order:
            return {"matched": False, "reason": "order_not_found", "parcel_id": parcel_id}

        # Do not discard the BTS details if an admin already marked the parcel arrived.
        same_message = (sh.bts_message or "").strip() == (text or "").strip()
        if same_message:
            return {"matched": True, "duplicate": True, "order_id": order.id}

        sh.status = "BTS filialiga yetib keldi"
        sh.bts_message = (text or "")[:3000]
        if parsed["pickup_code"]:
            sh.pickup_code = parsed["pickup_code"]
        order.status = "BTS filialiga yetib keldi"

        due = int(order.remaining_due or 0) if order.payment_plan == "40/60" else 0
        is_fully_paid = order.payment_status in FULLY_PAID

        # Reuse the pending second-installment payment created by first-payment
        # confirmation/admin workflow. Re-arm its 5-minute matching window now.
        if due > 0 and not is_fully_paid:
            payment = await db.scalar(select(Payment).where(
                Payment.order_id == order.id,
                Payment.expected_amount == due,
                Payment.status.in_(["Kutilmoqda", "BTS kelishini kutmoqda"]),
            ).order_by(Payment.id.desc()))
            if payment:
                payment.status = "Kutilmoqda"
                payment.created_at = datetime.now(timezone.utc)
            else:
                active_amounts = set((await db.scalars(select(Payment.expected_amount).where(
                    Payment.status.in_(["Kutilmoqda", "BTS kelishini kutmoqda", "Ikkinchi bosqich kutilmoqda"])
                ))).all())
                unique_due = next((due + offset for offset in range(1000, 5001, 1000)
                                   if due + offset not in active_amounts), None)
                if unique_due is None:
                    raise RuntimeError("5 daqiqalik oynada 1 000–5 000 so‘mlik bo‘sh to‘lov farqi qolmagan")
                order.remaining_due = unique_due
                db.add(Payment(order_id=order.id, expected_amount=unique_due, status="Kutilmoqda"))
            order.payment_status = "60% to‘lov kutilmoqda"
            order.second_payment_requested_at = datetime.now(timezone.utc)

        user_id, order_id = order.user_tg_id, order.id
        photo = sh.photo_url
        bts_code = parsed["pickup_code"] or sh.pickup_code or ""
        pay_second = due > 0 and not is_fully_paid
        await db.commit()

    own_bot = False
    if bot is None and BOT_TOKEN:
        bot = Bot(BOT_TOKEN)
        own_bot = True

    try:
        if bot:
            if pay_second:
                msg = (
                    f"📦 Buyurtma #{order_id}: BTS filialiga yetib keldi.\n"
                    f"Pochta ID: <code>{parcel_id}</code>\n"
                    f"Qolgan 60% to‘lov: <b>{due:,} so‘m</b>.\n"
                    "To‘lovni yakunlagach, BTS qabul qilish kodi yuboriladi.\n"
                    "Yordam kerak bo‘lsa, qo‘llab-quvvatlash xizmatiga yoki admin’ga murojaat qiling."
                )
                if WEBAPP_URL:
                    sep = "&" if "?" in WEBAPP_URL else "?"
                    kb = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text="💳 To‘lovni yakunlash",
                            web_app=WebAppInfo(url=f"{WEBAPP_URL}{sep}order_id={order_id}"),
                        )
                    ]])
                else:
                    kb = None
            else:
                msg = "📬 BTS’dan kelgan xabar:\n" + (text or "")
                if bts_code:
                    msg += f"\n\n🔐 BTS qabul qilish kodi: <code>{bts_code}</code>"
                msg += "\n\nMuammo yoki qiyinchilik bo‘lsa, qo‘llab-quvvatlash xizmatiga yoki admin’ga murojaat qiling."
                kb = None

            await bot.send_message(user_id, msg, parse_mode="HTML", reply_markup=kb)
            if photo:
                # photo_url may be a public URL or a Telegram-compatible file URL.
                try:
                    await bot.send_photo(user_id, photo, caption=f"📦 Buyurtma #{order_id} — BTS kvitansiyasi")
                except Exception as photo_error:
                    print("BTS receipt photo notification failed:", repr(photo_error))
    finally:
        if own_bot:
            await bot.session.close()

    return {"matched": True, "order_id": order_id, "due": due, "second_payment_required": pay_second}


async def main():
    from telethon import TelegramClient, events
    from app.config import TELEGRAM_API_ID, TELEGRAM_API_HASH
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise RuntimeError("TELEGRAM_API_ID va TELEGRAM_API_HASH kerak")
    os.makedirs(os.path.dirname(BTS_MONITOR_SESSION) or ".", exist_ok=True)
    client = TelegramClient(BTS_MONITOR_SESSION, int(TELEGRAM_API_ID), TELEGRAM_API_HASH)
    await client.start()
    bot = Bot(BOT_TOKEN) if BOT_TOKEN else None

    @client.on(events.NewMessage(chats=BTS_BOT_SOURCE))
    async def handler(event):
        try:
            result = await process_bts_message(event.raw_text or "", bot)
            print("BTS message:", result)
        except Exception as exc:
            print("BTS listener error:", repr(exc))

    print("BTS listener active for", BTS_BOT_SOURCE)
    try:
        await client.run_until_disconnected()
    finally:
        if bot:
            await bot.session.close()
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
