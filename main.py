import asyncio
import os
import json
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update, Message
from aiogram.filters import Command
from aiogram.webhook.aiohttp_server import SimpleWebhookApp, setup_application
from dotenv import load_dotenv
from aiohttp import web

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # Бесплатный ключ с https://platform.deepseek.com/
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Например: https://твой-проект.railway.app/webhook

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Храним последние сообщения для контекста
user_context = {}

async def get_deepseek_response(prompt: str) -> str:
    """Запрос к DeepSeek API (бесплатно)"""
    if not DEEPSEEK_API_KEY:
        return "❌ API-ключ DeepSeek не задан. Напиши админу."

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты — умный ассистент. Отвечай кратко, чётко, по делу."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 500,
                    "temperature": 0.7
                }
            )
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠️ Ошибка DeepSeek: {str(e)}"

@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        "🧠 Нейро-помощник активирован.\n\n"
        "1. Подключи бота как бизнес-бот в настройках Telegram.\n"
        "2. Все сообщения будут дублироваться админу.\n"
        "3. На каждое сообщение приходит ответ от DeepSeek.\n"
        "4. Если хочешь отключить умные ответы — напиши админу."
    )

@dp.message()
async def handle_all_messages(message: Message):
    """Обрабатываем ВСЕ сообщения (включая бизнес-сообщения)"""
    user_id = message.from_user.id
    text = message.text or "❌ Нет текста"
    chat_id = message.chat.id
    username = message.from_user.full_name
    is_business = bool(message.business_connection_id)

    # 1. Всегда отправляем копию админу
    await bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 [{'БИЗНЕС' if is_business else 'ОБЫЧНЫЙ'}] {username} (@{message.from_user.username or 'без юзера'}):\n\n{text}"
    )

    # 2. Если есть ключ DeepSeek — отвечаем умно
    if DEEPSEEK_API_KEY:
        # Отвечаем только если это не админ (чтобы не зациклиться)
        if user_id != ADMIN_ID:
            thinking_msg = await message.reply("🤔 Думаю...")
            try:
                # Добавляем контекст из истории
                context = user_context.get(user_id, [])
                context.append(f"Пользователь: {text}")
                if len(context) > 10:
                    context = context[-10:]  # Храним последние 10 сообщений

                full_prompt = "\n".join(context) + f"\n\nАссистент:"
                answer = await get_deepseek_response(full_prompt)

                # Сохраняем ответ в контекст
                context.append(f"Ассистент: {answer}")
                user_context[user_id] = context

                await thinking_msg.edit_text(f"🧠 {answer}")
            except Exception as e:
                await thinking_msg.edit_text(f"❌ Ошибка: {str(e)}")

    # 3. Если это бизнес-сообщение — отвечаем обязательно (чтобы бот не молчал)
    if is_business and user_id != ADMIN_ID:
        try:
            await message.answer(
                "✅ Сообщение получено и передано админу. Если нужно — я отвечу на него умно.",
                business_connection_id=message.business_connection_id
            )
        except:
            pass

async def on_startup():
    """При запуске — устанавливаем вебхук"""
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    print(f"✅ Вебхук установлен: {WEBHOOK_URL}")

def main():
    # Создаём приложение aiohttp
    app = web.Application()
    
    # Настраиваем вебхук
    webhook_app = SimpleWebhookApp(
        dispatcher=dp,
        bot=bot,
        webhook_path="/webhook",
        secret_token=os.getenv("WEBHOOK_SECRET", "default_secret")
    )
    
    app.router.post("/webhook", webhook_app.handle)
    app.router.get("/", lambda request: web.Response(text="✅ Бот работает!"))
    
    # Запускаем
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Запуск на порту {port}...")
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
