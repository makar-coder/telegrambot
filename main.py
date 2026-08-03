import os
import asyncio
import re
import json
import html
import time
from datetime import datetime
from aiohttp import web
import aiohttp
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

# Клавиатуры
MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "📥 Сохранить контент", "callback_data": "save"}],
        [{"text": "📚 Моя библиотека", "callback_data": "library"}],
        [{"text": "📤 Опубликовать в канал", "callback_data": "publish"}]
    ]
}

BACK_BUTTON = {
    "inline_keyboard": [
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

# Хранилище пользователей (в памяти, но при перезапуске сбросится)
user_library = {}
user_states = {}

async def send_message(chat_id, text, reply_markup=None, parse_mode="HTML"):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def forward_to_channel(chat_id, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/forwardMessage"
    payload = {"chat_id": chat_id, "from_chat_id": chat_id, "message_id": message_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def send_video(chat_id, file_path, caption="", reply_markup=None):
    """Отправка видео файла в Telegram"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('chat_id', str(chat_id))
                data.add_field('caption', caption)
                data.add_field('video', f, filename=os.path.basename(file_path))
                if reply_markup:
                    data.add_field('reply_markup', json.dumps(reply_markup))
                
                async with session.post(url, data=data) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return True
                    else:
                        if "file is too big" in str(result):
                            await send_message(chat_id, f"⚠️ Файл слишком большой для Telegram (>50 МБ). Скачай его по ссылке: {file_path}")
                            return True
                        return False
    except Exception as e:
        print(f"Ошибка отправки видео: {e}")
        return False

def download_video(url):
    """Скачивает видео с помощью yt-dlp"""
    try:
        ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extract_flat': False,
        }
        
        os.makedirs("downloads", exist_ok=True)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            return filename, info.get('title', 'Video')
    except Exception as e:
        return None, str(e)

async def handle_webhook(request):
    try:
        data = await request.json()
        print(f"📥 Получен запрос: {json.dumps(data, indent=2)[:500]}...")

        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")
            username = msg["from"].get("username", "без юзера")

            # Инициализация библиотеки пользователя
            if user_id not in user_library:
                user_library[user_id] = []

            # Команда /start
            if text == "/start":
                await send_message(
                    chat_id,
                    f"<b>📦 Контент-сборщик</b>\n\n"
                    f"Привет! Я помогу тебе сохранять контент и публиковать его в канале.\n\n"
                    f"<b>Что я умею:</b>\n"
                    f"✅ Сохранять видео, фото, тексты\n"
                    f"✅ Скачивать видео с YouTube, TikTok, Instagram\n"
                    f"✅ Хранить их в библиотеке\n"
                    f"✅ Публиковать в канал\n\n"
                    f"Отправь мне ссылку на пост, видео или фото, и я сохраню его!",
                    MAIN_MENU
                )

            # Сохранение контента (фото, видео, документы)
            elif msg.get("photo") or msg.get("video") or msg.get("document"):
                content_type = "фото" if msg.get("photo") else "видео" if msg.get("video") else "документ"
                content_data = msg["photo"][-1]["file_id"] if msg.get("photo") else msg["video"]["file_id"] if msg.get("video") else msg["document"]["file_id"]
                
                item_id = len(user_library[user_id]) + 1
                saved_item = {
                    "id": item_id,
                    "type": content_type,
                    "data": content_data,
                    "timestamp": datetime.now().isoformat()
                }
                user_library[user_id].append(saved_item)

                await send_message(
                    chat_id,
                    f"✅ <b>Контент сохранён!</b>\n\n"
                    f"📌 Тип: {content_type}\n"
                    f"📁 ID: {item_id}\n"
                    f"📦 Всего в библиотеке: {len(user_library[user_id])}",
                    MAIN_MENU
                )

            # Обработка ссылок для скачивания видео
            elif text and re.search(r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)', text, re.I):
                status_msg = await send_message(
                    chat_id,
                    f"⏳ Скачиваю видео с {text.split('/')[2]}... Пожалуйста, подожди."
                )
                
                file_path, title = download_video(text)
                
                if file_path and os.path.exists(file_path):
                    success = await send_video(chat_id, file_path, f"✅ <b>{title}</b>", MAIN_MENU)
                    
                    if success:
                        await send_message(
                            chat_id,
                            "✅ Видео успешно отправлено! Если хочешь сохранить его в библиотеку — нажми кнопку '📥 Сохранить контент' и отправь это видео повторно.",
                            MAIN_MENU
                        )
                    try:
                        os.remove(file_path)
                    except:
                        pass
                else:
                    await send_message(
                        chat_id,
                        f"❌ Ошибка загрузки: {title}\n\n"
                        f"Возможные причины:\n"
                        f"• Ссылка недействительна\n"
                        f"• Видео недоступно\n"
                        f"• Нужен cookies.txt для платформы (TikTok, Instagram)",
                        MAIN_MENU
                    )

            elif text.startswith("http"):
                item_id = len(user_library[user_id]) + 1
                saved_item = {
                    "id": item_id,
                    "type": "ссылка",
                    "data": text,
                    "timestamp": datetime.now().isoformat()
                }
                user_library[user_id].append(saved_item)

                await send_message(
                    chat_id,
                    f"✅ <b>Ссылка сохранена!</b>\n\n"
                    f"📌 Тип: ссылка\n"
                    f"📁 ID: {item_id}\n"
                    f"📦 Всего в библиотеке: {len(user_library[user_id])}",
                    MAIN_MENU
                )

            else:
                await send_message(
                    chat_id,
                    "❌ Неизвестная команда. Отправь ссылку, фото или видео, чтобы сохранить.",
                    MAIN_MENU
                )

        elif "callback_query" in data:
            callback = data["callback_query"]
            callback_id = callback["id"]
            chat_id = callback["message"]["chat"]["id"]
            user_id = callback["from"]["id"]
            data_cb = callback.get("data", "")
            message_id = callback["message"]["message_id"]

            if user_id not in user_library:
                user_library[user_id] = []

            if data_cb == "menu":
                await edit_message(chat_id, message_id, "📦 <b>Главное меню</b>", MAIN_MENU)

            elif data_cb == "save":
                await edit_message(
                    chat_id,
                    message_id,
                    "📥 <b>Отправь мне контент</b>\n\n"
                    "Можешь отправить:\n"
                    "• Ссылку на пост\n"
                    "• Фото\n"
                    "• Видео\n"
                    "• Документ\n\n"
                    "Я сохраню его в твою библиотеку.",
                    BACK_BUTTON
                )

            elif data_cb == "library":
                if not user_library[user_id]:
                    await send_message(
                        chat_id,
                        "📚 <b>Библиотека пуста</b>\n\n"
                        "Сначала сохрани несколько постов!",
                        MAIN_MENU
                    )
                    await asyncio.sleep(0.5)
                    await edit_message(chat_id, message_id, "📦 <b>Главное меню</b>", MAIN_MENU)
                    return

                lib_text = "📚 <b>Твоя библиотека</b>\n\n"
                for item in user_library[user_id]:
                    lib_text += f"• {item['type'].upper()} (ID {item['id']}) - {item['timestamp'][:10]}\n"

                lib_text += f"\n📦 Всего: {len(user_library[user_id])}"

                await edit_message(chat_id, message_id, lib_text, BACK_BUTTON)

            elif data_cb == "publish":
                await send_message(
                    chat_id,
                    "📤 <b>Публикация в канал</b>\n\n"
                    "Введи ID канала (например, -1001234567890):",
                    BACK_BUTTON
                )
                user_states[user_id] = "waiting_channel_id"

            elif data_cb == "back":
                await edit_message(chat_id, message_id, "📦 <b>Главное меню</b>", MAIN_MENU)

        else:
            print(f"⚠️ Другой тип обновления: {list(data.keys())}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

    return web.Response(text="OK")

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
