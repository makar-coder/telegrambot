import os
import asyncio
from aiogram import Bot, Dispatcher
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
    await message.answer("✅ Бот работает на вебхуке!")

@dp.message()
async def relay_handler(message: Message):
    await bot.send_message(
        ADMIN_ID,
        f"📩 От: {message.from_user.full_name} (@{message.from_user.username or 'без юзера'})\n\n{message.text or '❌ Нет текста'}"
    )
    await message.answer("✅ Сообщение получено и передано админу.")

async def handle_webhook(request):
    update = await request.json()
    await dp.process_update(update)
    return web.Response(text="OK")

async def on_startup():
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        print(f"✅ Вебхук установлен: {WEBHOOK_URL}")

def main():
    app = web.Application()
    app.router.add_route("POST", "/webhook", handle_webhook)
    app.router.add_route("GET", "/", lambda request: web.Response(text="✅ OK"))

    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Запуск на порту {port}...")

    asyncio.run(on_startup())
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
