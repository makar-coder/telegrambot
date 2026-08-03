import asyncio
import os
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID должны быть в .env файле")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

business_connections = {}

@dp.message(F.business_connection_id)
async def business_message_handler(message: Message):
    connection_id = message.business_connection_id
    chat_id = message.chat.id
    text = message.text or "❌ Нет текста"
    user = message.from_user

    business_connections[chat_id] = connection_id

    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"📩 Новое сообщение в чате {chat_id}\n\nОт: {user.full_name} (@{user.username or 'без юзера'})\n\n{text}"
        )
    except Exception as e:
        print(f"Ошибка при отправке админу: {e}")

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "👋 Бот активен.\n\n"
        "1. Подключи его через Настройки → Бизнес-боты в Telegram.\n"
        "2. Все сообщения будут приходить в админ-чат.\n"
        "3. Для отладки смотри логи."
    )

@dp.message()
async def fallback_handler(message: Message):
    await message.answer("Этот бот работает только как бизнес-бот. Подключи его в настройках.")

async def main():
    print("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
