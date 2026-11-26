
import asyncio, logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, ReplyKeyboardRemove
from sqlalchemy import select
from app.config import BOT_TOKEN, WEBAPP_URL, STORE_NAME
from app.db import init_db, Session, User, Admin

logging.basicConfig(level=logging.INFO)
dp=Dispatcher()

async def shop_keyboard(user_id:int):
    rows=[[InlineKeyboardButton(text="🛍 Xarid qilish",web_app=WebAppInfo(url=WEBAPP_URL))]]
    async with Session() as s:
        if await s.get(Admin,user_id):
            admin_url=WEBAPP_URL.rstrip("/")+"/admin"
            rows.append([InlineKeyboardButton(text="⚙️ Admin panel",web_app=WebAppInfo(url=admin_url))])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def welcome(message):
    await message.answer(
        f"🛍 <b>{STORE_NAME}</b> — onlayn do‘konimizga xush kelibsiz!\n\n"
        "Assalomu alaykum! 👋\n\n"
        "✨ Zamonaviy va sifatli kiyimlar\n"
        "🛒 Qulay onlayn xarid\n"
        "🚚 Pochta filialiga yetkazib berish\n"
        "💳 Bank kartasi orqali xavfsiz to‘lov\n\n"
        "Katalogimizni ko‘rish va xaridni boshlash uchun quyidagi tugmani bosing!\n\n"
        "<b>OnlineXarid — uslubingiz, tanlovingiz! ❤️</b>",
        reply_markup=await shop_keyboard(message.from_user.id),parse_mode="HTML")

@dp.message(CommandStart())
async def start(message:Message):
    async with Session() as s:
        user=await s.scalar(select(User).where(User.tg_id==message.from_user.id))
    if user and user.phone:
        await welcome(message)
        return
    kb=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish",request_contact=True)]],resize_keyboard=True,one_time_keyboard=True)
    await message.answer(f"🛍 <b>{STORE_NAME}</b> do‘koniga xush kelibsiz!\n\nDavom etish uchun o‘z telefon raqamingizni yuboring.",reply_markup=kb,parse_mode="HTML")

@dp.message(F.contact)
async def contact(message:Message):
    if not message.from_user or not message.contact or message.contact.user_id!=message.from_user.id:
        await message.answer("Iltimos, faqat o‘zingizning telefon raqamingizni tugma orqali yuboring.")
        return
    async with Session() as s:
        u=await s.scalar(select(User).where(User.tg_id==message.from_user.id))
        if not u: u=User(tg_id=message.from_user.id);s.add(u)
        u.username=message.from_user.username or "";u.full_name=message.from_user.full_name;u.phone=message.contact.phone_number
        await s.commit()
    # Contact and registration messages are left in chat; Telegram bot privacy rules
    # do not guarantee deletion of user-authored messages in private chats.
    await message.answer(
        f"🛍 <b>{STORE_NAME}</b> — onlayn do‘konimizga xush kelibsiz!\n\n"
        "Assalomu alaykum! 👋\n\n"
        "✨ Zamonaviy va sifatli kiyimlar\n"
        "🛒 Qulay onlayn xarid\n"
        "🚚 Pochta filialiga yetkazib berish\n"
        "💳 Bank kartasi orqali xavfsiz to‘lov\n\n"
        "Katalogimizni ko‘rish va xaridni boshlash uchun quyidagi tugmani bosing!\n\n"
        "<b>OnlineXarid — uslubingiz, tanlovingiz! ❤️</b>",
        reply_markup=await shop_keyboard(message.from_user.id), parse_mode="HTML"
    )

async def main():
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN .env faylida kiritilmagan")
    if not WEBAPP_URL.startswith("https://") or "your-domain.example" in WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL uchun haqiqiy HTTPS hosting manzilini .env fayliga kiriting")
    await init_db()
    bot=Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__=="__main__": asyncio.run(main())
