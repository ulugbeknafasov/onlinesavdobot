
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
import io, csv, secrets, pathlib, asyncio, re
from datetime import datetime, timedelta, timezone
from fastapi.staticfiles import StaticFiles
from aiogram import Bot
from pydantic import BaseModel, Field
from sqlalchemy import select, func, delete
from app.db import init_db, Session, User, Product, CartItem, Order, Admin, Setting, Branch, UserBranch, Payment, Favorite, Review, PromoCode, WalletLedger, OrderLine, ProductVariant, ProductMedia, Comparison, Referral, Shipment, SupportMessage, AuditLog, BTSTariff, InventoryReservation, RefundRequest, ScheduledChannelPost
from app.security import verify_init_data, encrypt_secret
from app.config import ADMIN_IDS, BOT_TOKEN, WEBAPP_URL

async def seed_bts_branches():
    """Idempotently load all Uzbekistan BTS offices parsed from the supplied directory."""
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bts_offices_uzbekistan.csv")
    if not os.path.exists(csv_path):
        return
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    async with Session() as s:
        existing = {b.branch_code: b for b in (await s.scalars(select(Branch))).all() if b.branch_code}
        for r in rows:
            code = (r.get("code") or "").strip()
            if not code:
                continue
            values = dict(
                title=(r.get("name") or "BTS filiali").strip()[:200],
                address=(r.get("address") or "").strip()[:300],
                city="O‘zbekiston",
                phone=(r.get("phone") or "").strip()[:40],
                branch_code=code[:30],
                latitude=float(r.get("latitude") or 0),
                longitude=float(r.get("longitude") or 0),
                map_url=(r.get("map_url") or "").strip()[:500],
                video_url=(r.get("video_url") or "").strip()[:500],
                active=True,
            )
            branch = existing.get(code)
            if branch:
                for key, value in values.items():
                    setattr(branch, key, value)
            else:
                branch = Branch(**values)
                s.add(branch)
                existing[code] = branch
        await s.commit()


@asynccontextmanager
async def lifespan(app):
    await init_db()
    await seed_bts_branches()
    async with Session() as s:
        for aid in ADMIN_IDS:
            if not await s.get(Admin, aid): s.add(Admin(tg_id=aid))
        await s.commit()
    task = asyncio.create_task(maintenance_worker())
    bot_task = None
    if BOT_TOKEN:
        # Run Telegram polling inside the same Render Web Service process.
        from bot.main import run_bot
        bot_task = asyncio.create_task(run_bot(), name="telegram-bot-polling")
    try:
        yield
    finally:
        for background_task in (task, bot_task):
            if background_task is not None:
                background_task.cancel()
                try:
                    await background_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass



async def allocate_unique_payment_amount(session, base_amount:int, *, max_offset:int=5000) -> int:
    """Allocate base + 1,000..5,000 UZS, unique among payments in 5-min window."""
    base_amount=int(base_amount)
    if base_amount < 1:
        raise HTTPException(400, "To‘lov summasi noto‘g‘ri")
    from datetime import timedelta
    cutoff=datetime.now(timezone.utc)-timedelta(minutes=5)
    active_statuses=("Kutilmoqda","BTS kelishini kutmoqda","Ikkinchi bosqich kutilmoqda")
    rows=(await session.scalars(select(Payment).where(
        Payment.status.in_(active_statuses), Payment.created_at >= cutoff
    ))).all()
    used={int(p.expected_amount) for p in rows}
    for offset in range(1000, min(max_offset,5000)+1, 1000):
        candidate=base_amount+offset
        if candidate not in used:
            return candidate
    raise HTTPException(409, "Hozir 1 000–5 000 so‘mlik bo‘sh farq qolmagan. 5 daqiqadan keyin qayta urinib ko‘ring.")

app = FastAPI(title="OnlineXarid API", version="2.0", lifespan=lifespan)
WEB_DIR=os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
UPLOAD_DIR=os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def tg_user(init_data):
    try: return verify_init_data(init_data)
    except Exception: raise HTTPException(401, "Telegram sessiyasi tasdiqlanmadi. Bot ichidan qayta oching.")

async def require_user(init_data):
    u=tg_user(init_data)
    async with Session() as s:
        user=await s.scalar(select(User).where(User.tg_id==u["id"]))
        if not user or not user.phone: raise HTTPException(403,"Avval botda telefon raqamingizni tasdiqlang")
        if user.is_blocked: raise HTTPException(403,"Hisobingiz vaqtincha bloklangan")
    return u

async def require_admin(init_data):
    u=await require_user(init_data)
    async with Session() as s:
        if not await s.get(Admin,u["id"]): raise HTTPException(403,"Admin ruxsati yo'q")
    return u

class CartIn(BaseModel):
    product_id:int
    quantity:int=Field(default=1,ge=1,le=20)
    color:str=""
    size:str=""
class CartUpdate(BaseModel):
    quantity:int=Field(ge=1,le=20)
class ReviewIn(BaseModel):
    rating:int=Field(ge=1,le=5)
    comment:str=""
class PromoIn(BaseModel):
    code:str
class WalletAdjustIn(BaseModel):
    tg_id:int
    amount:int
    note:str="Admin qo‘lda to‘ldirdi"
class PaymentDecision(BaseModel):
    decision:str
    note:str=""
class AdminRoleIn(BaseModel):
    tg_id:int
    role:str="manager"
class CheckoutIn(BaseModel):
    branch_id:int
    use_wallet:bool=False
    use_cashback:bool=False
    payment_plan:str="100"
    promo_code:str="" 
class ProductIn(BaseModel):
    title:str
    description:str=""
    price:int=Field(ge=0)
    old_price:int=0
    image_url:str=""
    category:str="Boshqa"
    stock:int=Field(ge=0)
    active:bool=True
class BranchIn(BaseModel):
    title:str
    address:str=""
    city:str="Toshkent"
    active:bool=True
    branch_code:str=""
    landmark:str=""
    map_url:str=""
    latitude:float=0
    longitude:float=0
    work_hours:str=""
    phone:str=""
class AdminIn(BaseModel): tg_id:int
class SettingIn(BaseModel):
    card_number:str=""
    card_holder:str=""
    telegram_api_id:str=""
    telegram_api_hash:str=""
    telegram_phone:str=""
    card_notice_source:str="CardXabarBot"
    card_last4:str=""
    product_channel_id:str=""
    product_post_template:str=""
    bts_origin_city:str=""
    bts_tariff_type:str=""

@app.get("/")
async def home(): return FileResponse(os.path.join(WEB_DIR,"index.html"))
@app.get("/health")
async def health(): return {"ok":True,"service":"OnlineXarid"}
@app.get("/api/me")
async def me(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        user=await s.scalar(select(User).where(User.tg_id==u["id"]))
        return {"id":user.tg_id,"name":user.full_name,"phone":user.phone,"cash_balance":user.cash_balance,"bonus_balance":user.bonus_balance}
@app.get("/api/products")
async def products(q:str="",category:str=""):
    async with Session() as s:
        stmt=select(Product).where(Product.active==True)
        rows=(await s.scalars(stmt.order_by(Product.id.desc()))).all()
        data=[{"id":p.id,"title":p.title,"description":p.description,"price":p.price,"old_price":p.old_price,"image_url":p.image_url,"category":p.category,"stock":p.stock} for p in rows]
        if q: data=[p for p in data if q.casefold() in p["title"].casefold()]
        if category: data=[p for p in data if p["category"]==category]
        return data
@app.get("/api/branches")
async def branches(x_telegram_init_data:str=Header(default="")):
    await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Branch).where(Branch.active==True).order_by(Branch.city,Branch.title))).all()
        return [{"id":b.id,"title":b.title,"address":b.address,"city":b.city,"latitude":b.latitude,
                 "longitude":b.longitude,"work_hours":b.work_hours,"phone":b.phone,
                 "branch_code":b.branch_code,"landmark":b.landmark,"map_url":b.map_url,"video_url":b.video_url} for b in rows]
@app.get("/api/my-branches")
async def my_branches(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.execute(select(UserBranch,Branch).join(Branch,Branch.id==UserBranch.branch_id).where(UserBranch.user_tg_id==u["id"]))).all()
        return [{"id":ub.id,"branch_id":b.id,"title":b.title,"address":b.address,"city":b.city,"label":ub.label} for ub,b in rows]
@app.post("/api/my-branches/{branch_id}")
async def save_my_branch(branch_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        b=await s.get(Branch,branch_id)
        if not b or not b.active: raise HTTPException(404,"Pochta filiali topilmadi")
        exists=await s.scalar(select(UserBranch).where(UserBranch.user_tg_id==u["id"],UserBranch.branch_id==branch_id))
        if not exists: s.add(UserBranch(user_tg_id=u["id"],branch_id=branch_id))
        await s.commit()
        return {"ok":True}
@app.delete("/api/my-branches/{saved_id}")
async def delete_my_branch(saved_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        row=await s.scalar(select(UserBranch).where(UserBranch.id==saved_id,UserBranch.user_tg_id==u["id"]))
        if row: await s.delete(row); await s.commit()
        return {"ok":True}
@app.post("/api/cart")
async def add_cart(body:CartIn,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        p=await s.get(Product,body.product_id)
        if not p or not p.active: raise HTTPException(404,"Mahsulot topilmadi")
        if p.stock<body.quantity: raise HTTPException(409,"Omborda yetarli mahsulot yo'q")
        row=await s.scalar(select(CartItem).where(CartItem.user_tg_id==u["id"],CartItem.product_id==p.id,CartItem.color==body.color,CartItem.size==body.size))
        if row: row.quantity=min(row.quantity+body.quantity,20)
        else: s.add(CartItem(user_tg_id=u["id"],product_id=p.id,quantity=body.quantity,color=body.color,size=body.size))
        await s.commit()
        return {"ok":True}
@app.get("/api/cart")
async def get_cart(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.execute(select(CartItem,Product).join(Product,Product.id==CartItem.product_id).where(CartItem.user_tg_id==u["id"]))).all()
        return [{"item_id":i.id,"product_id":p.id,"title":p.title,"price":p.price,"image_url":p.image_url,"quantity":i.quantity,"color":i.color,"size":i.size,"subtotal":p.price*i.quantity} for i,p in rows]
@app.get("/api/orders")
async def my_orders(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Order).where(Order.user_tg_id==u["id"]).order_by(Order.id.desc()))).all()
        return [{"id":o.id,"total":o.total,"branch":o.address,"status":o.status,"payment_status":o.payment_status,"wallet_used":o.wallet_used,"card_due":o.card_due,"remaining_due":o.remaining_due,"pickup_code":o.pickup_code,"created_at":str(o.created_at)} for o in rows]
@app.get("/api/shipping/quote")
async def shipping_quote(branch_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        branch=await s.get(Branch,branch_id)
        if not branch or not branch.active: raise HTTPException(404,"BTS filiali topilmadi")
        rows=(await s.execute(select(CartItem,Product).join(Product,Product.id==CartItem.product_id).where(CartItem.user_tg_id==u["id"]))).all()
        if not rows: raise HTTPException(400,"Savat bo‘sh")
        kg=sum(i.quantity for i,p in rows)
        origin=await s.get(Setting,"bts_origin_city")
        origin_city=origin.value.strip() if origin and origin.value.strip() else "Toshkent"
        dest_city=canonical_city(branch.city); origin_city=canonical_city(origin_city)
        tariff_setting=await s.get(Setting,"bts_tariff_type")
        tariff_type=tariff_setting.value if tariff_setting and tariff_setting.value in {"office_to_office","office_to_tashkent_mvo"} else "office_to_office"
        t=await s.scalar(select(BTSTariff).where(BTSTariff.active==True,BTSTariff.origin_city==origin_city,
            BTSTariff.destination_city==dest_city,BTSTariff.tariff_type==tariff_type,
            BTSTariff.kg_min<=kg,BTSTariff.kg_max>=kg).order_by(BTSTariff.kg_min.desc()))
        if not t: raise HTTPException(503,"Ushbu shaharlar/vazn uchun BTS tarifi kiritilmagan. Admin BTS tarif CSV faylini import qilishi kerak.")
        return {"origin_city":origin_city,"destination_city":dest_city,"weight_kg":kg,"delivery_price":t.price,"delivery_days":t.delivery_days,"zone":t.zone,"tariff_type":t.tariff_type,"effective_from":t.effective_from,"vat_included":t.vat_included}

@app.post("/api/checkout")
async def checkout(body:CheckoutIn,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    if body.payment_plan not in ("100","40/60"): raise HTTPException(400,"To'lov rejasi noto'g'ri")
    async with Session() as s:
        user=await s.scalar(select(User).where(User.tg_id==u["id"]))
        branch=await s.get(Branch,body.branch_id)
        if not branch or not branch.active: raise HTTPException(400,"Faol pochta filialini tanlang")
        rows=(await s.execute(select(CartItem,Product).join(Product,Product.id==CartItem.product_id).where(CartItem.user_tg_id==u["id"]))).all()
        if not rows: raise HTTPException(400,"Savat bo'sh")
        total=sum(i.quantity*p.price for i,p in rows)
        weight_kg=sum(i.quantity for i,p in rows)  # User-confirmed rule: 1 product = 1 kg
        origin_setting=await s.get(Setting,"bts_origin_city")
        origin_city=(origin_setting.value.strip() if origin_setting and origin_setting.value.strip() else "Toshkent")
        origin_city=canonical_city(origin_city); dest_city=canonical_city(branch.city)
        tariff_setting=await s.get(Setting,"bts_tariff_type")
        tariff_type=tariff_setting.value if tariff_setting and tariff_setting.value in {"office_to_office","office_to_tashkent_mvo"} else "office_to_office"
        tariff=await s.scalar(select(BTSTariff).where(BTSTariff.active==True,
            BTSTariff.origin_city==origin_city,BTSTariff.destination_city==dest_city,
            BTSTariff.tariff_type==tariff_type,BTSTariff.kg_min<=weight_kg,
            BTSTariff.kg_max>=weight_kg).order_by(BTSTariff.kg_min.desc()))
        if not tariff:
            raise HTTPException(503,f"{origin_city} → {branch.city}, {weight_kg} kg uchun BTS tarifi kiritilmagan. Admin tarif jadvalini yuklashi kerak.")
        delivery_price=tariff.price
        total+=delivery_price
        for i,p in rows:
            if p.stock<i.quantity: raise HTTPException(409,f"{p.title}: qoldiq yetarli emas")
            if i.color or i.size:
                variant=await s.scalar(select(ProductVariant).where(ProductVariant.product_id==p.id,
                    ProductVariant.color==i.color,ProductVariant.size==i.size))
                if variant and variant.stock<i.quantity:
                    raise HTTPException(409,f"{p.title} ({i.color}/{i.size}): variant qoldig‘i yetarli emas")
        discount=0; promo=None
        if body.promo_code.strip():
            promo=await s.scalar(select(PromoCode).where(PromoCode.code==body.promo_code.strip().upper(),PromoCode.active==True))
            if not promo or (promo.usage_limit and promo.used_count>=promo.usage_limit):
                raise HTTPException(400,"Promokod yaroqsiz yoki limiti tugagan")
            if promo.expires_at and promo.expires_at < datetime.utcnow():
                raise HTTPException(400,"Promokod muddati tugagan")
            discount=(total*promo.discount_percent)//100
        total-=discount
        first_stage=total if body.payment_plan=="100" else (total*40+99)//100
        # Hamyon/referral/cashback funksiyalari do‘kon rejasidan chiqarilgan.
        wallet=0
        cashback=0
        card_due=first_stage-wallet-cashback
        remaining_due=total-first_stage if body.payment_plan=="40/60" else 0
        order=Order(user_tg_id=u["id"],total=total,promo_code=(promo.code if promo else ""),delivery_price=delivery_price,weight_kg=weight_kg,address=f"{branch.title}, {branch.city}, {branch.address}",
            payment_plan=body.payment_plan,wallet_used=wallet,cashback_used=cashback,card_due=card_due,remaining_due=remaining_due,
            payment_status="Birinchi to'lov kutilmoqda" if card_due else ("60 foiz keyin to'lanadi" if remaining_due else "To'liq to'landi"))
        s.add(order); await s.flush()
        reservation_expiry=datetime.now(timezone.utc)+timedelta(minutes=5)
        for i,p in rows:
            variant=None
            if i.color or i.size:
                variant=await s.scalar(select(ProductVariant).where(
                    ProductVariant.product_id==p.id,ProductVariant.color==i.color,ProductVariant.size==i.size))
                if not variant:
                    raise HTTPException(409,f"{p.title}: tanlangan rang/o‘lcham varianti topilmadi")
            p.stock-=i.quantity
            if variant: variant.stock-=i.quantity
            s.add(InventoryReservation(order_id=order.id,product_id=p.id,
                variant_id=variant.id if variant else None,quantity=i.quantity,
                status="held" if card_due else "committed",
                expires_at=reservation_expiry if card_due else datetime.now(timezone.utc)))
            s.add(OrderLine(order_id=order.id,product_id=p.id,title=p.title,quantity=i.quantity,unit_price=p.price,color=i.color,size=i.size))
            await s.delete(i)
        if card_due:
            unique_due=await allocate_unique_payment_amount(s, card_due)
            card_due=unique_due
            order.card_due=unique_due
            s.add(Payment(order_id=order.id,expected_amount=unique_due,status="Kutilmoqda"))
        else:
            # Wallet fully covers the first stage; commit it now.
            user.cash_balance-=wallet
            user.bonus_balance-=cashback
            if cashback: s.add(WalletLedger(user_tg_id=u["id"],amount=-cashback,kind="cashback_spend",note=f"Buyurtma #{order.id}"))
            s.add(WalletLedger(user_tg_id=u["id"],amount=-wallet,kind="checkout",note=f"Buyurtma #{order.id}"))
            if remaining_due==0:
                import secrets; order.pickup_code=secrets.token_hex(3).upper()
            if remaining_due:
                unique_due=await allocate_unique_payment_amount(s, remaining_due)
            s.add(Payment(order_id=order.id,expected_amount=unique_due,status="Ikkinchi bosqich kutilmoqda"))
        if promo and not card_due: promo.used_count+=1
        await s.commit()
        order_lines = (await s.scalars(select(OrderLine).where(OrderLine.order_id==order.id))).all()
        product_details = []
        for line in order_lines:
            product = await s.get(Product, line.product_id)
            image_link = (product.image_url if product else "") or "Rasm biriktirilmagan"
            product_details.append(
                f"• {line.title} | Rang: {line.color or 'Ko‘rsatilmagan'} | "
                f"Razmer: {line.size or 'Ko‘rsatilmagan'} | Soni: {line.quantity} dona | "
                f"Narx: {line.unit_price:,} so‘m | Rasm: {image_link}".replace(",", " ")
            )
        import html
        customer_name = html.escape(user.full_name or str(u["id"]))
        customer_phone = html.escape(user.phone or "Kiritilmagan")
        alert = (
            f"🛍 <b>YANGI BUYURTMA #{order.id}</b>\\n"
            f"👤 Mijoz: {customer_name}\\n🆔 Telegram ID: <code>{u['id']}</code>\\n"
            f"📞 Telefon: {customer_phone}\\n\\n"
            f"📦 <b>Mahsulotlar:</b>\\n" + "\\n".join(product_details) + "\\n\\n"
            f"💰 Jami: {total:,} so‘m\\n".replace(",", " ") +
            f"💳 To‘lov rejasi: {body.payment_plan}\\n"
            f"✅ To‘lanishi kerak: {card_due:,} so‘m\\n".replace(",", " ") +
            f"⏳ Qolgan to‘lov: {remaining_due:,} so‘m\\n".replace(",", " ") +
            f"🚚 Pochta: BTS\\n🏢 Filial: {branch.title}\\n"
            f"📍 Manzil: {branch.city}, {branch.address}\\n"
            f"📅 Sana: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        await notify_admins(alert)
        return {"ok":True,"order_id":order.id,"total":total,"delivery_price":delivery_price,"weight_kg":weight_kg,"discount":discount,"wallet_reserved":wallet,"cashback_used":cashback,
            "card_due":card_due,"remaining_due":remaining_due,"payment_plan":body.payment_plan,
            "payment_status":order.payment_status,"payment_window_minutes":5 if card_due else 0,
            "note":"To‘lovni aynan ko‘rsatilgan noyob summa bilan amalga oshiring. Boshqa summa to‘lovi avtomatik aniqlanmasligi mumkin."}


@app.put("/api/cart/{item_id}")
async def update_cart(item_id:int, body:CartUpdate, x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        item=await s.scalar(select(CartItem).where(CartItem.id==item_id,CartItem.user_tg_id==u["id"]))
        if not item: raise HTTPException(404,"Savat elementi topilmadi")
        product=await s.get(Product,item.product_id)
        if not product or body.quantity>product.stock: raise HTTPException(409,"Omborda yetarli mahsulot yo‘q")
        item.quantity=body.quantity
        await s.commit()
        return {"ok":True}

@app.delete("/api/cart/{item_id}")
async def delete_cart(item_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        item=await s.scalar(select(CartItem).where(CartItem.id==item_id,CartItem.user_tg_id==u["id"]))
        if item: await s.delete(item); await s.commit()
        return {"ok":True}

@app.get("/api/favorites")
async def favorites(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.execute(select(Product).join(Favorite,Favorite.product_id==Product.id).where(Favorite.user_tg_id==u["id"]))).scalars().all()
        return [{"id":p.id,"title":p.title,"price":p.price,"image_url":p.image_url} for p in rows]

@app.post("/api/favorites/{product_id}")
async def toggle_favorite(product_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        row=await s.scalar(select(Favorite).where(Favorite.user_tg_id==u["id"],Favorite.product_id==product_id))
        if row: await s.delete(row); result=False
        else: s.add(Favorite(user_tg_id=u["id"],product_id=product_id)); result=True
        await s.commit()
        return {"ok":True,"favorite":result}

@app.get("/api/products/{product_id}/reviews")
async def product_reviews(product_id:int):
    async with Session() as s:
        rows=(await s.scalars(select(Review).where(Review.product_id==product_id,Review.moderation_status=="approved").order_by(Review.id.desc()).limit(100))).all()
        return [{"rating":r.rating,"comment":r.comment,"created_at":str(r.created_at)} for r in rows]

@app.post("/api/products/{product_id}/reviews")
async def add_review(product_id:int,body:ReviewIn,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        bought=await s.scalar(select(Order.id).join(OrderLine,OrderLine.order_id==Order.id).where(Order.user_tg_id==u["id"],OrderLine.product_id==product_id,Order.payment_status=="To‘liq to‘landi"))
        if not bought: raise HTTPException(403,"Sharh faqat xarid qilgan mijozlar uchun")
        s.add(Review(user_tg_id=u["id"],product_id=product_id,rating=body.rating,comment=body.comment[:1500]))
        await s.commit()
        return {"ok":True}

@app.post("/api/promo/validate")
async def validate_promo(body:PromoIn,x_telegram_init_data:str=Header(default="")):
    await require_user(x_telegram_init_data)
    async with Session() as s:
        p=await s.scalar(select(PromoCode).where(PromoCode.code==body.code.strip().upper(),PromoCode.active==True))
        if not p: raise HTTPException(404,"Promokod yaroqsiz")
        if p.usage_limit and p.used_count>=p.usage_limit: raise HTTPException(400,"Promokod limiti tugagan")
        if p.expires_at and p.expires_at < __import__("datetime").datetime.utcnow(): raise HTTPException(400,"Promokod muddati tugagan")
        return {"ok":True,"discount_percent":p.discount_percent}

@app.get("/api/payment-method")

async def payment_method(x_telegram_init_data:str=Header(default="")):
    await require_user(x_telegram_init_data)
    async with Session() as s:
        vals={}
        for key in ("card_number","card_holder"):
            row=await s.get(Setting,key)
            vals[key]=row.value if row else ""
        return {"card_number":vals["card_number"],"card_holder":vals["card_holder"],
                "configured":bool(vals["card_number"] and vals["card_holder"]),
                "instruction":"To‘lovni aynan buyurtmada ko‘rsatilgan summada amalga oshiring. Boshqa miqdordagi to‘lov avtomatik aniqlanmasligi yoki admin tekshiruviga tushishi mumkin."}

@app.get("/api/admin/payments")
async def admin_payments(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","finance"})
    async with Session() as s:
        rows=(await s.scalars(select(Payment).order_by(Payment.id.desc()).limit(200))).all()
        return [{"id":p.id,"order_id":p.order_id,"expected_amount":p.expected_amount,"status":p.status,"transaction_id":p.transaction_id,"created_at":str(p.created_at)} for p in rows]


@app.delete("/api/admin/products/{product_id}")
async def delete_product(product_id:int,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    async with Session() as s:
        p=await s.get(Product,product_id)
        if not p: raise HTTPException(404,"Mahsulot topilmadi")
        # Preserve order history; hide product instead of destructive deletion.
        p.active=False
        await s.commit()
        return {"ok":True,"archived":True}

@app.post("/api/admin/wallet/adjust")
async def adjust_wallet(body:WalletAdjustIn,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","finance"})
    if body.amount==0: raise HTTPException(400,"Summa nol bo‘lmasin")
    async with Session() as s:
        user=await s.scalar(select(User).where(User.tg_id==body.tg_id))
        if not user: raise HTTPException(404,"Foydalanuvchi topilmadi")
        if user.cash_balance+body.amount<0: raise HTTPException(400,"Balans manfiy bo‘lib qoladi")
        user.cash_balance+=body.amount
        s.add(WalletLedger(user_tg_id=body.tg_id,amount=body.amount,kind="admin_adjust",note=body.note[:500]))
        await s.commit()
        return {"ok":True,"cash_balance":user.cash_balance}

@app.post("/api/admin/payments/{payment_id}/decision")
async def payment_decision(payment_id:int,body:PaymentDecision,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","finance"})
    if body.decision not in ("approve","reject"): raise HTTPException(400,"decision approve yoki reject bo‘lishi kerak")
    async with Session() as s:
        p=await s.get(Payment,payment_id)
        if not p: raise HTTPException(404,"To‘lov topilmadi")
        if p.status=="Tasdiqlandi": raise HTTPException(409,"To‘lov allaqachon tasdiqlangan")
        order=await s.get(Order,p.order_id)
        if body.decision=="reject":
            p.status="Rad etildi"; p.raw_message=(p.raw_message+"\\nAdmin: "+body.note)[:2000]
            if order: order.payment_status="To‘lov rad etildi"
        else:
            p.status="Tasdiqlandi"; p.confirmed_at=__import__("datetime").datetime.utcnow()
            if order:
                is_second = (order.payment_plan=="40/60" and order.payment_status=="60% to‘lov kutilmoqda")
                if not is_second:
                    user=await s.scalar(select(User).where(User.tg_id==order.user_tg_id))
                    if user and order.wallet_used:
                        if user.cash_balance < order.wallet_used: raise HTTPException(409,"Hamyon rezervi yetarli emas")
                        user.cash_balance-=order.wallet_used
                        s.add(WalletLedger(user_tg_id=user.tg_id,amount=-order.wallet_used,kind="checkout",note=f"Buyurtma #{order.id}"))
                    lines=(await s.scalars(select(OrderLine).where(OrderLine.order_id==order.id))).all()
                    for line in lines:
                        prod=await s.get(Product,line.product_id)
                        if prod:
                            if prod.stock<line.quantity: raise HTTPException(409,"Ombor qoldig‘i yetarli emas")
                            prod.stock-=line.quantity
                            if line.color or line.size:
                                variant=await s.scalar(select(ProductVariant).where(
                                    ProductVariant.product_id==prod.id,
                                    ProductVariant.color==line.color,
                                    ProductVariant.size==line.size))
                                if variant:
                                    if variant.stock < line.quantity:
                                        raise HTTPException(409,"Variant omborida qoldiq yetarli emas")
                                    variant.stock -= line.quantity
                if not is_second and order.promo_code:
                    used_promo=await s.scalar(select(PromoCode).where(PromoCode.code==order.promo_code))
                    if used_promo:
                        used_promo.used_count += 1
                if order.payment_plan=="40/60" and order.remaining_due and not is_second:
                    order.payment_status="40% to'landi — 60% BTS punktiga yetgach"
                    unique_due=await allocate_unique_payment_amount(s, order.remaining_due)
                    order.remaining_due=unique_due
                    s.add(Payment(order_id=order.id,expected_amount=unique_due,status="BTS kelishini kutmoqda"))
                else:
                    order.payment_status="To‘liq to‘landi"
                    if not order.pickup_code:
                        import secrets; order.pickup_code=secrets.token_hex(3).upper()
        await s.commit()
        return {"ok":True,"status":p.status}

@app.post("/api/admin/promos")
async def create_promo(body:dict,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager","catalog"})
    code=str(body.get("code"," ")).strip().upper()
    percent=int(body.get("discount_percent",0)); limit=max(0,int(body.get("usage_limit",0)))
    expires_raw=str(body.get("expires_at","")).strip()
    if not re.fullmatch(r"[A-Z0-9_-]{3,40}",code): raise HTTPException(400,"Kod 3–40 belgi: A–Z, 0–9, _ yoki -")
    if not 1<=percent<=100: raise HTTPException(400,"Chegirma 1–100 foiz oralig‘ida bo‘lsin")
    try: expires=datetime.fromisoformat(expires_raw) if expires_raw else None
    except ValueError: raise HTTPException(400,"Amal qilish muddati noto‘g‘ri")
    async with Session() as s:
        if await s.scalar(select(PromoCode.id).where(PromoCode.code==code)): raise HTTPException(409,"Bu promokod mavjud")
        p=PromoCode(code=code,discount_percent=percent,discount_amount=0,usage_limit=limit,expires_at=expires,active=True)
        s.add(p); await s.commit(); return {"ok":True,"id":p.id}

@app.put("/api/admin/promos/{promo_id}")
async def update_promo(promo_id:int,body:dict,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager","catalog"})
    percent=int(body.get("discount_percent",0)); limit=max(0,int(body.get("usage_limit",0))); raw=str(body.get("expires_at","")).strip()
    if not 1<=percent<=100: raise HTTPException(400,"Chegirma 1–100 foiz oralig‘ida bo‘lsin")
    try: expires=datetime.fromisoformat(raw) if raw else None
    except ValueError: raise HTTPException(400,"Amal qilish muddati noto‘g‘ri")
    async with Session() as s:
        p=await s.get(PromoCode,promo_id)
        if not p: raise HTTPException(404,"Promokod topilmadi")
        p.discount_percent=percent; p.discount_amount=0; p.usage_limit=limit; p.expires_at=expires
        await s.commit(); return {"ok":True}

@app.post("/api/admin/promos/{promo_id}/toggle")
async def toggle_promo(promo_id:int,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager","catalog"})
    async with Session() as s:
        p=await s.get(PromoCode,promo_id)
        if not p: raise HTTPException(404,"Promokod topilmadi")
        p.active=not p.active; await s.commit(); return {"ok":True,"active":p.active}

@app.delete("/api/admin/promos/{promo_id}")
async def delete_promo(promo_id:int,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        p=await s.get(PromoCode,promo_id)
        if not p: raise HTTPException(404,"Promokod topilmadi")
        await s.delete(p); await s.commit(); return {"ok":True}


@app.post("/api/admin/orders/{order_id}/arrived")
async def mark_order_arrived(order_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        order=await s.get(Order,order_id)
        if not order: raise HTTPException(404,"Buyurtma topilmadi")
        order.status="BTS filialiga yetib keldi"
        tg_id=order.user_tg_id
        due=order.remaining_due if order.payment_plan=="40/60" else 0
        if due>0 and order.payment_status not in ("To‘liq to‘landi","To‘liq tolandi"):
            existing=await s.scalar(select(Payment).where(
                Payment.order_id==order_id,Payment.expected_amount==due,
                Payment.status.in_(["Kutilmoqda","BTS kelishini kutmoqda","Tasdiqlandi"])))
            already=bool(existing and existing.status=="Kutilmoqda" and order.payment_status=="60% to‘lov kutilmoqda")
            if existing and existing.status=="BTS kelishini kutmoqda":
                existing.status="Kutilmoqda"; existing.created_at=datetime.now(timezone.utc)
            elif not existing:
                due=await allocate_unique_payment_amount(s, due)
                order.remaining_due=due
                s.add(Payment(order_id=order_id,expected_amount=due,status="Kutilmoqda"))
            order.second_payment_requested_at=datetime.now(timezone.utc)
            order.payment_status="60% to‘lov kutilmoqda"
        else:
            already=True
            if order.payment_status in ("To‘liq to‘landi","To‘liq tolandi") and not order.pickup_code:
                order.pickup_code=secrets.token_hex(3).upper()
        pickup=order.pickup_code if order.payment_status in ("To‘liq to‘landi","To‘liq tolandi") else ""
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        photo=sh.photo_url if sh else ""
        tracking=sh.tracking_code if sh else ""
        await s.commit()
    if BOT_TOKEN:
        from aiogram import Bot
        from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        bot=Bot(BOT_TOKEN)
        try:
            msg=f"📦 <b>Buyurtma #{order_id}</b> BTS filialiga yetib keldi.\\n"
            if tracking: msg+=f"🚚 Pochta ID: <code>{tracking}</code>\\n"
            keyboard=None
            if due>0:
                msg+=f"💳 Qolgan 60% to‘lov: <b>{due:,} so‘m</b>\\n⏳ To‘lov muddati: 5 kun.\\n\\nTushunmovchilik yoki qiyinchilik bo‘lsa, qo‘llab-quvvatlash xizmatiga yoki admin Telegram’iga murojaat qiling.\\n\\nTo‘lovni yakunlash uchun quyidagi tugmani bosing."
                separator="&" if "?" in WEBAPP_URL else "?"
                order_url=f"{WEBAPP_URL}{separator}order_id={order_id}"
                keyboard=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="💳 To‘lovni yakunlash",web_app=WebAppInfo(url=order_url))
                ]])
            else:
                msg+="To‘lovingiz to‘liq.\\n"
                if pickup: msg+=f"🔐 BTS olish kodi: <b>{pickup}</b>\\n"
                msg+="Tushunmovchilik yoki qiyinchilik bo‘lsa, qo‘llab-quvvatlash xizmatiga yoki admin Telegram’iga murojaat qiling."
            if photo and photo.startswith("/uploads/"):
                local=os.path.join(UPLOAD_DIR,os.path.basename(photo))
                if os.path.isfile(local): await bot.send_photo(tg_id,FSInputFile(local),caption=msg,parse_mode="HTML",reply_markup=keyboard)
                else: await bot.send_message(tg_id,msg,parse_mode="HTML",reply_markup=keyboard)
            elif photo.startswith(("http://","https://")):
                await bot.send_photo(tg_id,photo,caption=msg,parse_mode="HTML",reply_markup=keyboard)
            else: await bot.send_message(tg_id,msg,parse_mode="HTML",reply_markup=keyboard)
        finally:
            await bot.session.close()
    return {"ok":True,"second_payment":due}

@app.post("/api/admin/admins/role")
async def set_admin_role(body:AdminRoleIn,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner"})
    if body.role not in ("owner","manager","finance","catalog"): raise HTTPException(400,"Rol noto‘g‘ri")
    async with Session() as s:
        a=await s.get(Admin,body.tg_id)
        if not a: raise HTTPException(404,"Admin topilmadi")
        a.role=body.role
        await s.commit()
        return {"ok":True,"role":a.role}

@app.get("/api/admin/summary")
async def admin_summary(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        return {"users":await s.scalar(select(func.count(User.id))) or 0,"products":await s.scalar(select(func.count(Product.id))) or 0,"orders":await s.scalar(select(func.count(Order.id))) or 0,"sales":await s.scalar(select(func.coalesce(func.sum(Order.total),0))) or 0}
@app.get("/api/admin/orders")
async def admin_orders(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Order).order_by(Order.id.desc()).limit(200))).all()
        return [{"id":o.id,"user":o.user_tg_id,"total":o.total,"branch":o.address,"status":o.status,"payment_status":o.payment_status,"wallet_used":o.wallet_used,"card_due":o.card_due,"remaining_due":o.remaining_due,"pickup_code":o.pickup_code} for o in rows]
@app.put("/api/admin/orders/{order_id}")
async def update_order(order_id:int,body:dict,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        o=await s.get(Order,order_id)
        if not o: raise HTTPException(404,"Buyurtma topilmadi")
        if "status" in body: o.status=str(body["status"])[:40]
        if "payment_status" in body:
            new_status=str(body["payment_status"])[:40]
            o.payment_status=new_status
            if new_status.lower() in ("to'liq to'landi","to'liq tolandi","paid","to'liq to'lov tasdiqlandi") and o.status=="BTS filialiga yetib keldi" and not o.pickup_code:
                import secrets
                o.pickup_code=secrets.token_hex(3).upper()
        await s.commit()
        return {"ok":True}
@app.get("/api/admin/user/{tg_id}")
async def admin_user(tg_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        u=await s.scalar(select(User).where(User.tg_id==tg_id))
        if not u: raise HTTPException(404,"Foydalanuvchi topilmadi")
        orders=(await s.scalars(select(Order).where(Order.user_tg_id==tg_id).order_by(Order.id.desc()))).all()
        return {"id":u.tg_id,"username":u.username,"name":u.full_name,"phone":u.phone,"blocked":u.is_blocked,"cash_balance":u.cash_balance,"bonus_balance":u.bonus_balance,"orders":[{"id":o.id,"total":o.total,"status":o.status,"payment_status":o.payment_status} for o in orders]}
@app.get("/api/admin/products")
async def admin_products(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Product).order_by(Product.id.desc()))).all()
        return [{"id":p.id,"title":p.title,"price":p.price,"stock":p.stock,"active":p.active} for p in rows]

async def publish_product_to_channel(product_id:int):
    """Publish newly created product to configured Telegram channel (best effort)."""
    if not BOT_TOKEN:
        return False
    from aiogram import Bot
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from html import escape
    async with Session() as s:
        p=await s.get(Product,product_id)
        ch=await s.get(Setting,"product_channel_id")
        tpl=await s.get(Setting,"product_post_template")
        if not p or not p.active or not ch or not ch.value.strip():
            return False
        channel=ch.value.strip()
        template=tpl.value if tpl and tpl.value.strip() else (
            "🛍 <b>{title}</b>\\n\\n{description}\\n\\n"
            "💰 <b>{price} so‘m</b>\\n{old_price}\\n"
            "📦 Mavjud: {stock} dona\\n\\n"
            "🛒 Buyurtma: @OnlineXaridBot"
        )
        vals={
            "title":escape(p.title),
            "description":escape(p.description or ""),
            "price":f"{p.price:,}".replace(",", " "),
            "old_price":f"Eski narx: {p.old_price:,} so‘m" if p.old_price else "",
            "stock":str(p.stock),
            "category":escape(p.category or ""),
            "product_id":str(p.id),
        }
        try:
            caption=template.format(**vals)[:1024]
        except Exception:
            caption=(f"🛍 <b>{escape(p.title)}</b>\\n\\n{escape(p.description or '')}\\n"
                     f"💰 <b>{p.price:,} so‘m</b>\\n📦 {p.stock} dona")[:1024]
        image_url=p.image_url
    bot=Bot(BOT_TOKEN)
    try:
        markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🛒 Buyurtma berish",url=WEBAPP_URL)
        ]])
        if image_url and image_url.startswith(("http://","https://")):
            await bot.send_photo(channel,image_url,caption=caption,parse_mode="HTML",reply_markup=markup)
        elif image_url and image_url.startswith("/uploads/"):
            local=os.path.join(UPLOAD_DIR,os.path.basename(image_url))
            if os.path.isfile(local):
                from aiogram.types import FSInputFile
                await bot.send_photo(channel,FSInputFile(local),caption=caption,parse_mode="HTML",reply_markup=markup)
            else:
                await bot.send_message(channel,caption,parse_mode="HTML",reply_markup=markup)
        else:
            await bot.send_message(channel,caption,parse_mode="HTML",reply_markup=markup)
        return True
    except Exception as exc:
        print("Product channel publish failed:",exc)
        return False
    finally:
        await bot.session.close()


@app.post("/api/admin/products")
async def create_product(body:ProductIn,x_telegram_init_data:str=Header(default="")):
    u=await require_admin(x_telegram_init_data)
    async with Session() as s:
        p=Product(**body.model_dump());s.add(p);await s.commit()
        pid=p.id
        await audit(s,u["id"],"product_create",str(pid),p.title)
        await s.commit()
    return {"ok":True,"id":pid,"channel_posted":False}
@app.put("/api/admin/products/{product_id}")
async def update_product(product_id:int,body:ProductIn,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        p=await s.get(Product,product_id)
        if not p: raise HTTPException(404,"Mahsulot topilmadi")
        for k,v in body.model_dump().items(): setattr(p,k,v)
        await s.commit();return {"ok":True}
@app.get("/api/admin/branches")
async def admin_branches(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Branch).order_by(Branch.id.desc()))).all()
        return [{"id":b.id,"title":b.title,"address":b.address,"city":b.city,"active":b.active} for b in rows]
@app.post("/api/admin/branches")
async def create_branch(body:BranchIn,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        b=Branch(**body.model_dump());s.add(b);await s.commit();return {"ok":True,"id":b.id}
@app.put("/api/admin/branches/{branch_id}")
async def update_branch(branch_id:int,body:BranchIn,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        b=await s.get(Branch,branch_id)
        if not b: raise HTTPException(404,"Filial topilmadi")
        for k,v in body.model_dump().items():setattr(b,k,v)
        await s.commit();return {"ok":True}
@app.get("/api/admin/admins")
async def admins(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Admin).order_by(Admin.tg_id))).all()
        return [{"tg_id":a.tg_id,"role":a.role} for a in rows]
@app.post("/api/admin/admins")
async def add_admin(body:AdminIn,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        if await s.get(Admin,body.tg_id):raise HTTPException(409,"Admin mavjud")
        s.add(Admin(tg_id=body.tg_id));await s.commit();return {"ok":True}
@app.delete("/api/admin/admins/{tg_id}")
async def remove_admin(tg_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Admin))).all()
        if len(rows)<=1:raise HTTPException(400,"Oxirgi adminni o'chirib bo'lmaydi")
        a=await s.get(Admin,tg_id)
        if not a:raise HTTPException(404,"Admin topilmadi")
        await s.delete(a);await s.commit();return {"ok":True}
@app.get("/api/admin/settings")
async def get_admin_settings(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    keys=("card_number","card_holder","card_last4","telegram_api_id","telegram_phone","card_notice_source")
    async with Session() as s:
        result={}
        for key in keys:
            row=await s.get(Setting,key)
            result[key]=row.value if row else ""
        # Never send API HASH back to the browser.
        row=await s.get(Setting,"telegram_api_hash")
        result["telegram_api_hash_configured"]=bool(row and row.value)
        return result

@app.put("/api/admin/settings")
async def save_settings(body:SettingIn,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    values=body.model_dump()
    card_number=re.sub(r"\s+", "", str(values.get("card_number") or ""))
    card_holder=str(values.get("card_holder") or "").strip()
    if card_number and (not card_number.isdigit() or not 16 <= len(card_number) <= 19):
        raise HTTPException(400, "Karta raqami 16–19 ta raqamdan iborat bo‘lishi kerak")
    if card_holder and len(card_holder) < 3:
        raise HTTPException(400, "Karta egasining ism-familiyasini kiriting")
    values["card_number"]=card_number
    values["card_holder"]=card_holder
    if card_number:
        values["card_last4"]=card_number[-4:]
    async with Session() as s:
        for key,value in values.items():
            if value is None or value == "":
                continue
            row=await s.get(Setting,key)
            if not row:
                row=Setting(key=key,value="");s.add(row)
            if key=="telegram_api_hash":
                row.value=encrypt_secret(value)
            else:
                row.value=str(value).strip()
        await s.commit()
    return {"ok":True,"message":"Karta va kuzatuv sozlamalari saqlandi. Listenerni qayta ishga tushiring."}


@app.post("/api/admin/products/{product_id}/upload")
async def upload_product_media(product_id:int, file:UploadFile=File(...), x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    allowed={"image/jpeg":".jpg","image/png":".png","image/webp":".webp","video/mp4":".mp4"}
    if file.content_type not in allowed: raise HTTPException(415,"Faqat JPG, PNG, WEBP yoki MP4 fayl")
    data=await file.read()
    if not data or len(data)>12*1024*1024: raise HTTPException(413,"Fayl 12 MB dan kichik bo‘lishi kerak")
    async with Session() as s:
        p=await s.get(Product,product_id)
        if not p: raise HTTPException(404,"Mahsulot topilmadi")
        name=secrets.token_hex(16)+allowed[file.content_type]
        pathlib.Path(UPLOAD_DIR).mkdir(parents=True,exist_ok=True)
        with open(os.path.join(UPLOAD_DIR,name),"wb") as out: out.write(data)
        url="/uploads/"+name
        s.add(ProductMedia(product_id=product_id,media_type="video" if file.content_type=="video/mp4" else "image",url=url))
        if not p.image_url: p.image_url=url
        pid=p.id
        await s.commit()
    return {"ok":True,"url":url,"channel_posted":False}

# Extended commerce, BTS manual operations, support and audit endpoints.
@app.get("/api/compare")
async def get_compare(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.execute(select(Product).join(Comparison,Comparison.product_id==Product.id).where(Comparison.user_tg_id==u["id"]))).scalars().all()
        return [{"id":p.id,"title":p.title,"price":p.price,"category":p.category,"description":p.description,"image_url":p.image_url} for p in rows]

@app.post("/api/compare/{product_id}")
async def toggle_compare(product_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        row=await s.scalar(select(Comparison).where(Comparison.user_tg_id==u["id"],Comparison.product_id==product_id))
        if row: await s.delete(row); added=False
        else:
            count=await s.scalar(select(func.count(Comparison.id)).where(Comparison.user_tg_id==u["id"]))
            if count>=4: raise HTTPException(400,"Taqqoslashda ko‘pi bilan 4 ta mahsulot")
            s.add(Comparison(user_tg_id=u["id"],product_id=product_id)); added=True
        await s.commit(); return {"ok":True,"added":added}

@app.get("/api/products/{product_id}/media")
async def product_media(product_id:int):
    async with Session() as s:
        rows=(await s.scalars(select(ProductMedia).where(ProductMedia.product_id==product_id))).all()
        return [{"type":m.media_type,"url":m.url} for m in rows]

@app.post("/api/admin/products/{product_id}/media")
async def add_product_media(product_id:int,body:dict,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    kind=str(body.get("type","image")); url=str(body.get("url","")).strip()
    if kind not in ("image","video") or not url.startswith(("https://","http://")): raise HTTPException(400,"Media turi yoki URL noto‘g‘ri")
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        s.add(ProductMedia(product_id=product_id,media_type=kind,url=url)); await s.commit(); return {"ok":True}

@app.get("/api/admin/products/{product_id}/variants")
async def list_variants(product_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(ProductVariant).where(ProductVariant.product_id==product_id))).all()
        return [{"id":v.id,"color":v.color,"size":v.size,"stock":v.stock} for v in rows]

@app.post("/api/admin/products/{product_id}/variants")
async def save_variant(product_id:int,body:dict,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    color=str(body.get("color",""))[:50]; size=str(body.get("size",""))[:30]; stock=int(body.get("stock",0))
    if stock<0: raise HTTPException(400,"Qoldiq manfiy bo‘lmaydi")
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        v=await s.scalar(select(ProductVariant).where(ProductVariant.product_id==product_id,ProductVariant.color==color,ProductVariant.size==size))
        if v: v.stock=stock
        else: s.add(ProductVariant(product_id=product_id,color=color,size=size,stock=stock))
        await s.commit(); return {"ok":True}

@app.post("/api/referral/claim")
async def referral_claim(body:dict,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data); inviter=int(body.get("inviter_tg_id",0))
    if not inviter or inviter==u["id"]: raise HTTPException(400,"Referral kodi noto‘g‘ri")
    async with Session() as s:
        if not await s.scalar(select(User).where(User.tg_id==inviter)): raise HTTPException(404,"Taklif qiluvchi topilmadi")
        if await s.scalar(select(Referral.id).where(Referral.invited_tg_id==u["id"])): raise HTTPException(409,"Referral avval ishlatilgan")
        s.add(Referral(inviter_tg_id=inviter,invited_tg_id=u["id"]))
        await s.commit(); return {"ok":True,"message":"Taklif ro‘yxatga olindi; bonus birinchi muvaffaqiyatli xariddan keyin beriladi"}

@app.get("/api/referral")
async def referral_info(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        count=await s.scalar(select(func.count(Referral.id)).where(Referral.inviter_tg_id==u["id"]))
        return {"referrals":count or 0,"referral_code":str(u["id"])}

@app.post("/api/support/messages")
async def send_support(body:dict,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data); msg=str(body.get("message","")).strip()
    if not msg or len(msg)>4000: raise HTTPException(400,"Xabar 1–4000 belgi bo‘lsin")
    async with Session() as s:
        s.add(SupportMessage(user_tg_id=u["id"],order_id=body.get("order_id"),sender_role="user",message=msg))
        await s.commit()
        user = await s.scalar(select(User).where(User.tg_id==u["id"]))
        import html
        support_alert = (
            "💬 <b>YANGI QO‘LLAB-QUVVATLASH XABARI</b>\\n"
            f"👤 Mijoz: {html.escape((user.full_name if user else '') or 'Noma’lum')}\\n"
            f"🆔 Telegram ID: <code>{u['id']}</code>\\n"
            f"📞 Telefon: {html.escape((user.phone if user else '') or 'Kiritilmagan')}\\n"
            f"📦 Buyurtma: #{body.get('order_id') or 'Ko‘rsatilmagan'}\\n\\n"
            f"✉️ Xabar: {html.escape(msg)}"
        )
        await notify_admins(support_alert)
        return {"ok":True}

@app.get("/api/support/messages")
async def get_support(order_id:int=0,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(SupportMessage).where(SupportMessage.user_tg_id==u["id"],SupportMessage.order_id== (order_id or None)).order_by(SupportMessage.id))).all()
        return [{"id":m.id,"sender":m.sender_role,"message":m.message,"created_at":str(m.created_at)} for m in rows]

@app.post("/api/admin/shipments/{order_id}")
async def upsert_shipment(order_id:int,body:dict,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        order=await s.get(Order,order_id)
        if not order: raise HTTPException(404,"Buyurtma topilmadi")
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if not sh: sh=Shipment(order_id=order_id); s.add(sh)
        sh.carrier=str(body.get("carrier","BTS"))[:30]
        sh.tracking_code=str(body.get("tracking_code",""))[:100]
        sh.status=str(body.get("status","Tayyorlanmoqda"))[:100]
        sh.estimated_date=str(body.get("estimated_date",""))[:40]
        sh.delivery_price=max(0,int(body.get("delivery_price",0)))
        sh.photo_url=str(body.get("photo_url",""))[:500]
        order.status=sh.status
        if sh.status.lower() in ("filialga yetib keldi","bts punktiga yetib keldi","arrived"):
            order.status="BTS punktiga yetib keldi"
        await s.commit(); return {"ok":True}

@app.get("/api/orders/{order_id}/shipment")
async def shipment_status(order_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        order=await s.scalar(select(Order).where(Order.id==order_id,Order.user_tg_id==u["id"]))
        if not order: raise HTTPException(404,"Buyurtma topilmadi")
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if not sh: return {"available":False}
        return {"available":True,"carrier":sh.carrier,"tracking_code":sh.tracking_code,"status":sh.status,"estimated_date":sh.estimated_date,"delivery_price":sh.delivery_price,"photo_url":sh.photo_url,"pickup_code":(sh.pickup_code or order.pickup_code) if (order.payment_status in ("To‘liq to‘landi","To‘liq tolandi") and order.status=="BTS filialiga yetib keldi") else "","pickup_code_type":"Do‘konning ichki olish kodi; BTS tomonidan berilgan kod emas" if (sh.pickup_code or order.pickup_code) else ""}

@app.post("/api/admin/shipments/{order_id}/photo")
async def upload_shipment_photo(order_id:int,file:UploadFile=File(...),x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    allowed={"image/jpeg":".jpg","image/png":".png","image/webp":".webp"}
    if file.content_type not in allowed: raise HTTPException(415,"Faqat JPG, PNG yoki WEBP rasm")
    data=await file.read()
    if not data or len(data)>10*1024*1024: raise HTTPException(413,"Rasm 10 MB dan kichik bo‘lsin")
    async with Session() as s:
        order=await s.get(Order,order_id)
        if not order: raise HTTPException(404,"Buyurtma topilmadi")
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if not sh: sh=Shipment(order_id=order_id); s.add(sh)
        name=secrets.token_hex(16)+allowed[file.content_type]
        pathlib.Path(UPLOAD_DIR).mkdir(parents=True,exist_ok=True)
        with open(os.path.join(UPLOAD_DIR,name),"wb") as out: out.write(data)
        sh.photo_url="/uploads/"+name
        await s.commit()
        return {"ok":True,"photo_url":sh.photo_url}


@app.get("/api/admin/shipments")
async def admin_shipments(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Shipment).order_by(Shipment.id.desc()))).all()
        return [{"order_id":x.order_id,"carrier":x.carrier,"tracking_code":x.tracking_code,"status":x.status,"estimated_date":x.estimated_date,"delivery_price":x.delivery_price,"pickup_code":x.pickup_code,"photo_url":x.photo_url} for x in rows]

@app.get("/api/admin/audit")
async def audit_logs(x_telegram_init_data:str=Header(default="")):
    u=await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(300))).all()
        return [{"admin":x.admin_tg_id,"action":x.action,"target":x.target,"details":x.details,"created_at":str(x.created_at)} for x in rows]

@app.get("/api/admin/products/export.csv")
async def export_products(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Product).order_by(Product.id))).all()
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(["id","title","description","price","old_price","category","stock","image_url","active"])
        for p in rows: w.writerow([p.id,p.title,p.description,p.price,p.old_price,p.category,p.stock,p.image_url,p.active])
        return StreamingResponse(iter([buf.getvalue()]),media_type="text/csv; charset=utf-8",headers={"Content-Disposition":"attachment; filename=products.csv"})

@app.post("/api/admin/support/reply")
async def admin_support_reply(body:dict,x_telegram_init_data:str=Header(default="")):
    u=await require_admin(x_telegram_init_data); tg_id=int(body.get("tg_id",0)); msg=str(body.get("message","")).strip()
    if not tg_id or not msg: raise HTTPException(400,"tg_id va message kerak")
    async with Session() as s:
        s.add(SupportMessage(user_tg_id=tg_id,order_id=body.get("order_id"),sender_role="admin",message=msg[:4000]))
        await s.commit()
    if BOT_TOKEN:
        from aiogram import Bot
        bot = Bot(BOT_TOKEN)
        try:
            import html
            await bot.send_message(tg_id, "💬 <b>Qo‘llab-quvvatlash javobi:</b>\\n" + html.escape(msg[:3900]), parse_mode="HTML")
        except Exception:
            pass
        finally:
            await bot.session.close()
    return {"ok":True}

@app.post("/api/admin/orders/{order_id}/pickup-code")
async def generate_pickup_code(order_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        o=await s.get(Order,order_id)
        if not o: raise HTTPException(404,"Buyurtma topilmadi")
        if o.payment_status not in ("To‘liq to‘landi","To‘liq tolandi"):
            raise HTTPException(409,"Olish kodi faqat 100% to‘lov tasdiqlangandan keyin beriladi")
        if o.status not in ("BTS filialiga yetib keldi","BTS punktiga yetib keldi","Filialga yetib keldi"):
            raise HTTPException(409,"Olish kodi faqat buyurtma BTS filialiga yetib kelgach beriladi")
        if not o.pickup_code: o.pickup_code=secrets.token_hex(3).upper()
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if sh: sh.pickup_code=o.pickup_code
        tg_id=o.user_tg_id
        code=o.pickup_code
        await s.commit()
    if BOT_TOKEN:
        from aiogram import Bot
        bot=Bot(BOT_TOKEN)
        try:
            await bot.send_message(tg_id,f"🔐 Buyurtma #{order_id} uchun topshirish kodingiz: <b>{code}</b>\n\nBu do‘konning ichki kodi, BTS tomonidan berilgan kod emas. Uni filial xodimiga ko‘rsating.",parse_mode="HTML")
        finally:
            await bot.session.close()
    return {"ok":True,"pickup_code":code}



# ---------------- v8: remaining customer/admin workflows ----------------
from fastapi import Request
from sqlalchemy import and_
from datetime import datetime, timezone
from aiogram import Bot
from app.config import BOT_TOKEN

async def notify_admins(text: str):
    """Send operational notifications to all active admins with the bot."""
    if not BOT_TOKEN:
        return
    from aiogram import Bot
    async with Session() as session:
        admins = (await session.scalars(select(Admin.tg_id))).all()
    if not admins:
        return
    bot = Bot(BOT_TOKEN)
    try:
        for admin_id in admins:
            try:
                await bot.send_message(admin_id, text[:3900], parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                # A blocked bot / unreachable admin must not roll back a customer action.
                continue
    finally:
        await bot.session.close()



class VariantIn(BaseModel):
    color: str = ""
    size: str = ""
    stock: int = Field(ge=0)
class ShipmentIn(BaseModel):
    carrier: str = "BTS"
    tracking_code: str = ""
    status: str = "BTS ga topshirildi"
    estimated_date: str = ""
    delivery_price: int = Field(default=0, ge=0)
    pickup_code: str = ""
class SupportIn(BaseModel):
    message: str = Field(min_length=1, max_length=3000)
    order_id: int | None = None
class MediaIn(BaseModel):
    media_type: str = "image"
    url: str
class BranchFullIn(BaseModel):
    title: str
    address: str
    city: str
    latitude: float = 0
    longitude: float = 0
    work_hours: str = ""
    phone: str = ""
    branch_code: str = ""
    landmark: str = ""
    map_url: str = ""
    video_url: str = ""
    active: bool = True

async def audit(session, admin_id:int, action:str, target:str="", details:str=""):
    session.add(AuditLog(admin_tg_id=admin_id, action=action, target=target, details=details[:2000]))

async def require_role(init_data, allowed):
    u=await require_admin(init_data)
    async with Session() as s:
        a=await s.get(Admin,u["id"])
        if a.role not in allowed and a.role!="owner":
            raise HTTPException(403,"Bu amal uchun admin roli yetarli emas")
    return u

@app.get("/api/compare")
async def get_compare(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.execute(select(Product).join(Comparison,Comparison.product_id==Product.id)
             .where(Comparison.user_tg_id==u["id"],Product.active==True))).scalars().all()
        return [{"id":p.id,"title":p.title,"price":p.price,"old_price":p.old_price,
                 "category":p.category,"description":p.description,"stock":p.stock,"image_url":p.image_url} for p in rows]

@app.post("/api/compare/{product_id}")
async def toggle_compare(product_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        p=await s.get(Product,product_id)
        if not p or not p.active: raise HTTPException(404,"Mahsulot topilmadi")
        row=await s.scalar(select(Comparison).where(Comparison.user_tg_id==u["id"],Comparison.product_id==product_id))
        if row: await s.delete(row); added=False
        else:
            count=await s.scalar(select(func.count(Comparison.id)).where(Comparison.user_tg_id==u["id"]))
            if count>=4: raise HTTPException(409,"Taqqoslashga ko‘pi bilan 4 ta mahsulot qo‘shiladi")
            s.add(Comparison(user_tg_id=u["id"],product_id=product_id)); added=True
        await s.commit()
        return {"ok":True,"added":added}

@app.delete("/api/compare")
async def clear_compare(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        await s.execute(delete(Comparison).where(Comparison.user_tg_id==u["id"]))
        await s.commit()
    return {"ok":True}

@app.get("/api/products/{product_id}/media")
async def product_media(product_id:int):
    async with Session() as s:
        rows=(await s.scalars(select(ProductMedia).where(ProductMedia.product_id==product_id))).all()
        return [{"id":r.id,"type":r.media_type,"url":r.url} for r in rows]

@app.get("/api/products/{product_id}/variants")
async def product_variants(product_id:int):
    async with Session() as s:
        rows=(await s.scalars(select(ProductVariant).where(ProductVariant.product_id==product_id))).all()
        return [{"id":v.id,"color":v.color,"size":v.size,"stock":v.stock} for v in rows]

@app.post("/api/admin/products/{product_id}/variants")
async def upsert_variant(product_id:int,body:VariantIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        v=await s.scalar(select(ProductVariant).where(ProductVariant.product_id==product_id,
            ProductVariant.color==body.color,ProductVariant.size==body.size))
        if v: v.stock=body.stock
        else: s.add(ProductVariant(product_id=product_id,color=body.color,size=body.size,stock=body.stock))
        await audit(s,u["id"],"variant_upsert",str(product_id),f"{body.color}/{body.size}: {body.stock}")
        await s.commit()
    return {"ok":True}

@app.delete("/api/admin/products/{product_id}/variants/{variant_id}")
async def delete_variant(product_id:int,variant_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    async with Session() as s:
        v=await s.scalar(select(ProductVariant).where(ProductVariant.id==variant_id,ProductVariant.product_id==product_id))
        if not v: raise HTTPException(404,"Variant topilmadi")
        await s.delete(v); await audit(s,u["id"],"variant_delete",str(variant_id)); await s.commit()
    return {"ok":True}

@app.post("/api/admin/products/{product_id}/media")
async def add_product_media(product_id:int,body:MediaIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    if body.media_type not in ("image","video"): raise HTTPException(400,"media_type image yoki video bo‘lsin")
    if not body.url.startswith(("https://","http://")): raise HTTPException(400,"Media URL http(s) bo‘lishi kerak")
    async with Session() as s:
        if not await s.get(Product,product_id): raise HTTPException(404,"Mahsulot topilmadi")
        r=ProductMedia(product_id=product_id,media_type=body.media_type,url=body.url)
        s.add(r); await s.flush(); await audit(s,u["id"],"media_add",str(product_id),body.media_type)
        await s.commit(); return {"ok":True,"id":r.id}

@app.delete("/api/admin/products/{product_id}/media/{media_id}")
async def delete_product_media(product_id:int,media_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    async with Session() as s:
        r=await s.scalar(select(ProductMedia).where(ProductMedia.id==media_id,ProductMedia.product_id==product_id))
        if not r: raise HTTPException(404,"Media topilmadi")
        await s.delete(r); await audit(s,u["id"],"media_delete",str(media_id)); await s.commit()
    return {"ok":True}

@app.get("/api/shipments/{order_id}")
async def shipment_status(order_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        order=await s.scalar(select(Order).where(Order.id==order_id,Order.user_tg_id==u["id"]))
        if not order: raise HTTPException(404,"Buyurtma topilmadi")
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if not sh: return {"order_id":order_id,"carrier":"BTS","status":order.status,"tracking_code":"","estimated_date":"","delivery_price":order.delivery_price,"pickup_code":order.pickup_code if order.payment_status in ("To‘liq to‘landi","To‘liq tolandi") else ""}
        return {"order_id":order_id,"carrier":sh.carrier,"tracking_code":sh.tracking_code,
                "status":sh.status,"estimated_date":sh.estimated_date,"delivery_price":sh.delivery_price,
                "pickup_code":order.pickup_code if order.payment_status=="To‘liq to‘landi" else ""}

@app.put("/api/admin/orders/{order_id}/shipment")
async def update_shipment(order_id:int,body:ShipmentIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager","logistics"})
    allowed_statuses={"Qabul qilindi","Tayyorlanmoqda","BTS ga topshirildi","Yo‘lda","BTS filialiga yetib keldi","Mijozga topshirildi","Yetkazildi","Muammo yuz berdi","Bekor qilindi"}
    status=body.status.strip()
    if status not in allowed_statuses:
        raise HTTPException(400,"Noto‘g‘ri jo‘natma holati")
    if len(body.tracking_code)>100 or len(body.pickup_code)>50:
        raise HTTPException(400,"Tracking yoki olish kodi juda uzun")
    async with Session() as s:
        o=await s.get(Order,order_id)
        if not o: raise HTTPException(404,"Buyurtma topilmadi")
        sh=await s.scalar(select(Shipment).where(Shipment.order_id==order_id))
        if not sh:
            sh=Shipment(order_id=order_id)
            s.add(sh)
        sh.carrier=(body.carrier or "BTS")[:30]
        sh.tracking_code=body.tracking_code.strip()
        sh.status=status
        sh.estimated_date=body.estimated_date.strip()[:40]
        sh.delivery_price=body.delivery_price
        if body.pickup_code.strip():
            if o.payment_status not in ("To‘liq to‘landi","To‘liq tolandi"):
                raise HTTPException(409,"Olish kodi faqat to‘liq to‘lovdan keyin kiritiladi")
            sh.pickup_code=body.pickup_code.strip()
            o.pickup_code=body.pickup_code.strip()
        o.status=status
        await audit(s,u["id"],"manual_bts_tracking_update",str(order_id),f"{status}; carrier={sh.carrier}; tracking={sh.tracking_code}; ETA={sh.estimated_date}; pickup_code_set={bool(sh.pickup_code)}")
        await s.commit()
        user_id=o.user_tg_id
        payment_status=o.payment_status
        pickup_code=sh.pickup_code
        tracking=sh.tracking_code
        eta=sh.estimated_date
    if BOT_TOKEN:
        try:
            bot=Bot(BOT_TOKEN)
            text_msg=(f"📦 Buyurtma #{order_id} bo‘yicha BTS ma’lumoti yangilandi.\n"
                      f"Holat: {status}\n"
                      f"Tashuvchi: {body.carrier or 'BTS'}\n"
                      f"Tracking kodi: {tracking or 'Hali kiritilmagan'}\n"
                      f"Taxminiy yetib borish: {eta or 'Belgilanmagan'}")
            if pickup_code and payment_status in ("To‘liq to‘landi","To‘liq tolandi"):
                text_msg += f"\nIchki olish kodi: {pickup_code}\n(Eslatma: bu do‘kon kodi, BTS kodi emas.)"
            await bot.send_message(user_id,text_msg)
            await bot.session.close()
        except Exception:
            pass
    return {"ok":True,"order_id":order_id,"status":status}

@app.post("/api/support/messages")
async def send_support(body:SupportIn,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        if body.order_id:
            order=await s.scalar(select(Order).where(Order.id==body.order_id,Order.user_tg_id==u["id"]))
            if not order: raise HTTPException(404,"Buyurtma topilmadi")
        msg=SupportMessage(user_tg_id=u["id"],order_id=body.order_id,sender_role="user",message=body.message)
        s.add(msg); await s.commit()
    if BOT_TOKEN:
        try:
            bot=Bot(BOT_TOKEN)
            async with Session() as s:
                admins=(await s.scalars(select(Admin.tg_id))).all()
            for aid in admins:
                await bot.send_message(aid,f"🆘 Yangi murojaat\nMijoz: {u['id']}\nBuyurtma: {body.order_id or '—'}\n\n{body.message}")
            await bot.session.close()
        except Exception:
            pass
    return {"ok":True}

@app.get("/api/support/messages")
async def get_support_messages(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(SupportMessage).where(SupportMessage.user_tg_id==u["id"]).order_by(SupportMessage.id))).all()
        return [{"id":m.id,"order_id":m.order_id,"sender":m.sender_role,"message":m.message,"created_at":str(m.created_at)} for m in rows]

@app.post("/api/admin/support/{user_tg_id}")
async def admin_reply(user_tg_id:int,body:SupportIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        if not await s.scalar(select(User.id).where(User.tg_id==user_tg_id)): raise HTTPException(404,"Mijoz topilmadi")
        s.add(SupportMessage(user_tg_id=user_tg_id,order_id=body.order_id,sender_role="admin",message=body.message))
        await audit(s,u["id"],"support_reply",str(user_tg_id))
        await s.commit()
    if BOT_TOKEN:
        try:
            bot=Bot(BOT_TOKEN); await bot.send_message(user_tg_id,"💬 Admin javobi:\n"+body.message); await bot.session.close()
        except Exception: pass
    return {"ok":True}

@app.get("/api/admin/support")
async def admin_support(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(SupportMessage).order_by(SupportMessage.id.desc()).limit(300))).all()
        return [{"id":m.id,"user_tg_id":m.user_tg_id,"order_id":m.order_id,"sender":m.sender_role,"message":m.message,"created_at":str(m.created_at)} for m in rows]

@app.post("/api/referral/apply/{inviter_tg_id}")
async def apply_referral(inviter_tg_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    if inviter_tg_id==u["id"]: raise HTTPException(400,"O‘zingizni taklif qila olmaysiz")
    async with Session() as s:
        if not await s.scalar(select(User.id).where(User.tg_id==inviter_tg_id)): raise HTTPException(404,"Taklif qiluvchi topilmadi")
        if await s.scalar(select(Referral.id).where(Referral.invited_tg_id==u["id"])): raise HTTPException(409,"Referral avval qo‘llangan")
        s.add(Referral(inviter_tg_id=inviter_tg_id,invited_tg_id=u["id"]))
        await s.commit()
    return {"ok":True}

@app.get("/api/referral")
async def referral_info(x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Referral).where(Referral.inviter_tg_id==u["id"]))).all()
        return {"invited_count":len(rows),"bonus_paid_count":sum(1 for r in rows if r.bonus_paid)}

@app.post("/api/admin/orders/{order_id}/delivered")
async def mark_delivered(order_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        o=await s.get(Order,order_id)
        if not o: raise HTTPException(404,"Buyurtma topilmadi")
        if o.payment_status!="To‘liq to‘landi": raise HTTPException(409,"To‘liq to‘lovsiz buyurtma yakunlanmaydi")
        o.status="Yetkazildi"
        note=f"Cashback order #{order_id}"
        exists=await s.scalar(select(WalletLedger.id).where(WalletLedger.kind=="cashback",WalletLedger.note==note))
        if not exists:
            rate_row=await s.get(Setting,"cashback_percent")
            rate=max(0,min(50,int(rate_row.value))) if rate_row and rate_row.value.isdigit() else 0
            bonus=o.total*rate//100
            customer=await s.scalar(select(User).where(User.tg_id==o.user_tg_id))
            if bonus and customer:
                customer.bonus_balance+=bonus
                s.add(WalletLedger(user_tg_id=customer.tg_id,amount=bonus,kind="cashback",note=note))
        refs=(await s.scalars(select(Referral).where(Referral.invited_tg_id==o.user_tg_id,Referral.bonus_paid==False))).all()
        for ref in refs:
            inviter=await s.scalar(select(User).where(User.tg_id==ref.inviter_tg_id))
            if inviter:
                reward_row=await s.get(Setting,"referral_bonus")
                reward=int(reward_row.value) if reward_row and reward_row.value.isdigit() else 0
                if reward:
                    inviter.bonus_balance+=reward
                    s.add(WalletLedger(user_tg_id=inviter.tg_id,amount=reward,kind="referral",note=f"Referral order #{order_id}"))
                ref.bonus_paid=True
        await audit(s,u["id"],"order_delivered",str(order_id))
        await s.commit()
    return {"ok":True,"cashback_and_referral_processed":True}

@app.get("/api/admin/branches/full")
async def admin_branches_full(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(Branch).order_by(Branch.city,Branch.title))).all()
        return [{"id":b.id,"title":b.title,"address":b.address,"city":b.city,"latitude":b.latitude,
                 "longitude":b.longitude,"work_hours":b.work_hours,"phone":b.phone,"active":b.active} for b in rows]

@app.post("/api/admin/branches/full")
async def create_branch_full(body:BranchFullIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        b=Branch(**body.model_dump()); s.add(b); await s.flush()
        await audit(s,u["id"],"branch_create",str(b.id),b.title); await s.commit()
        return {"ok":True,"id":b.id}

@app.get("/api/admin/audit")
async def get_audit(limit:int=100,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner"})
    async with Session() as s:
        rows=(await s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit,1),500)))).all()
        return [{"admin":r.admin_tg_id,"action":r.action,"target":r.target,"details":r.details,"created_at":str(r.created_at)} for r in rows]

@app.get("/api/admin/products/export.csv")
async def export_products(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(Product).order_by(Product.id))).all()
        out=io.StringIO(); w=csv.writer(out)
        w.writerow(["id","title","description","price","old_price","category","stock","image_url","active"])
        for p in rows: w.writerow([p.id,p.title,p.description,p.price,p.old_price,p.category,p.stock,p.image_url,p.active])
        return StreamingResponse(iter([out.getvalue()]),media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":"attachment; filename=onlinexarid_products.csv"})

@app.post("/api/admin/products/import.csv")
async def import_products_csv(request:Request,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","catalog","manager"})
    raw=(await request.body()).decode("utf-8-sig")
    if len(raw)>2_000_000: raise HTTPException(413,"CSV fayl 2 MB dan kichik bo‘lsin")
    reader=csv.DictReader(io.StringIO(raw))
    required={"title","price","stock"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)): raise HTTPException(400,"CSV ustunlari: title, price, stock bo‘lishi shart")
    count=0
    async with Session() as s:
        for row in reader:
            try:
                p=Product(title=row["title"][:200],description=row.get("description",""),
                    price=max(0,int(row["price"])),old_price=max(0,int(row.get("old_price") or 0)),
                    category=row.get("category") or "Boshqa",stock=max(0,int(row["stock"])),
                    image_url=row.get("image_url",""),active=(row.get("active","true").lower() not in ("false","0","no")))
            except Exception: continue
            s.add(p); count+=1
        await audit(s,u["id"],"products_csv_import","",f"{count} ta mahsulot")
        await s.commit()
    return {"ok":True,"imported":count}

@app.get("/api/admin/wallet/ledger/{tg_id}")
async def wallet_ledger(tg_id:int,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","finance"})
    async with Session() as s:
        rows=(await s.scalars(select(WalletLedger).where(WalletLedger.user_tg_id==tg_id).order_by(WalletLedger.id.desc()).limit(200))).all()
        return [{"amount":r.amount,"kind":r.kind,"note":r.note,"created_at":str(r.created_at)} for r in rows]

@app.get("/api/admin/promos")
async def list_promos(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager","catalog"})
    async with Session() as s:
        rows=(await s.scalars(select(PromoCode).order_by(PromoCode.id.desc()))).all()
        return [{"id":p.id,"code":p.code,"discount_percent":p.discount_percent,"discount_amount":p.discount_amount,
                 "active":p.active,"usage_limit":p.usage_limit,"used_count":p.used_count,"expires_at":str(p.expires_at or "")} for p in rows]


CITY_ALIASES = {
    "nukus":"Nukus","nukus shahri":"Nukus","urganch":"Urganch","urgench":"Urganch",
    "buxoro":"Buxoro","bukhara":"Buxoro","navoiy":"Navoiy","navoi":"Navoiy",
    "samarqand":"Samarqand","samarkand":"Samarqand","qarshi":"Qarshi","karshi":"Qarshi",
    "termiz":"Termiz","termez":"Termiz","jizzax":"Jizzax","jizzakh":"Jizzax",
    "guliston":"Guliston","toshkent":"Toshkent","tashkent":"Toshkent",
    "qo'qon":"Qo‘qon","qoqon":"Qo‘qon","kokand":"Qo‘qon",
    "namangan":"Namangan","farg'ona":"Farg‘ona","fargona":"Farg‘ona","fergana":"Farg‘ona",
}
def canonical_city(value:str)->str:
    key=(value or "").strip().lower().replace("ʻ","'").replace("’","'").replace("‘","'").replace("`","'")
    return CITY_ALIASES.get(key,key.title())

@app.post("/api/admin/bts/tariffs/import.csv")
async def import_bts_tariffs(request:Request,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner"})
    raw=(await request.body()).decode("utf-8-sig")
    if len(raw)>2_000_000: raise HTTPException(413,"CSV 2 MB dan kichik bo‘lsin")
    reader=csv.DictReader(io.StringIO(raw))
    required={"origin_city","destination_city","kg_min","kg_max","price","delivery_days","tariff_type","zone"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(400,"CSV BTS 2026 formatida bo‘lishi kerak")
    parsed=[]
    for r in reader:
        try:
            origin=canonical_city(r["origin_city"]); dest=canonical_city(r["destination_city"])
            lo,hi,price,days,zone=map(int,(r["kg_min"],r["kg_max"],r["price"],r["delivery_days"],r["zone"]))
            typ=r["tariff_type"].strip()
            if not origin or not dest or typ not in {"office_to_office","office_to_tashkent_mvo"}: continue
            if lo<1 or hi<lo or hi>20 or price<0 or days<1 or zone not in range(6): continue
            parsed.append(BTSTariff(origin_city=origin,destination_city=dest,kg_min=lo,kg_max=hi,
                price=price,delivery_days=days,tariff_type=typ,zone=zone,
                effective_from=r.get("effective_from","2026-09-01"),vat_included=(r.get("vat_included","true").lower()=="true")))
        except Exception: continue
    if not parsed: raise HTTPException(400,"Yaroqli BTS tarif qatori topilmadi")
    async with Session() as s:
        await s.execute(delete(BTSTariff))
        s.add_all(parsed); await audit(s,u["id"],"bts_tariffs_import","",f"{len(parsed)} tarif")
        await s.commit()
    return {"ok":True,"imported":len(parsed),"effective_from":"2026-09-01","vat_included":True}

@app.get("/api/admin/bts/tariffs/template.csv")
async def bts_tariff_template(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner"})
    out=io.StringIO(); w=csv.writer(out)
    w.writerow(["origin_city","destination_city","kg_min","kg_max","price","delivery_days","tariff_type","zone","effective_from","vat_included"])
    return StreamingResponse(iter([out.getvalue()]),media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":"attachment; filename=bts_tariffs_template.csv"})

@app.get("/api/branches/map")
async def branches_map(x_telegram_init_data:str=Header(default="")):
    await require_user(x_telegram_init_data)
    async with Session() as s:
        rows=(await s.scalars(select(Branch).where(Branch.active==True,Branch.latitude!=0,Branch.longitude!=0))).all()
        return [{"id":b.id,"name":b.title,"address":b.address,"city":b.city,
                 "lat":b.latitude,"lon":b.longitude,"hours":b.work_hours,"phone":b.phone,"branch_code":b.branch_code,"landmark":b.landmark,"map_url":b.map_url,"video_url":b.video_url} for b in rows]

@app.post("/api/admin/branches/import.csv")
async def import_branches_csv(request:Request,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    raw=(await request.body()).decode("utf-8-sig")
    if len(raw)>2_000_000: raise HTTPException(413,"CSV fayl 2 MB dan kichik bo‘lsin")
    reader=csv.DictReader(io.StringIO(raw))
    required={"title","address","city"}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(400,"CSV ustunlari: title,address,city,latitude,longitude,work_hours,phone")
    count=0
    async with Session() as s:
        for r in reader:
            try:
                b=Branch(title=r["title"][:200],address=r["address"][:300],city=r["city"][:100],
                    latitude=float(r.get("latitude") or 0),longitude=float(r.get("longitude") or 0),
                    work_hours=r.get("work_hours","")[:120],phone=r.get("phone","")[:40],
                    branch_code=r.get("branch_code","")[:30],landmark=r.get("landmark","")[:250],map_url=r.get("map_url","")[:500],video_url=r.get("video_url","")[:500])
                if not (-90<=b.latitude<=90 and -180<=b.longitude<=180): continue
                s.add(b); count+=1
            except Exception: continue
        await audit(s,u["id"],"branches_csv_import","",f"{count} ta filial")
        await s.commit()
    return {"ok":True,"imported":count}

@app.get("/api/admin/branches/export.csv")
async def export_branches_csv(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(Branch).order_by(Branch.city,Branch.title))).all()
        out=io.StringIO(); w=csv.writer(out)
        w.writerow(["branch_code","title","city","address","landmark","work_hours","phone","latitude","longitude","map_url","video_url","active"])
        for b in rows: w.writerow([b.branch_code,b.title,b.city,b.address,b.landmark,b.work_hours,b.phone,b.latitude,b.longitude,b.map_url,b.video_url,b.active])
        return StreamingResponse(iter([out.getvalue()]),media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition":"attachment; filename=onlinexarid_branches.csv"})


class RewardSettingsIn(BaseModel):
    cashback_percent:int=Field(default=0,ge=0,le=50)
    referral_bonus:int=Field(default=0,ge=0)

@app.put("/api/admin/rewards/settings")
async def update_reward_settings(body:RewardSettingsIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner"})
    async with Session() as s:
        for key,value in (("cashback_percent",body.cashback_percent),("referral_bonus",body.referral_bonus)):
            row=await s.get(Setting,key)
            if row: row.value=str(value)
            else: s.add(Setting(key=key,value=str(value)))
        await audit(s,u["id"],"reward_settings","",f"cashback={body.cashback_percent}; referral={body.referral_bonus}")
        await s.commit()
    return {"ok":True}


# ---- v13: reservation expiry, refunds, review moderation, scheduled channel posts ----

class RefundIn(BaseModel):
    order_id:int
    amount:int=Field(gt=0)
    method:str="wallet"
    reason:str=""

class RefundDecisionIn(BaseModel):
    decision:str
    note:str=""

class ReviewDecisionIn(BaseModel):
    decision:str
    note:str=""

class ChannelPostIn(BaseModel):
    channel_id:str
    message:str=Field(min_length=1,max_length=4000)
    scheduled_at:datetime

@app.post("/api/refunds")
async def request_refund(body:RefundIn,x_telegram_init_data:str=Header(default="")):
    u=await require_user(x_telegram_init_data)
    if body.method not in ("wallet","manual_card"): raise HTTPException(400,"Refund usuli noto‘g‘ri")
    async with Session() as s:
        order=await s.get(Order,body.order_id)
        if not order or order.user_tg_id!=u["id"]: raise HTTPException(404,"Buyurtma topilmadi")
        if order.status in ("BTS ga topshirildi","Yo‘lda","BTS filialiga yetib keldi","Yetkazildi","Mijozga topshirildi"):
            raise HTTPException(409,"Jo‘natilgan buyurtma uchun refund admin tekshiruvi orqali amalga oshiriladi")
        if body.amount>order.total: raise HTTPException(400,"Refund summasi buyurtma qiymatidan oshmasin")
        existing=await s.scalar(select(RefundRequest).where(RefundRequest.order_id==order.id,RefundRequest.status.in_(["pending","approved","processing"])))
        if existing: raise HTTPException(409,"Bu buyurtma uchun refund so‘rovi allaqachon mavjud")
        rr=RefundRequest(order_id=order.id,user_tg_id=u["id"],amount=body.amount,method=body.method,reason=body.reason[:1000])
        s.add(rr); await s.commit()
        return {"ok":True,"refund_id":rr.id,"status":rr.status}

@app.get("/api/admin/refunds")
async def admin_refunds(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","finance"})
    async with Session() as s:
        rows=(await s.scalars(select(RefundRequest).order_by(RefundRequest.id.desc()).limit(300))).all()
        return [{"id":r.id,"order_id":r.order_id,"user_tg_id":r.user_tg_id,"amount":r.amount,"method":r.method,"status":r.status,"reason":r.reason,"admin_note":r.admin_note} for r in rows]

@app.post("/api/admin/refunds/{refund_id}/decision")
async def decide_refund(refund_id:int,body:RefundDecisionIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","finance"})
    if body.decision not in ("approve","reject","complete"): raise HTTPException(400,"Noto‘g‘ri qaror")
    async with Session() as s:
        r=await s.get(RefundRequest,refund_id)
        if not r: raise HTTPException(404,"Refund topilmadi")
        if r.status in ("completed","rejected"): raise HTTPException(409,"Refund allaqachon yakunlangan")
        order=await s.get(Order,r.order_id)
        if body.decision=="reject":
            r.status="rejected"; r.admin_note=body.note[:1000]
        elif body.decision=="approve":
            r.status="approved"; r.admin_note=body.note[:1000]
        else:
            if r.status not in ("approved","processing"): raise HTTPException(409,"Avval refundni tasdiqlang")
            if r.method=="wallet":
                user=await s.scalar(select(User).where(User.tg_id==r.user_tg_id))
                if not user: raise HTTPException(404,"Mijoz topilmadi")
                # idempotence guarded by status transition
                user.cash_balance+=r.amount
                s.add(WalletLedger(user_tg_id=r.user_tg_id,amount=r.amount,kind="refund",note=f"Refund #{r.id}, buyurtma #{r.order_id}"))
            else:
                r.status="processing"
                r.admin_note=(body.note+" | Kartaga qaytarish provayder orqali qo‘lda bajarilishi kerak")[:1000]
                await s.commit()
                return {"ok":True,"status":r.status,"note":"Karta refundi avtomatik bajarilmadi; provayder orqali qaytarib, keyin complete yuboring."}
            r.status="completed"; r.processed_at=datetime.now(timezone.utc); r.admin_note=body.note[:1000]
            if order: order.status="Refund qaytarildi"
        await audit(s,u["id"],"refund_"+body.decision,str(refund_id),body.note[:500])
        await s.commit()
        # Send the admin's note to the customer through the shop bot.
        customer_message = {
            "approve": "Qaytarish so‘rovingiz tasdiqlandi.",
            "reject": "Qaytarish so‘rovingiz rad etildi.",
            "complete": "Qaytarish jarayoni yakunlandi."
        }[body.decision]
        if body.note.strip():
            customer_message += "\n\nAdmin izohi: " + body.note.strip()[:900]
        if r.method == "manual_card" and r.status == "processing":
            customer_message = "Kartaga pul qaytarish jarayoni boshlandi."
            if body.note.strip(): customer_message += "\n\nAdmin izohi: " + body.note.strip()[:900]
        try:
            bot = Bot(token=BOT_TOKEN)
            await bot.send_message(r.user_tg_id, customer_message)
            await bot.session.close()
        except Exception as exc:
            print("Refund customer notification failed:", repr(exc))
        return {"ok":True,"status":r.status}

@app.get("/api/admin/reviews")
async def admin_reviews(status:str="pending",x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(Review).where(Review.moderation_status==status).order_by(Review.id.desc()).limit(300))).all()
        return [{"id":r.id,"product_id":r.product_id,"user_tg_id":r.user_tg_id,"rating":r.rating,"comment":r.comment,"status":r.moderation_status} for r in rows]

@app.post("/api/admin/reviews/{review_id}/decision")
async def decide_review(review_id:int,body:ReviewDecisionIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    if body.decision not in ("approve","reject"): raise HTTPException(400,"Noto‘g‘ri qaror")
    async with Session() as s:
        r=await s.get(Review,review_id)
        if not r: raise HTTPException(404,"Sharh topilmadi")
        r.moderation_status="approved" if body.decision=="approve" else "rejected"
        r.moderation_note=body.note[:1000]
        await audit(s,u["id"],"review_"+body.decision,str(review_id),body.note[:300])
        await s.commit()
        return {"ok":True,"status":r.moderation_status}

@app.post("/api/admin/channel-posts")
async def schedule_channel_post(body:ChannelPostIn,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    if body.scheduled_at.tzinfo is None: raise HTTPException(400,"Vaqt timezone bilan yuborilishi kerak")
    if body.scheduled_at <= datetime.now(timezone.utc): raise HTTPException(400,"Post vaqti kelajakda bo‘lishi kerak")
    async with Session() as s:
        p=ScheduledChannelPost(channel_id=body.channel_id[:120],message=body.message,
            scheduled_at=body.scheduled_at,created_by=u["id"])
        s.add(p); await s.commit()
        return {"ok":True,"post_id":p.id}

@app.get("/api/admin/channel-posts")
async def list_channel_posts(x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        rows=(await s.scalars(select(ScheduledChannelPost).order_by(ScheduledChannelPost.scheduled_at.desc()).limit(300))).all()
        return [{"id":p.id,"channel_id":p.channel_id,"message":p.message,"scheduled_at":p.scheduled_at.isoformat(),"status":p.status,"error":p.error} for p in rows]

@app.delete("/api/admin/channel-posts/{post_id}")
async def cancel_channel_post(post_id:int,x_telegram_init_data:str=Header(default="")):
    await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        p=await s.get(ScheduledChannelPost,post_id)
        if not p: raise HTTPException(404,"Post topilmadi")
        if p.status!="pending": raise HTTPException(409,"Faqat kutilayotgan post bekor qilinadi")
        p.status="cancelled"; await s.commit()
        return {"ok":True}

@app.post("/api/admin/orders/{order_id}/cancel")
async def cancel_order(order_id:int,x_telegram_init_data:str=Header(default="")):
    u=await require_role(x_telegram_init_data,{"owner","manager"})
    async with Session() as s:
        o=await s.get(Order,order_id)
        if not o: raise HTTPException(404,"Buyurtma topilmadi")
        if o.status in ("BTS ga topshirildi","Yo‘lda","BTS filialiga yetib keldi","Yetkazildi"):
            raise HTTPException(409,"Jo‘natilgan buyurtmani oddiy bekor qilib bo‘lmaydi; refund so‘rovi yarating")
        if o.status=="Bekor qilindi": return {"ok":True,"status":o.status}
        o.status="Bekor qilindi"
        reservations=(await s.scalars(select(InventoryReservation).where(
            InventoryReservation.order_id==order_id,InventoryReservation.status.in_(["held","committed"])))).all()
        for rv in reservations:
            product=await s.get(Product,rv.product_id)
            if product: product.stock += rv.quantity
            if rv.variant_id:
                variant=await s.get(ProductVariant,rv.variant_id)
                if variant: variant.stock += rv.quantity
            rv.status="released"
        # Return any wallet/cashback debits only when they were actually debited.
        pays=(await s.scalars(select(Payment).where(Payment.order_id==order_id))).all()
        paid=any(p.status=="Tasdiqlandi" for p in pays)
        if paid:
            user=await s.scalar(select(User).where(User.tg_id==o.user_tg_id))
            if user:
                if o.wallet_used:
                    user.cash_balance+=o.wallet_used
                    s.add(WalletLedger(user_tg_id=user.tg_id,amount=o.wallet_used,kind="cancel_return",note=f"Buyurtma #{o.id}"))
                if o.cashback_used:
                    user.bonus_balance+=o.cashback_used
                    s.add(WalletLedger(user_tg_id=user.tg_id,amount=o.cashback_used,kind="cancel_return",note=f"Cashback buyurtma #{o.id}"))
        await audit(s,u["id"],"order_cancel",str(order_id))
        await s.commit()
        return {"ok":True,"status":o.status}

async def maintenance_worker():
    # Scheduled channel posts require BOT_TOKEN and a bot with permission to post in the channel.
    from aiogram import Bot
    while True:
        try:
            now=datetime.now(timezone.utc)
            async with Session() as s:
                expired=(await s.scalars(select(Order).where(
                    Order.payment_status=="Birinchi to'lov kutilmoqda",
                    Order.created_at < now-timedelta(minutes=5),
                    Order.status!="Bekor qilindi"))).all()
                for o in expired:
                    o.status="Bekor qilindi"; o.payment_status="To‘lov muddati tugadi"
                    for p in (await s.scalars(select(Payment).where(Payment.order_id==o.id,Payment.status=="Kutilmoqda"))).all():
                        p.status="Muddati tugadi"
                    # Remove only pending, uncommitted reservation rows if present.
                    for rv in (await s.scalars(select(InventoryReservation).where(InventoryReservation.order_id==o.id,InventoryReservation.status=="held"))).all():
                        product=await s.get(Product,rv.product_id)
                        if product: product.stock += rv.quantity
                        if rv.variant_id:
                            variant=await s.get(ProductVariant,rv.variant_id)
                            if variant: variant.stock += rv.quantity
                        rv.status="released"
                due=(await s.scalars(select(ScheduledChannelPost).where(ScheduledChannelPost.status=="pending",ScheduledChannelPost.scheduled_at<=now).limit(20))).all()
                due_ids=[p.id for p in due]
                await s.commit()
            if due_ids and BOT_TOKEN:
                bot=Bot(BOT_TOKEN)
                for pid in due_ids:
                    async with Session() as s:
                        p=await s.get(ScheduledChannelPost,pid)
                        if not p or p.status!="pending": continue
                        try:
                            await bot.send_message(p.channel_id,p.message)
                            p.status="sent"; p.error=""
                        except Exception as e:
                            p.status="failed"; p.error=str(e)[:1000]
                        await s.commit()
                await bot.session.close()
        except Exception as e:
            print("Maintenance worker error:",e)
        await asyncio.sleep(30)



@app.get("/api/admin/channel-settings")
async def get_channel_settings(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    async with Session() as s:
        vals={}
        for key in ("product_channel_id","product_post_template"):
            row=await s.get(Setting,key); vals[key]=row.value if row else ""
        return vals

@app.put("/api/admin/channel-settings")
async def set_channel_settings(body:dict,x_telegram_init_data:str=Header(default="")):
    u=await require_admin(x_telegram_init_data)
    channel=str(body.get("product_channel_id","")).strip()
    template=str(body.get("product_post_template","")).strip()
    if channel and not (channel.startswith("@") or channel.startswith("-100")):
        raise HTTPException(400,"Kanal username @ bilan yoki -100... ID bo‘lishi kerak")
    async with Session() as s:
        for key,value in (("product_channel_id",channel),("product_post_template",template)):
            row=await s.get(Setting,key)
            if row: row.value=value
            else: s.add(Setting(key=key,value=value))
        await audit(s,u["id"],"channel_settings","",channel)
        await s.commit()
    return {"ok":True}

@app.post("/api/admin/channel-test")
async def test_channel(x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    from aiogram import Bot
    async with Session() as s:
        row=await s.get(Setting,"product_channel_id")
        channel=row.value.strip() if row else ""
    if not channel:
        raise HTTPException(400,"Avval kanal username yoki ID sini saqlang")
    if not BOT_TOKEN:
        raise HTTPException(503,"BOT_TOKEN sozlanmagan")
    bot=Bot(BOT_TOKEN)
    try:
        chat=await bot.get_chat(channel)
        me=await bot.get_me()
        member=await bot.get_chat_member(chat.id,me.id)
        if member.status not in ("administrator","creator"):
            raise HTTPException(403,"Bot kanal administratori emas. Botga admin huquqini bering.")
        await bot.send_message(chat.id,"✅ OnlineXarid: kanal ulanishi muvaffaqiyatli tekshirildi.")
        return {"ok":True,"title":getattr(chat,"title",channel),"message":"Bot kanalga xabar yubora oladi."}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400,"Kanalga ulanish xatosi: "+str(exc)[:250])
    finally:
        await bot.session.close()

@app.get("/admin")
async def admin_page():
    return FileResponse(os.path.join(WEB_DIR,"admin.html"))


@app.post("/api/admin/products/{product_id}/publish")
async def publish_product_endpoint(product_id:int,x_telegram_init_data:str=Header(default="")):
    await require_admin(x_telegram_init_data)
    posted=await publish_product_to_channel(product_id)
    if not posted:
        raise HTTPException(503,"Kanalga yuborilmadi. Bot tokeni, kanal ID va bot admin huquqini tekshiring.")
    return {"ok":True,"channel_posted":True}
