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

user_library = {}
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
                    result = await resp.json()
                    return result.get("ok", False)
    except Exception as e:
        print(f"❌ Ошибка отправки видео: {e}")
        return False

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
        print(f"📥 {json.dumps(data, indent=2)[:300]}")

        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            user_id = msg["from"]["id"]
            text = msg.get("text", "")

            if user_id not in user_library:
                user_library[user_id] = []
            if user_id not in user_video_count:
                user_video_count[user_id] = 0

            if text == "/start":
                await send_message(
                    chat_id,
                    "<b>🎬 | ContentHubBot</b>\n\nТвой контент-менеджер.\n📥 Скачивай видео с YouTube, TikTok, Instagram\n📚 Храни в библиотеке\n\n👇 Выбери действие:",
                    MAIN_MENU
                )
                return

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
                    success = await send_video(
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

            await send_message(chat_id, "❌ Отправь ссылку на видео или /start", MAIN_MENU)

        elif "callback_query" in data:
            cb = data["callback_query"]
            cb_id = cb["id"]
            chat_id = cb["message"]["chat"]["id"]
            user_id = cb["from"]["id"]
            data_cb = cb.get("data", "")
            message_id = cb["message"]["message_id"]

            print(f"🔄 Нажата кнопка: {data_cb}")
            await answer_callback(cb_id)

            if data_cb == "download":
                await edit_message(
                    chat_id,
                    message_id,
                    "📥 <b>Скачать видео</b>\n\nОтправь мне ссылку на видео.\n\nПоддерживаемые площадки:\n• YouTube\n• TikTok\n• Instagram",
                    BACK_BUTTON
                )

            elif data_cb == "library":
                if not user_library.get(user_id):
                    await edit_message(chat_id, message_id, "📚 Библиотека пуста. Скачай видео!", MAIN_MENU)
                    return
                lib_text = "📚 <b>Моя библиотека</b>\n\n"
                for item in user_library[user_id]:
                    lib_text += f"🎬 Видео {item['id']}: {item['title'][:30]}...\n"
                await edit_message(chat_id, message_id, lib_text, MAIN_MENU)

            elif data_cb == "back":
                await edit_message(chat_id, message_id, "📦 Главное меню", MAIN_MENU)

            else:
                await edit_message(chat_id, message_id, "⚠️ Неизвестная команда", MAIN_MENU)

    except Exception as e:
        print(f"❌ Ошибка: {e}")
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
                    print(f"❌ Ошибка установки вебхука: {result}")

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
