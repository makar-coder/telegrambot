import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("✅ Бот-ретранслятор работает. Все сообщения передаются админу.")

@dp.message()
async def relay_handler(message: Message):
    user = message.from_user
    text = message.text or "❌ Нет текста"

    # 1. Отправляем копию админу
    await bot.send_message(
        ADMIN_ID,
        f"📩 От: {user.full_name} (@{user.username or 'без юзера'})\n\n{text}"
    )

    # 2. Отвечаем отправителю (шаблон)
    await message.answer("✅ Сообщение получено и передано админу.")

async def on_startup():
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        print(f"✅ Вебхук установлен: {WEBHOOK_URL}")

def main():
    app = web.Application()
    app.router.post("/webhook", dp._webhook_handler)
    app.router.get("/", lambda request: web.Response(text="✅ Бот работает!"))
    
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Запуск на порту {port}...")
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
