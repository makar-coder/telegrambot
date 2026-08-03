import os
import re
import json
import asyncio
import yt_dlp
from datetime import datetime
from aiohttp import web
import aiohttp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "ne_otvechu_bot"
OWNER_USERNAME = "black_ide"

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

# ============ ДАННЫЕ ПОЛЬЗОВАТЕЛЕЙ ============
user_library = {}       # {user_id: [ {id, title, file_path, timestamp} ]}
user_video_count = {}   # {user_id: int}
user_states = {}        # {user_id: "waiting_video_selection" | "waiting_post_text" | "waiting_channel_id" | "publish_text:..."}

# ============ КЛАВИАТУРЫ ============
MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "📥 Скачать видео", "callback_data": "download"}],
        [{"text": "🆘 Поддержка", "url": f"https://t.me/{OWNER_USERNAME}"}]
    ]
}

BACK_BUTTON = {
    "inline_keyboard": [
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

PUBLISH_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "📤 Опубликовать в канал", "callback_data": "publish"}],
        [{"text": "◀️ Назад", "callback_data": "back"}]
    ]
}

# ============ ФУНКЦИИ ОТПРАВКИ ============
async def send_message(chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback(callback_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"callback_query_id": callback_id}) as resp:
            return await resp.json()

async def send_video(chat_id, file_path, caption=""):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('chat_id', str(chat_id))
                data.add_field('caption', caption)
                data.add_field('video', f, filename=os.path.basename(file_path))
                async with session.post(url, data=data) as resp:
                    return await resp.json()
    except Exception as e:
        print(f"❌ Ошибка отправки видео: {e}")
        return None

async def send_video_to_channel(channel_id, file_path, caption):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendVideo"
    try:
        async with aiohttp.ClientSession() as session:
            with open(file_path, 'rb') as f:
                data = aiohttp.FormData()
                data.add_field('chat_id', channel_id)
                data.add_field('caption', caption + f"\n\n<a href='https://t.me/{BOT_USERNAME}'>@{BOT_USERNAME}</a>")
                data.add_field('parse_mode', 'HTML')
                data.add_field('video', f, filename=os.path.basename(file_path))
                async with session.post(url, data=data) as resp:
                    return await resp.json()
    except Exception as e:
        print(f"❌ Ошибка публикации: {e}")
        return None

def download_video(url):
    try:
        ydl_opts = {
            'format': 'best[height<=720]',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
        }
        os.makedirs("downloads", exist_ok=True)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info), info.get('title', 'Video')
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

            # Инициализация
            if user_id not in user_library:
                user_library[user_id] = []
            if user_id not in user_video_count:
                user_video_count[user_id] = 0

            # ===== ОБРАБОТКА СОСТОЯНИЙ =====
            state = user_states.get(user_id, "")

            # Состояние: ожидание текста для поста
            if state == "waiting_post_text":
                if text:
                    user_states[user_id] = f"publish_text:{text}"
                    await send_message(
                        chat_id,
                        f"📤 <b>Пост готов!</b>\n\nТекст:\n{text}\n\nНажми кнопку ниже, чтобы опубликовать в канал.",
                        {"inline_keyboard": [[{"text": "📤 Опубликовать", "callback_data": "do_publish"}]]}
                    )
                else:
                    await send_message(chat_id, "❌ Отправь текст для поста.", BACK_BUTTON)
                return

            # Состояние: ожидание ID канала
            if state == "waiting_channel_id":
                if text and text.lstrip('-').isdigit():
                    user_states[user_id] = f"channel_id:{text}"
                    await send_message(
                        chat_id,
                        f"✅ Канал ID {text} сохранён!\n\nТеперь отправь <b>текст</b> для поста:",
                        BACK_BUTTON
                    )
                    user_states[user_id] = "waiting_post_text"
                else:
                    await send_message(chat_id, "❌ Введи корректный ID канала (только цифры, может начинаться с -).", BACK_BUTTON)
                return

            # Если есть текст для публикации и выбрано видео
            if state.startswith("publish_text:"):
                text_for_post = state.replace("publish_text:", "")
                # Проверяем, есть ли выбранное видео
                selected_video_id = user_states.get(f"selected_video_{user_id}", None)
                if selected_video_id:
                    # Ищем видео в библиотеке
                    selected_video = None
                    for item in user_library[user_id]:
                        if item['id'] == selected_video_id:
                            selected_video = item
                            break
                    if selected_video and os.path.exists(selected_video['file_path']):
                        # Публикуем
                        result = await send_video_to_channel(
                            user_states.get(f"channel_{user_id}", ""),
                            selected_video['file_path'],
                            text_for_post
                        )
                        if result and result.get("ok"):
                            await send_message(chat_id, f"✅ <b>Пост опубликован в канале!</b>\n\n📌 Текст: {text_for_post}", MAIN_MENU)
                        else:
                            await send_message(chat_id, f"❌ Ошибка публикации. Убедись, что бот добавлен в канал как администратор.", MAIN_MENU)
                        user_states[user_id] = ""
                        return
                    else:
                        await send_message(chat_id, "❌ Видео не найдено. Попробуй снова.", MAIN_MENU)
                        user_states[user_id] = ""
                        return

            # ===== /start =====
            if text == "/start":
                await send_message(
                    chat_id,
                    "<b>🎬 | ContentHubBot</b>\n\nТвой контент-менеджер.\n📥 Скачивай видео с YouTube, TikTok, Instagram\n📚 Храни в библиотеке\n📤 Публикуй в каналы\n\n👇 Выбери действие:",
                    MAIN_MENU
                )
                return

            # ===== СКАЧИВАНИЕ ПО ССЫЛКЕ =====
            if re.search(r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)', text, re.I):
                await send_message(chat_id, "⏳ Скачиваю... Подожди.")
                file_path, title = download_video(text)
                if file_path and os.path.exists(file_path):
                    user_video_count[user_id] += 1
                    video_id = user_video_count[user_id]
                    user_library[user_id].append({
                        "id": video_id,
                        "title": title[:50],
                        "file_path": file_path,
                        "timestamp": datetime.now().isoformat()
                    })
                    result = await send_video(
                        chat_id,
                        file_path,
                        f"✅ <b>{title[:50]}</b>\n📁 ID: {video_id}\n📦 Сохранено в библиотеку"
                    )
                    if result and result.get("ok"):
                        await send_message(
                            chat_id,
                            f"✅ Видео сохранено под ID {video_id}!",
                            PUBLISH_KEYBOARD
                        )
                    try:
                        os.remove(file_path)
                    except:
                        pass
                else:
                    await send_message(chat_id, f"❌ Ошибка загрузки: {title}", MAIN_MENU)
                return

            # ===== НЕИЗВЕСТНАЯ КОМАНДА =====
            await send_message(chat_id, "❌ Отправь ссылку на видео или /start", MAIN_MENU)

        # ============ ОБРАБОТКА КНОПОК ============
        elif "callback_query" in data:
            cb = data["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            user_id = cb["from"]["id"]
            data_cb = cb.get("data", "")
            message_id = cb["message"]["message_id"]

            print(f"🔄 Нажата кнопка: {data_cb} от {user_id}")
            await answer_callback(cb_id)

            if user_id not in user_library:
                user_library[user_id] = []

            # ===== СКАЧАТЬ ВИДЕО =====
            if data_cb == "download":
                await edit_message(
                    chat_id,
                    message_id,
                    "📥 <b>Скачать видео</b>\n\nОтправь мне ссылку на видео.\n\nПоддерживаемые площадки:\n• YouTube\n• TikTok\n• Instagram\n\n📌 Пример: https://youtu.be/xxxxxxx",
                    BACK_BUTTON
                )

            # ===== ОПУБЛИКОВАТЬ =====
            elif data_cb == "publish":
                if not user_library.get(user_id):
                    await edit_message(chat_id, message_id, "❌ Библиотека пуста. Сначала скачай видео.", MAIN_MENU)
                    return

                # Показываем список видео для выбора
                lib_text = "📤 <b>Выбери видео для публикации</b>\n\n"
                for i, item in enumerate(user_library[user_id]):
                    lib_text += f"{i+1}. Видео {item['id']}: {item['title'][:30]}...\n"
                lib_text += f"\n🔢 Напиши номер видео (1, 2, 3...)"

                await edit_message(chat_id, message_id, lib_text, BACK_BUTTON)
                user_states[user_id] = "waiting_video_selection"

            # ===== ОБРАБОТКА ВЫБОРА ВИДЕО (текстом) =====
            elif data_cb == "back":
                await edit_message(chat_id, message_id, "📦 Главное меню", MAIN_MENU)
                user_states[user_id] = ""

            # ===== ОПУБЛИКОВАТЬ (финальная кнопка) =====
            elif data_cb == "do_publish":
                await edit_message(
                    chat_id,
                    message_id,
                    "📤 <b>Публикация в канал</b>\n\nВведи <b>ID канала</b> (например, -1001234567890):\n\n<i>Бот должен быть администратором канала!</i>",
                    BACK_BUTTON
                )
                user_states[user_id] = "waiting_channel_id"

            else:
                await edit_message(chat_id, message_id, "⚠️ Неизвестная команда", MAIN_MENU)

        else:
            print(f"⚠️ Другой тип обновления")

    except Exception as e:
        print(f"❌ ОШИБКА В ВЕБХУКЕ: {e}")
        import traceback
        traceback.print_exc()

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
