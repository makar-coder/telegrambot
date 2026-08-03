import os
import re
import sqlite3
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.types.webhook_info import WebhookInfo
from aiohttp import web
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
OWNER_USERNAME = "black_ide"
BOT_USERNAME = "ne_otvechu_bot"

if not BOT_TOKEN or not ADMIN_ID or not WEBHOOK_URL:
    raise ValueError("BOT_TOKEN, ADMIN_ID и WEBHOOK_URL обязательны")

# ============ БАЗА ДАННЫХ ============
def init_db():
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS library (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            video_id INTEGER,
            title TEXT,
            file_path TEXT,
            timestamp TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS counter (
            user_id INTEGER PRIMARY KEY,
            count INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def get_video_count(user_id):
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    c.execute('SELECT count FROM counter WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if row:
        return row[0]
    return 0

def increment_video_count(user_id):
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    current = get_video_count(user_id)
    c.execute('REPLACE INTO counter (user_id, count) VALUES (?, ?)', (user_id, current + 1))
    conn.commit()
    conn.close()
    return current + 1

def add_video(user_id, video_id, title, file_path):
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO library (user_id, video_id, title, file_path, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, video_id, title, file_path, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def get_library(user_id):
    conn = sqlite3.connect('library.db')
    c = conn.cursor()
    c.execute('SELECT video_id, title, file_path, timestamp FROM library WHERE user_id = ? ORDER BY id DESC', (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

init_db()

# ============ КЛАВИАТУРЫ ============
def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать видео", callback_data="download")],
        [InlineKeyboardButton(text="📚 Моя библиотека", callback_data="library")],
        [InlineKeyboardButton(text="🆘 Поддержка", url=f"https://t.me/{OWNER_USERNAME}")]
    ])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
    ])

# ============ БОТ ============
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ============ ОБРАБОТЧИКИ ============
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer(
        f"<b>🎬 | ContentHubBot</b>\n\n"
        f"Твой контент-менеджер.\n"
        f"📥 Скачивай видео с YouTube, TikTok, Instagram\n"
        f"📚 Храни в библиотеке\n"
        f"📤 Публикуй в каналы\n\n"
        f"👇 Выбери действие:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

@dp.message()
async def handle_links(message: Message):
    text = message.text
    if not text:
        return
    if re.search(r'(youtube\.com|youtu\.be|tiktok\.com|instagram\.com)', text, re.I):
        status_msg = await message.answer("⏳ Скачиваю... Подожди.")
        try:
            ydl_opts = {
                'format': 'best[height<=720]',
                'outtmpl': 'downloads/%(title)s.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'noplaylist': True,
            }
            os.makedirs('downloads', exist_ok=True)
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(text, download=True)
                filename = ydl.prepare_filename(info)
                title = info.get('title', 'Video')[:50]

            user_id = message.from_user.id
            video_id = increment_video_count(user_id)
            add_video(user_id, video_id, title, filename)

            with open(filename, 'rb') as f:
                await message.answer_video(
                    video=types.FSInputFile(filename),
                    caption=f"✅ <b>{title}</b>\n📁 ID: {video_id}\n📦 Сохранено в библиотеку",
                    reply_markup=main_keyboard(),
                    parse_mode="HTML"
                )
            os.remove(filename)
            await status_msg.delete()
        except Exception as e:
            await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")
    else:
        await message.answer("❌ Отправь ссылку на видео YouTube, TikTok или Instagram.", reply_markup=main_keyboard())

@dp.callback_query(F.data == "download")
async def download_callback(callback: CallbackQuery):
    await callback.answer("📥 Открой меню скачивания")
    await callback.message.edit_text(
        f"📥 <b>Скачать видео</b>\n\n"
        f"Отправь мне ссылку на видео.\n\n"
        f"Поддерживаемые площадки:\n"
        f"• YouTube (youtube.com, youtu.be)\n"
        f"• TikTok (tiktok.com)\n"
        f"• Instagram (instagram.com)\n\n"
        f"📌 Пример: https://youtu.be/xxxxxxx",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "library")
async def library_callback(callback: CallbackQuery):
    await callback.answer("📚 Открываю библиотеку")
    user_id = callback.from_user.id
    library = get_library(user_id)
    if not library:
        await callback.message.edit_text(
            "📚 Библиотека пуста. Скачай видео!",
            reply_markup=main_keyboard()
        )
        return
    text = "📚 <b>Моя библиотека</b>\n\n"
    for video_id, title, file_path, ts in library:
        text += f"🎬 Видео {video_id}: {title[:30]}...\n"
    await callback.message.edit_text(text, reply_markup=main_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "back")
async def back_callback(callback: CallbackQuery):
    await callback.answer("◀️ Назад")
    await callback.message.edit_text(
        f"<b>🎬 | ContentHubBot</b>\n\n"
        f"Твой контент-менеджер.\n"
        f"📥 Скачивай видео с YouTube, TikTok, Instagram\n"
        f"📚 Храни в библиотеке\n"
        f"📤 Публикуй в каналы\n\n"
        f"👇 Выбери действие:",
        reply_markup=main_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "publish")
async def publish_callback(callback: CallbackQuery):
    await callback.answer("📤 Функция в разработке")
    await callback.message.edit_text(
        "📤 Функция публикации в канал появится в следующем обновлении.",
        reply_markup=main_keyboard()
    )

# ============ ВЕБХУК ============
async def handle_webhook(request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
        return web.Response(text="OK")
    except Exception as e:
        print(f"❌ Ошибка вебхука: {e}")
        return web.Response(text="ERROR", status=500)

async def on_startup():
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    print(f"✅ Вебхук установлен: {WEBHOOK_URL}")

async def main():
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/", lambda request: web.Response(text="I'm alive ✅"))

    port = int(os.environ.get("PORT", 8080))
    await on_startup()
    print(f"🚀 Запуск на порту {port}...")
    web.run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())
