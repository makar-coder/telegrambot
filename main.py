import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("✅ Бот работает!")

@dp.message()
async def relay_handler(message: types.Message):
    await bot.send_message(
        ADMIN_ID,
        f"📩 От: {message.from_user.full_name} (@{message.from_user.username})\n\n{message.text}"
    )
    await message.answer("✅ Сообщение получено")

async def handle_webhook(request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
    return web.Response(text="OK")

async def on_startup():
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        print(f"✅ Вебхук установлен: {WEBHOOK_URL}")

def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/", lambda request: web.Response(text="I'm alive"))

    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Запуск на порту {port}...")

    # Установка вебхука в том же цикле событий
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(on_startup())

    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
