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

# Хранилища
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

async def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()

async def answer_callback(callback_id, text="", show_alert=False):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id, "text": text, "show_alert": show_alert}
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
        print(f"📥 Получен запрос: {json.dumps(data, indent=2)[:500]}")

        # Обработка сообщений
        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")

            if user_id not in user_library:
                user_library[user_id] = []
            if user_id not in user_video_count:
                user_video_count[user_id] = 0

            # Если ожидаем текст для поста
            if user_states.get(user_id) == "waiting_post_text":
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

            # /start
            if text == "/start":
                await send_message(
                    chat_id,
                    f"<b>🎬 | ContentHubBot</b>\n\n"
                    f"Твой контент-менеджер.\n"
                    f"📥 Скачивай видео с YouTube, TikTok, Instagram\n"
                    f"📚 Храни в библиотеке\n"
                    f"📤 Публикуй в каналы\n\n"
                    f"👇 Выбери действие:",
                    MAIN_MENU
                )
                return

            # Ссылка на видео
            if text and re.search(r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)', text, re.I):
                await send_message(chat_id, f"⏳ Скачиваю... Подожди.")
                file_path, title = download_video(text)
                if file_path and os.path.exists(file_path):
                    user_video_count[user_id] += 1
                    video_id = user_video_count[user_id]
                    saved_item = {
                        "id": video_id,
                        "type": "видео",
                        "title": title[:50],
                        "file_path": file_path,
                        "timestamp": datetime.now().isoformat()
                    }
                    user_library[user_id].append(saved_item)
                    success, _ = await send_video(
                        chat_id,
                        file_path,
                        f"✅ <b>{title[:50]}</b>\n📁 ID: {video_id}\n📦 Сохранено в библиотеку"
                    )
                    if success:
                        await send_message(chat_id, f"✅ Видео сохранено под ID {video_id}!", MAIN_MENU)
                    try:
                        os.remove(file_path)
                    except:
                        pass
                else:
                    await send_message(chat_id, f"❌ Ошибка: {title}", MAIN_MENU)
                return

            # Всё остальное
            await send_message(chat_id, "❌ Отправь ссылку на видео или /start", MAIN_MENU)

        # ============ ОБРАБОТКА КНОПОК ============
        elif "callback_query" in data:
            callback = data["callback_query"]
            callback_id = callback["id"]
            chat_id = callback["message"]["chat"]["id"]
            user_id = callback["from"]["id"]
            data_cb = callback.get("data", "")
            message_id = callback["message"]["message_id"]

            print(f"🔄 Нажата кнопка: {data_cb} от {user_id}")

            # Удаляем старое сообщение с клавиатурой
            try:
                await delete_message(chat_id, message_id)
            except:
                pass

            # ===== КНОПКА СКАЧАТЬ ВИДЕО =====
            if data_cb == "download":
                await answer_callback(callback_id, "📥 Открой меню скачивания")
                await send_message(
                    chat_id,
                    f"📥 <b>Скачать видео</b>\n\n"
                    f"Отправь мне ссылку на видео.\n\n"
                    f"Поддерживаемые площадки:\n"
                    f"• YouTube (youtube.com, youtu.be)\n"
                    f"• TikTok (tiktok.com)\n"
                    f"• Instagram (instagram.com)\n\n"
                    f"📌 Пример: https://youtu.be/xxxxxxx",
                    BACK_BUTTON
                )

            # ===== КНОПКА МОЯ БИБЛИОТЕКА =====
            elif data_cb == "library":
                await answer_callback(callback_id, "📚 Открываю библиотеку")
                if not user_library.get(user_id):
                    await send_message(chat_id, "📚 Библиотека пуста. Скачай видео!", MAIN_MENU)
                    return

                lib_text = "📚 <b>Моя библиотека</b>\n\n"
                for item in user_library[user_id]:
                    lib_text += f"🎬 Видео {item['id']}: {item['title'][:30]}...\n"
                await send_message(chat_id, lib_text, MAIN_MENU)

            # ===== КНОПКА НАЗАД =====
            elif data_cb == "back":
                await answer_callback(callback_id, "◀️ Назад")
                await send_message(chat_id, "📦 Главное меню", MAIN_MENU)

            # ===== КНОПКА ОПУБЛИКОВАТЬ (вызывается из библиотеки) =====
            elif data_cb == "publish":
                await answer_callback(callback_id, "📤 Выбери видео")
                if not user_library.get(user_id):
                    await send_message(chat_id, "❌ Библиотека пуста.", MAIN_MENU)
                    return

                pub_text = "📤 <b>Выбери видео для публикации</b>\n\n"
                for i, item in enumerate(user_library[user_id]):
                    pub_text += f"{i+1}. Видео {item['id']}: {item['title'][:30]}...\n"
                pub_text += "\n🔢 Введи номер видео:"
                user_states[user_id] = "waiting_video_selection"
                await send_message(chat_id, pub_text, BACK_BUTTON)

            # ===== КНОПКА ОПУБЛИКОВАТЬ (финальная) =====
            elif data_cb == "do_publish":
                await answer_callback(callback_id, "📤 Публикую...")
                state = user_states.get(user_id, "")
                if not state.startswith("publish_text:"):
                    await send_message(chat_id, "❌ Сначала напиши текст для поста.", MAIN_MENU)
                    return

                text_for_post = state.replace("publish_text:", "")
                # Здесь должна быть логика выбора видео и публикации
                # Но пока упростим: отправим сообщение, что функция в разработке
                await send_message(
                    chat_id,
                    f"📤 Функция публикации в разработке.\nТекст: {text_for_post}\nСкоро будет работать!",
                    MAIN_MENU
                )
                user_states[user_id] = ""

            # Неизвестная кнопка
            else:
                await answer_callback(callback_id, "⚠️ Неизвестная команда")

        else:
            print(f"⚠️ Другой тип обновления: {list(data.keys())}")

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
