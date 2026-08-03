import os
import asyncio
import re
import json
import time
from datetime import datetime
from aiohttp import web
import aiohttp
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "ne_otvechu_bot"
OWNER_USERNAME = "black_ide"

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

# Хранилище
user_library = {}
user_states = {}
user_video_count = {}

# ============ КЛАВИАТУРЫ ============
MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "📥 Скачать видео", "callback_data": "download"}],
        [{"text": "📚 Моя библиотека", "callback_data": "library"}],
        [{"text": "🆘 Поддержка", "url": f"https://t.me/{OWNER_USERNAME}"}]
    ]
}

LIBRARY_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "📤 Опубликовать в канал", "callback_data": "publish"}],
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

PUBLISH_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "📤 Опубликовать", "callback_data": "do_publish"}],
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

BACK_BUTTON = {
    "inline_keyboard": [
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

# ============ ФУНКЦИИ ============
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

async def send_video(chat_id, file_path, caption="", reply_markup=None):
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
                        return True, result["result"]["message_id"]
                    else:
                        if "file is too big" in str(result):
                            await send_message(chat_id, f"⚠️ Файл слишком большой для Telegram (>50 МБ)")
                            return False, None
                        return False, None
    except Exception as e:
        print(f"Ошибка отправки видео: {e}")
        return False, None

async def forward_to_channel(chat_id, message_id, channel_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload = {
        "chat_id": channel_id,
        "from_chat_id": chat_id,
        "message_id": message_id
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def send_to_channel_with_text(chat_id, channel_id, text, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
    payload = {
        "chat_id": channel_id,
        "from_chat_id": chat_id,
        "message_id": message_id,
        "caption": text,
        "parse_mode": "HTML"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

def download_video(url):
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

# ============ ВЕБХУК ============
async def handle_webhook(request):
    try:
        data = await request.json()
        print(f"📥 Получен запрос")

        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")
            username = msg["from"].get("username", "без юзера")

            if user_id not in user_library:
                user_library[user_id] = []
            if user_id not in user_video_count:
                user_video_count[user_id] = 0

            # Обработка состояния (ожидание текста для поста)
            if user_states.get(user_id) == "waiting_post_text":
                if text:
                    user_states[user_id] = f"publish_text:{text}"
                    await send_message(
                        chat_id,
                        f"📤 <b>Пост готов к публикации!</b>\n\n"
                        f"Текст:\n{text}\n\n"
                        f"Нажми кнопку ниже, чтобы опубликовать в канал.",
                        PUBLISH_KEYBOARD
                    )
                else:
                    await send_message(chat_id, "❌ Отправь текст для поста.", BACK_BUTTON)
                return

            # Команда /start
            if text == "/start":
                await send_message(
                    chat_id,
                    f"<b>📦 ContentHubBot</b>\n\n"
                    f"Твой личный контент-менеджер в Telegram.\n\n"
                    f"<b>Что я умею:</b>\n"
                    f"📥 Скачивать видео с YouTube, TikTok, Instagram\n"
                    f"📚 Хранить всё в библиотеке\n"
                    f"📤 Публиковать в каналы\n\n"
                    f"👇 Выбери действие:",
                    MAIN_MENU
                )

            # Скачивание видео по ссылке
            elif text and re.search(r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)', text, re.I):
                await send_message(
                    chat_id,
                    f"⏳ Скачиваю видео... Пожалуйста, подожди."
                )
                
                file_path, title = download_video(text)
                
                if file_path and os.path.exists(file_path):
                    user_video_count[user_id] += 1
                    video_id = user_video_count[user_id]
                    
                    # Сохраняем в библиотеку
                    saved_item = {
                        "id": video_id,
                        "type": "видео",
                        "title": title[:50],
                        "file_path": file_path,
                        "timestamp": datetime.now().isoformat()
                    }
                    user_library[user_id].append(saved_item)

                    success, msg_id = await send_video(
                        chat_id, 
                        file_path, 
                        f"✅ <b>{title[:50]}</b>\n\n📁 ID: {video_id}\n📦 Сохранено в библиотеку"
                    )
                    
                    if success:
                        await send_message(
                            chat_id,
                            f"✅ Видео сохранено в библиотеку под ID {video_id}!",
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
                        f"• Нужен cookies.txt для платформы",
                        MAIN_MENU
                    )

            else:
                await send_message(
                    chat_id,
                    "❌ Отправь ссылку на видео с YouTube, TikTok или Instagram.",
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

            # ===== СКАЧАТЬ ВИДЕО =====
            if data_cb == "download":
                await edit_message(
                    chat_id,
                    message_id,
                    f"📥 <b>Скачать видео</b>\n\n"
                    f"Просто отправь мне ссылку на видео.\n\n"
                    f"<b>Поддерживаемые площадки:</b>\n"
                    f"• YouTube (youtube.com, youtu.be)\n"
                    f"• TikTok (tiktok.com)\n"
                    f"• Instagram (instagram.com)\n\n"
                    f"📌 <b>Примеры ссылок:</b>\n"
                    f"• https://youtu.be/xxxxxxx\n"
                    f"• https://www.tiktok.com/@user/video/xxxx\n"
                    f"• https://www.instagram.com/reel/xxxx",
                    BACK_BUTTON
                )

            # ===== МОЯ БИБЛИОТЕКА =====
            elif data_cb == "library":
                if not user_library[user_id]:
                    await edit_message(
                        chat_id,
                        message_id,
                        f"📚 <b>Библиотека пуста</b>\n\n"
                        f"Скачай хотя бы одно видео, чтобы оно появилось здесь.",
                        BACK_BUTTON
                    )
                    return

                lib_text = f"📚 <b>Моя библиотека</b>\n\n"
                for item in user_library[user_id]:
                    lib_text += f"🎬 <b>Видео {item['id']}</b>\n"
                    lib_text += f"📌 {item['title'][:40]}...\n"
                    lib_text += f"📅 {item['timestamp'][:10]}\n\n"

                await edit_message(
                    chat_id,
                    message_id,
                    lib_text,
                    LIBRARY_KEYBOARD
                )

            # ===== ОПУБЛИКОВАТЬ В КАНАЛ =====
            elif data_cb == "publish":
                if not user_library[user_id]:
                    await send_message(
                        chat_id,
                        "❌ Библиотека пуста. Сначала скачай видео.",
                        MAIN_MENU
                    )
                    return

                # Показываем список видео для выбора
                pub_text = f"📤 <b>Выбери видео для публикации</b>\n\n"
                for i, item in enumerate(user_library[user_id]):
                    pub_text += f"{i+1}. {item['title'][:40]}... (ID {item['id']})\n"
                pub_text += f"\n🔢 <b>Введи номер видео для публикации:</b>"

                await send_message(
                    chat_id,
                    pub_text,
                    BACK_BUTTON
                )
                user_states[user_id] = "waiting_video_selection"

            # ===== ДЕЙСТВИТЕЛЬНО ОПУБЛИКОВАТЬ =====
            elif data_cb == "do_publish":
                # Проверяем, есть ли текст для поста
                state = user_states.get(user_id, "")
                if state.startswith("publish_text:"):
                    text_for_post = state.replace("publish_text:", "")
                    
                    # Ищем последнее выбранное видео
                    channel_id = user_states.get(f"channel_{user_id}", "")
                    video_id = user_states.get(f"video_{user_id}", "")

                    if not channel_id:
                        await send_message(chat_id, "❌ Сначала укажи ID канала.", MAIN_MENU)
                        return

                    # Ищем видео в библиотеке
                    selected_video = None
                    for item in user_library[user_id]:
                        if str(item['id']) == video_id:
                            selected_video = item
                            break

                    if not selected_video or not os.path.exists(selected_video.get('file_path', '')):
                        await send_message(chat_id, "❌ Видео не найдено в библиотеке.", MAIN_MENU)
                        return

                    # Отправляем в канал
                    try:
                        # Сначала отправляем видео в канал
                        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
                        async with aiohttp.ClientSession() as session:
                            with open(selected_video['file_path'], 'rb') as f:
                                data_send = aiohttp.FormData()
                                data_send.add_field('chat_id', channel_id)
                                data_send.add_field('caption', f"{text_for_post}\n\n<a href='https://t.me/{BOT_USERNAME}'>@{BOT_USERNAME}</a>")
                                data_send.add_field('parse_mode', 'HTML')
                                data_send.add_field('video', f, filename=os.path.basename(selected_video['file_path']))
                                
                                async with session.post(url, data=data_send) as resp:
                                    result = await resp.json()
                                    if result.get("ok"):
                                        await send_message(
                                            chat_id,
                                            f"✅ <b>Пост опубликован в канале!</b>\n\n"
                                            f"📌 Текст: {text_for_post}\n"
                                            f"📤 Канал: {channel_id}",
                                            MAIN_MENU
                                        )
                                        user_states[user_id] = ""
                                    else:
                                        await send_message(
                                            chat_id,
                                            f"❌ Ошибка публикации: {result}",
                                            MAIN_MENU
                                        )
                    except Exception as e:
                        await send_message(chat_id, f"❌ Ошибка публикации: {e}", MAIN_MENU)

            # ===== НАЗАД =====
            elif data_cb == "back":
                await edit_message(chat_id, message_id, "📦 <b>Главное меню</b>", MAIN_MENU)

        else:
            print(f"⚠️ Другой тип обновления")

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
    web.run_app(app, host="0.0.0.0", port=port)
