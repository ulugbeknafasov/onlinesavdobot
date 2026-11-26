"""Card notification watcher for the admin-owned Telegram account.

This is a notification parser, not a bank acquiring API. It only confirms
messages that explicitly look like incoming credits, contain a transaction
reference, match the configured card suffix, and uniquely match one pending
payment inside the configured time window. Ambiguous messages go to review.
"""
import asyncio, os, re, secrets
from datetime import datetime, timezone
from telethon import TelegramClient, events
from aiogram import Bot
from sqlalchemy import select
from app.db import Session, Payment, Order, Shipment, Setting, User, OrderLine, WalletLedger, Product, ProductVariant, InventoryReservation
from app.config import BOT_TOKEN
from app.security import decrypt_secret
from app.payment_parser import parse_notice


async def setting(session, key, default=""):
    row = await session.get(Setting, key)
    return row.value if row else default

async def handle_notice(text, received_at, bot):
    parsed = parse_notice(text)
    if not parsed:
        print("Payment notice ignored: not a supported incoming customer payment")
        return
    if parsed.get("manual_review"):
        print("Payment notice requires manual review:", parsed.get("reason"))
        return
    amount, txid, card4 = parsed["amount"], parsed["transaction_id"], parsed["card4"]
    async with Session() as s:
        expected4 = await setting(s, "card_last4")
        if not expected4 or card4 != expected4[-4:]:
            print("Payment notice sent to manual review: card suffix mismatch/unconfigured")
            return
        if await s.scalar(select(Payment.id).where(Payment.transaction_id == txid)):
            print("Duplicate transaction ignored:", txid); return
        pending = (await s.scalars(select(Payment).where(Payment.status == "Kutilmoqda"))).all()
        candidates = [p for p in pending if p.expected_amount == amount]
        if len(candidates) != 1:
            print("Payment requires admin review: amount match count =", len(candidates))
            for p in candidates:
                p.status = "Admin tekshiruvida"; p.raw_message = text[:2000]
            await s.commit(); return
        p = candidates[0]
        # The second 60% installment is payable within five calendar days
        # after the admin marks the parcel as arrived at the BTS branch.
        order_for_deadline = await s.get(Order, p.order_id)
        if order_for_deadline and order_for_deadline.payment_status == "60% to‘lov kutilmoqda":
            deadline_created = order_for_deadline.second_payment_requested_at
            if deadline_created and deadline_created.tzinfo is None:
                deadline_created = deadline_created.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if deadline_created and (now_utc - deadline_created).total_seconds() > 5 * 24 * 60 * 60:
                p.status = "Muddati o‘tgan — admin tekshiruvi"
                p.raw_message = text[:2000]
                await s.commit()
                print("Second installment expired; sent to admin review:", p.id)
                return
        created = p.created_at
        if created and created.tzinfo is None: created = created.replace(tzinfo=timezone.utc)
        received = received_at if received_at.tzinfo else received_at.replace(tzinfo=timezone.utc)
        delta = (received - created).total_seconds() if created else 999999
        p.raw_message = text[:2000]
        if delta < 0 or delta > 300:
            p.status = "Kechikkan — admin tekshiruvi"; await s.commit(); return
        p.transaction_id = txid
        p.status = "Tasdiqlandi"; p.confirmed_at = datetime.now(timezone.utc)
        order = await s.get(Order, p.order_id)
        if not order:
            p.status = "Admin tekshiruvida"; await s.commit(); return
        # Apply wallet reservation and stock only on the first installment.
        is_second_installment = (order.payment_plan == "40/60" and p.expected_amount == order.remaining_due
                                 and order.payment_status == "60% to‘lov kutilmoqda")
        if not is_second_installment:
            user = await s.scalar(select(User).where(User.tg_id == order.user_tg_id))
        else:
            user = None
        if user and order.wallet_used:
            if user.cash_balance < order.wallet_used:
                p.status = "Admin tekshiruvida — hamyon rezervi yetarli emas"
                await s.commit()
                return
            user.cash_balance -= order.wallet_used
            s.add(WalletLedger(user_tg_id=user.tg_id, amount=-order.wallet_used,
                               kind="checkout", note=f"Buyurtma #{order.id}"))
        if user and order.cashback_used:
            if user.bonus_balance < order.cashback_used:
                p.status = "Admin tekshiruvida — cashback rezervi yetarli emas"
                await s.commit()
                return
            user.bonus_balance -= order.cashback_used
            s.add(WalletLedger(user_tg_id=user.tg_id, amount=-order.cashback_used,
                               kind="cashback_spend", note=f"Buyurtma #{order.id}"))
        if not is_second_installment:
            reservations=(await s.scalars(select(InventoryReservation).where(
                InventoryReservation.order_id==order.id,InventoryReservation.status=="held"))).all()
            if reservations:
                for reservation in reservations:
                    reservation.status="committed"
            else:
                # Legacy orders created before reservation support: manual review.
                p.status="Admin tekshiruvida — ombor rezervi topilmadi"
                await s.commit()
                return
        if order.payment_plan == "40/60" and order.remaining_due > 0 and not is_second_installment:
            order.payment_status = "40% to'landi — 60% BTS punktiga yetgach"
        else:
            order.payment_status = "To'liq to'landi"
            if order.status == "BTS filialiga yetib keldi" and not order.pickup_code:
                order.pickup_code = secrets.token_hex(3).upper()
        user_id, order_id, status = order.user_tg_id, order.id, order.payment_status
        shipment = await s.scalar(select(Shipment).where(Shipment.order_id == order_id))
        pickup = (shipment.pickup_code or order.pickup_code) if shipment and order.status == "BTS filialiga yetib keldi" else order.pickup_code
        bts_message = shipment.bts_message if shipment else ""
        await s.commit()
    if bot:
        try:
            notify = f"✅ Buyurtma #{order_id} uchun {amount:,} so‘m to‘lovi tasdiqlandi.\nHolat: {status}"
            if status in ("To‘liq to‘landi", "To‘liq tolandi") and bts_message:
                notify += "\n\n📬 BTS’dan kelgan xabar:\n" + bts_message
                if pickup: notify += f"\n\n🔐 Qabul qilish kodi: <code>{pickup}</code>"
                notify += "\n\nMuammo yoki qiyinchilik bo‘lsa, qo‘llab-quvvatlash xizmatiga yoki admin’ga murojaat qiling."
            await bot.send_message(user_id, notify, parse_mode="HTML")
        except Exception as e: print("User notification failed:", e)


async def main():
    async with Session() as s:
        api_id = int(await setting(s, "telegram_api_id", "0") or 0)
        api_hash_enc = await setting(s, "telegram_api_hash")
        api_hash = decrypt_secret(api_hash_enc) if api_hash_enc else ""
        phone = await setting(s, "telegram_phone")
        source = await setting(s, "card_notice_source", "CardXabarBot")
    if not api_id or not api_hash or not phone:
        raise RuntimeError("Admin panelda Telegram API ID, API Hash va telefonni sozlang.")
    os.makedirs("storage", exist_ok=True)
    client = TelegramClient(os.getenv("TELEGRAM_SESSION", "storage/card_monitor"), api_id, api_hash)
    await client.start(phone=phone)
    bot = Bot(BOT_TOKEN) if BOT_TOKEN else None
    entity = await client.get_entity(source)
    @client.on(events.NewMessage(chats=entity))
    async def on_message(event):
        await handle_notice(event.raw_text or "", event.message.date, bot)
    print(f"Card notification listener started: {source}")
    try: await client.run_until_disconnected()
    finally:
        if bot: await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
