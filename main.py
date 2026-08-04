import asyncio
import html
import json
import logging
import os
import re
import time
import sqlite3
from typing import Dict, List, Optional
from datetime import datetime
from aiohttp import ClientSession, ClientTimeout, web
from dotenv import load_dotenv
from yt_dlp import YoutubeDL
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineQuery, 
    InlineKeyboardMarkup, FSInputFile,
    InlineQueryResultArticle, InputTextMessageContent
)
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GENIUS_TOKEN = os.getenv("GENIUS_TOKEN", "")

print(f"TOKEN: {str(BOT_TOKEN)[:10]}... ADMIN: {ADMIN_ID}", flush=True)
logging.basicConfig(level=logging.INFO, filename="bot.log", filemode="a",
                    format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Кэши для ускорения работы
_url_cache: Dict[str, str] = {}
_meta_cache: Dict[str, Dict] = {}
_lyrics_cache: Dict[str, str] = {}  # Новое: кэш текстов песен

# ─── DATABASE ────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect("music.db")
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, joined_at TEXT);
        CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, query TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS playlist_tracks (id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id INTEGER, title TEXT, artist TEXT, url TEXT, thumb TEXT);
        CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, text TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value INTEGER DEFAULT 0);
    """)
    for key in ("total_users", "total_searches", "total_downloads"):
        c.execute("INSERT OR IGNORE INTO stats(key, value) VALUES (?, 0)", (key,))
    conn.commit()
    conn.close()

def db(): return sqlite3.connect("music.db")

def register_user(user_id, username, first_name):
    with db() as conn:
        c = conn.cursor()
        if not c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
            c.execute("INSERT INTO users VALUES (?,?,?,?)",
                      (user_id, username, first_name, datetime.now().isoformat()))
            c.execute("UPDATE stats SET value=value+1 WHERE key='total_users'")
            conn.commit()

def log_search(user_id, query):
    with db() as conn:
        conn.execute("INSERT INTO searches(user_id, query, ts) VALUES (?,?,?)",
                     (user_id, query, datetime.now().isoformat()))
        conn.execute("UPDATE stats SET value=value+1 WHERE key='total_searches'")
        conn.commit()

def get_stats() -> dict:
    with db() as conn:
        c = conn.cursor()
        stats = dict(c.execute("SELECT key, value FROM stats").fetchall())
        stats["total_playlists"] = c.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
        stats["total_suggestions"] = c.execute("SELECT COUNT(*) FROM suggestions").fetchone()[0]
        return stats

def get_all_searches_txt() -> str:
    with db() as conn:
        rows = conn.execute(
            "SELECT u.first_name, s.query, s.ts FROM searches s "
            "LEFT JOIN users u ON u.id=s.user_id ORDER BY s.ts DESC LIMIT 1000"
        ).fetchall()
        return "\n".join([f"{ts} | {name or 'unknown'} | {q}" for name, q, ts in rows])

# ─── YT-DLP & GENIUS LOGIC ───────────────────────────────────────────────────
_id_counter = 0
_id_to_url: Dict[int, str] = {}
_url_to_id: Dict[str, int] = {}
_user_service: Dict[int, str] = {}

def store_url(url: str) -> str:
    global _id_counter
    if url in _url_to_id: return str(_url_to_id[url])
    _id_counter += 1
    _id_to_url[_id_counter] = url
    _url_to_id[url] = _id_counter
    return str(_id_counter)

def get_url(token: str) -> str:
    try: return _id_to_url.get(int(token), "")
    except: return ""

def get_user_service(user_id: int) -> str: return _user_service.get(user_id, "youtube")
def set_user_service(user_id: int, service: str): _user_service[user_id] = service

async def search_tracks(query: str, service: str = "youtube") -> List[Dict]:
    loop = asyncio.get_event_loop()
    def _search():
        prefix = "scsearch8:" if service == "soundcloud" else "ytsearch8:"
        opts = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "ignoreerrors": True}
        results = []
        with YoutubeDL(opts) as ydl:
            try: info = ydl.extract_info(f"{prefix}{query}", download=False)
            except Exception as ex: 
                print(f"SEARCH ERROR: {ex}", flush=True); return []
        
        for e in (info.get("entries") or []):
            if not e: continue
            url = e.get("webpage_url") or e.get("url", "")
            if not url: continue
            
            thumb = ""
            thumbs = e.get("thumbnails")
            if thumbs and isinstance(thumbs, list): thumb = thumbs[-1].get("url", "")
            elif e.get("thumbnail"): thumb = e.get("thumbnail")
            
            results.append({
                "title": e.get("title", "Unknown"),
                "uploader": e.get("uploader") or e.get("channel") or "Unknown",
                "url": url, "thumb": thumb, "duration": e.get("duration", 0)
            })
            if len(results) >= 8: break
        return results
    return await loop.run_in_executor(None, _search)

async def download_track(url: str) -> Optional[str]:
    loop = asyncio.get_event_loop()
    out_path = f"/tmp/track_{int(time.time())}"
    opts = {
        "quiet": True, "no_warnings": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": out_path + ".%(ext)s",
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
    }
    def _dl():
        with YoutubeDL(opts) as ydl: ydl.download([url])
        mp3 = out_path + ".mp3"
        if os.path.exists(mp3): return mp3
        for f in os.listdir("/tmp"):
            if f.startswith(f"track_{out_path.split('_')[-1]}"): return f"/tmp/{f}"
        return None
    return await loop.run_in_executor(None, _dl)

async def get_lyrics(title: str, artist: str) -> Optional[str]:
    """Исправленная функция: использует API для поиска + парсинг страницы для полного текста"""
    cache_key = f"{artist.lower()}::{title.lower()}"
    if cache_key in _lyrics_cache: return _lyrics_cache[cache_key]
    
    if not GENIUS_TOKEN: return "⚠️ Genius API токен не настроен."
    
    try:
        async with ClientSession(timeout=ClientTimeout(total=15)) as session:
            headers = {"Authorization": f"Bearer {GENIUS_TOKEN}"}
            # 1. Поиск через API
            async with session.get("https://api.genius.com/search", 
                                   params={"q": f"{artist} {title}", "per_page": 1}, 
                                   headers=headers) as r:
                data = await r.json()
                
            hits = data.get("response", {}).get("hits", [])
            if not hits: return "❌ Текст не найден в базе Genius."
            
            song_url = hits[0]["result"]["url"]
            
            # 2. Парсинг полной страницы (API часто не отдает полный текст в JSON)
            async with session.get(song_url) as page_r:
                html_text = await page_r.text()
                
            # Ищем контейнеры с текстом (актуальные классы Genius)
            patterns = [
                r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>',
                r'<div[^>]+class="Lyrics__Container[^"]*"[^>]*>(.*?)</div>'
            ]
            
            lyrics_parts = []
            for pattern in patterns:
                matches = re.findall(pattern, html_text, re.DOTALL)
                if matches:
                    lyrics_parts.extend(matches)
                    break
                    
            if not lyrics_parts:
                return f"🔗 Текст найден, но не распарсен.\nПосмотреть на Genius: {song_url}"
                
            raw = "".join(lyrics_parts)
            raw = re.sub(r'<br\s*/?>', '\n', raw)
            clean = re.sub(r'<[^>]+>', '', raw)
            clean = html.unescape(clean).strip()
            
            lines = [l.strip() for l in clean.split('\n') if l.strip()]
            final_lyrics = '\n'.join(lines)
            
            if len(final_lyrics) > 3800:
                final_lyrics = final_lyrics[:3800] + "\n\n... (текст сокращен из-за лимита Telegram)"
                
            _lyrics_cache[cache_key] = final_lyrics
            return final_lyrics
            
    except Exception as e:
        logger.error(f"Lyrics error: {e}")
        return f"⚠️ Ошибка получения текста: {str(e)}"

# ─── FSM STATES ──────────────────────────────────────────────────────────────
class SearchState(StatesGroup): waiting_query = State()
class PlaylistState(StatesGroup): waiting_name = State()
class SuggestionState(StatesGroup): waiting_text = State()

# ─── KEYBOARDS ───────────────────────────────────────────────────────────────
def main_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 Начать поиск", callback_data="search_start")
    kb.button(text="📂 Плейлисты", callback_data="playlists_menu")
    kb.button(text="💡 Предложения", callback_data="suggest_start")
    kb.button(text="⚙️ Источник музыки", callback_data="service_menu")
    kb.adjust(1)
    return kb.as_markup()

def service_kb(user_id: int):
    current = get_user_service(user_id)
    kb = InlineKeyboardBuilder()
    for key, label in [("youtube", "▶️ YouTube"), ("soundcloud", "☁️ SoundCloud")]:
        check = "✅ " if current == key else ""
        kb.button(text=f"{check}{label}", callback_data=f"set_service:{key}")
    kb.button(text="◀️ Назад", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def search_results_kb(tracks: List[Dict]):
    kb = InlineKeyboardBuilder()
    for t in tracks:
        token = store_url(t["url"])
        _url_cache[token] = t["url"]
        _meta_cache[token] = {"title": t["title"], "artist": t["uploader"]}
        kb.button(text=f"🎵 {t['title'][:40]}", callback_data=f"dl:{token}")
    kb.button(text="🏠 Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def track_kb(token: str):
    kb = InlineKeyboardBuilder()
    kb.button(text="📝 Показать текст", callback_data=f"lyr:{token}")
    kb.button(text="➕ В плейлист", callback_data=f"apl:{token}")
    kb.button(text="🏠 Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def playlists_kb(user_id: int):
    kb = InlineKeyboardBuilder()
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM playlists WHERE user_id=?", (user_id,)).fetchall()
    for pid, name in rows:
        kb.button(text=f"📁 {name}", callback_data=f"pl_open:{pid}")
    kb.button(text="➕ Создать плейлист", callback_data="pl_create")
    kb.button(text="🏠 Главное меню", callback_data="main_menu")
    kb.adjust(1)
    return kb.as_markup()

def playlist_tracks_kb(pid: int):
    kb = InlineKeyboardBuilder()
    with db() as conn:
        rows = conn.execute("SELECT id, title FROM playlist_tracks WHERE playlist_id=?", (pid,)).fetchall()
    for tid, title in rows:
        kb.button(text=f"🎵 {title[:35]}", callback_data=f"pl_play:{tid}")
    kb.button(text="🗑 Удалить плейлист", callback_data=f"pl_delete:{pid}")
    kb.button(text="◀️ Назад", callback_data="playlists_menu")
    kb.adjust(1)
    return kb.as_markup()

def admin_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📥 Скачать статистику TXT", callback_data="admin_dl_stats")
    kb.button(text="📋 Скачать логи", callback_data="admin_dl_logs")
    kb.button(text="💌 Предложения пользователей", callback_data="admin_suggestions")
    kb.adjust(1)
    return kb.as_markup()

# ─── ROUTER HANDLERS ─────────────────────────────────────────────────────────
router = Router()

@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    register_user(msg.from_user.id, msg.from_user.username, msg.from_user.first_name)
    await state.clear()
    name = msg.from_user.first_name or "друг"
    await msg.answer(
        f"👋 Привет, {name}!\n\n"
        "🎶 <b>Я музыкальный бот</b> — нахожу и скидываю треки прямо сюда.\n"
        "Все версии — оригинальные, без цензуры.\n\n"
        "Выбери что хочешь сделать:",
        reply_markup=main_menu_kb(), parse_mode="HTML"
    )

@router.message(Command("admin"))
async def cmd_admin(msg: Message):
    if msg.from_user.id != ADMIN_ID: return
    await msg.answer("🛠 <b>Админ панель</b>", reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🎶 <b>Главное меню</b>\n\nВыбери действие:",
                               reply_markup=main_menu_kb(), parse_mode="HTML")

# --- SEARCH ---
@router.callback_query(F.data == "search_start")
async def cb_search_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.waiting_query)
    await cb.message.edit_text("🔍 Введи название песни или исполнителя:")

@router.message(SearchState.waiting_query)
async def handle_search(msg: Message, state: FSMContext):
    query = msg.text.strip()
    await state.clear()
    log_search(msg.from_user.id, query)
    wait = await msg.answer("⏳ Ищу треки...")
    tracks = await search_tracks(query, get_user_service(msg.from_user.id))
    
    if not tracks:
        await wait.edit_text("❌ Ничего не нашёл. Попробуй другой запрос.", reply_markup=main_menu_kb())
        return
        
    await wait.edit_text(
        f"🎵 <b>Результаты по запросу:</b> {html.escape(query)}\n\nВыбери трек:",
        reply_markup=search_results_kb(tracks), parse_mode="HTML"
    )

# --- DOWNLOAD ---
@router.callback_query(F.data.startswith("dl:"))
async def cb_download(cb: CallbackQuery):
    token = cb.data[3:]
    url = get_url(token) or _url_cache.get(token)
    if not url:
        await cb.answer("⚠️ Трек устарел, сделай новый поиск", show_alert=True); return
        
    await cb.answer("⏳ Скачиваю...")
    wait = await cb.message.answer("⏬ Загружаю трек, это займёт 10-30 сек...")
    
    path = await download_track(url)
    if not path or not os.path.exists(path):
        await wait.edit_text("❌ Не удалось загрузить трек."); return
        
    loop = asyncio.get_event_loop()
    def get_meta():
        try:
            with YoutubeDL({"quiet": True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get("title", "Unknown"), info.get("uploader", "Unknown"), info.get("thumbnail", "")
        except: return "Unknown", "Unknown", ""
        
    title, artist, _ = await loop.run_in_executor(None, get_meta)
    _meta_cache[token] = {"title": title, "artist": artist}
    
    with db() as conn:
        conn.execute("UPDATE stats SET value=value+1 WHERE key='total_downloads'"); conn.commit()
        
    try:
        await cb.message.answer_audio(
            FSInputFile(path, filename=f"{title}.mp3"),
            title=title[:64], performer=artist[:64],
            caption=f"🎵 <b>{html.escape(title)}</b>\n👤 {html.escape(artist)}",
            parse_mode="HTML", reply_markup=track_kb(token)
        )
        await wait.delete()
    except Exception as e:
        await wait.edit_text(f"❌ Ошибка отправки: {e}")
    finally:
        try: os.remove(path)
        except: pass

# --- LYRICS (FIXED) ---
@router.callback_query(F.data.startswith("lyr:"))
async def cb_lyrics(cb: CallbackQuery):
    token = cb.data[4:]
    meta = _meta_cache.get(token, {})
    title = meta.get("title", "Unknown")
    artist = meta.get("artist", "Unknown")
    
    await cb.answer("⏳ Ищу текст...")
    lyrics = await get_lyrics(title, artist)
    
    if not lyrics or lyrics.startswith("❌"):
        await cb.message.answer(lyrics or "❌ Текст не найден.")
        return
        
    await cb.message.answer(
        f"📝 <b>{html.escape(title)}</b>\n👤 {html.escape(artist)}\n\n{html.escape(lyrics)}",
        parse_mode="HTML"
    )

# --- PLAYLISTS ---
@router.callback_query(F.data == "playlists_menu")
async def cb_playlists(cb: CallbackQuery):
    await cb.message.edit_text("📂 <b>Твои плейлисты</b>",
                               reply_markup=playlists_kb(cb.from_user.id), parse_mode="HTML")

@router.callback_query(F.data == "pl_create")
async def cb_pl_create(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PlaylistState.waiting_name)
    await cb.message.edit_text("✏️ Введи название нового плейлиста:")

@router.message(PlaylistState.waiting_name)
async def handle_pl_name(msg: Message, state: FSMContext):
    await state.clear()
    name = msg.text.strip()
    with db() as conn:
        conn.execute("INSERT INTO playlists(user_id, name, created_at) VALUES (?,?,?)",
                     (msg.from_user.id, name, datetime.now().isoformat()))
        conn.commit()
    await msg.answer(f"✅ Плейлист <b>{html.escape(name)}</b> создан!",
                     reply_markup=playlists_kb(msg.from_user.id), parse_mode="HTML")

@router.callback_query(F.data.startswith("pl_open:"))
async def cb_pl_open(cb: CallbackQuery):
    pid = int(cb.data.split(":")[1])
    with db() as conn:
        name = conn.execute("SELECT name FROM playlists WHERE id=?", (pid,)).fetchone()
    if not name: await cb.answer("Плейлист не найден"); return
    await cb.message.edit_text(f"📁 <b>{html.escape(name[0])}</b>",
                               reply_markup=playlist_tracks_kb(pid), parse_mode="HTML")

@router.callback_query(F.data.startswith("pl_delete:"))
async def cb_pl_delete(cb: CallbackQuery):
    pid = int(cb.data.split(":")[1])
    with db() as conn:
        conn.execute("DELETE FROM playlists WHERE id=?", (pid,))
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (pid,))
        conn.commit()
    await cb.message.edit_text("🗑 Плейлист удалён.", reply_markup=playlists_kb(cb.from_user.id))

@router.callback_query(F.data.startswith("apl:"))
async def cb_addpl(cb: CallbackQuery):
    token = cb.data[4:]
    user_id = cb.from_user.id
    with db() as conn:
        rows = conn.execute("SELECT id, name FROM playlists WHERE user_id=?", (user_id,)).fetchall()
    if not rows: await cb.answer("У тебя нет плейлистов. Создай сначала!", show_alert=True); return
    
    kb = InlineKeyboardBuilder()
    for pid, name in rows:
        kb.button(text=f"📁 {name}", callback_data=f"at:{pid}:{token}")
    kb.adjust(1)
    await cb.message.answer("В какой плейлист добавить?", reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("at:"))
async def cb_addto(cb: CallbackQuery):
    parts = cb.data.split(":")
    pid, token = int(parts[1]), parts[2]
    meta = _meta_cache.get(token, {})
    url = get_url(token) or _url_cache.get(token, "")
    
    with db() as conn:
        conn.execute("INSERT INTO playlist_tracks(playlist_id, title, artist, url) VALUES (?,?,?,?)",
                     (pid, meta.get("title","?"), meta.get("artist","?"), url))
        conn.commit()
    await cb.answer("✅ Добавлено в плейлист!", show_alert=True)

@router.callback_query(F.data.startswith("pl_play:"))
async def cb_pl_play(cb: CallbackQuery):
    tid = int(cb.data.split(":")[1])
    with db() as conn:
        row = conn.execute("SELECT title, artist, url FROM playlist_tracks WHERE id=?", (tid,)).fetchone()
    if not row: await cb.answer("Трек не найден"); return
    
    title, artist, url = row
    await cb.answer("⏳ Загружаю...")
    wait = await cb.message.answer("⏬ Загружаю трек из плейлиста...")
    path = await download_track(url)
    
    if not path: await wait.edit_text("❌ Не удалось загрузить."); return
    
    await cb.message.answer_audio(
        FSInputFile(path, filename=f"{title}.mp3"),
        title=title, performer=artist,
        caption=f"🎵 <b>{html.escape(title)}</b>\n👤 {html.escape(artist)}",
        parse_mode="HTML"
    )
    await wait.delete()
    try: os.remove(path)
    except: pass

# --- SUGGESTIONS ---
@router.callback_query(F.data == "suggest_start")
async def cb_suggest(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SuggestionState.waiting_text)
    await cb.message.edit_text("💡 Напиши своё предложение — какие песни добавить или что улучшить:")

@router.message(SuggestionState.waiting_text)
async def handle_suggestion(msg: Message, state: FSMContext, bot: Bot):
    await state.clear()
    text = msg.text.strip()
    with db() as conn:
        conn.execute("INSERT INTO suggestions(user_id, username, text, ts) VALUES (?,?,?,?)",
                     (msg.from_user.id, msg.from_user.username or "", text, datetime.now().isoformat()))
        conn.commit()
    await msg.answer("✅ Предложение отправлено, спасибо!", reply_markup=main_menu_kb())
    try:
        await bot.send_message(ADMIN_ID, f"💡 <b>Новое предложение</b>\n👤 @{msg.from_user.username or msg.from_user.id}\n\n{html.escape(text)}", parse_mode="HTML")
    except: pass

# --- ADMIN ---
@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    s = get_stats()
    text = (f"📊 <b>Статистика бота</b>\n\n"
            f"👥 Пользователей: <b>{s.get('total_users', 0)}</b>\n"
            f"🔍 Поисков: <b>{s.get('total_searches', 0)}</b>\n"
            f"⬇️ Скачиваний: <b>{s.get('total_downloads', 0)}</b>\n"
            f"📂 Плейлистов: <b>{s.get('total_playlists', 0)}</b>\n"
            f"💡 Предложений: <b>{s.get('total_suggestions', 0)}</b>")
    await cb.message.edit_text(text, reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_dl_stats")
async def cb_dl_stats(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != ADMIN_ID: return
    path = "/tmp/stats_export.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"Экспорт статистики {datetime.now().isoformat()}\n\n{get_all_searches_txt()}")
    await bot.send_document(ADMIN_ID, FSInputFile(path, "stats.txt"), caption="📥 Статистика поисков")
    await cb.answer()

@router.callback_query(F.data == "admin_dl_logs")
async def cb_dl_logs(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id != ADMIN_ID: return
    if os.path.exists("bot.log"):
        await bot.send_document(ADMIN_ID, FSInputFile("bot.log", "bot.log"), caption="📋 Логи бота")
    else: await cb.answer("Логов нет", show_alert=True)
    await cb.answer()

@router.callback_query(F.data == "admin_suggestions")
async def cb_admin_suggestions(cb: CallbackQuery):
    if cb.from_user.id != ADMIN_ID: return
    with db() as conn:
        rows = conn.execute("SELECT username, text, ts FROM suggestions ORDER BY ts DESC LIMIT 20").fetchall()
    if not rows: await cb.answer("Предложений нет", show_alert=True); return
    
    text = "💡 <b>Последние предложения:</b>\n\n"
    for username, msg_text, ts in rows:
        text += f"👤 @{username} [{ts[:10]}]\n{html.escape(msg_text[:200])}\n\n"
    await cb.message.edit_text(text[:4000], reply_markup=admin_kb(), parse_mode="HTML")

# --- SERVICE SELECTION ---
@router.callback_query(F.data == "service_menu")
async def cb_service_menu(cb: CallbackQuery):
    await cb.message.edit_text(
        "⚙️ <b>Выбери источник музыки</b>\n\n▶️ YouTube — всё подряд\n☁️ SoundCloud — инди, эксклюзивы",
        reply_markup=service_kb(cb.from_user.id), parse_mode="HTML")

@router.callback_query(F.data.startswith("set_service:"))
async def cb_set_service(cb: CallbackQuery):
    service = cb.data.split(":")[1]
    set_user_service(cb.from_user.id, service)
    names = {"youtube": "YouTube", "soundcloud": "SoundCloud"}
    await cb.answer(f"✅ Источник: {names.get(service, service)}", show_alert=False)
    await cb.message.edit_text(
        "⚙️ <b>Выбери источник музыки</b>\n\n▶️ YouTube — всё подряд\n☁️ SoundCloud — инди, эксклюзивы",
        reply_markup=service_kb(cb.from_user.id), parse_mode="HTML")

# --- INLINE MODE (FIXED CRITICAL BUG) ---
@router.inline_query()
async def inline_search(inline: InlineQuery):
    query = inline.query.strip()
    if not query: await inline.answer([], cache_time=1); return
    
    # ИСПРАВЛЕНО: было msg.from_user.id, стало inline.from_user.id
    service = get_user_service(inline.from_user.id) 
    tracks = await search_tracks(query, service)
    results = []
    
    for i, t in enumerate(tracks[:5]):
        token = store_url(t["url"])
        _url_cache[token] = t["url"]
        results.append(InlineQueryResultArticle(
            id=str(i), title=t["title"], description=t["uploader"],
            input_message_content=InputTextMessageContent(
                message_text=f"🎵 <b>{html.escape(t['title'])}</b>\n👤 {html.escape(t['uploader'])}\n\nОтправить: /dl {token[:40]}",
                parse_mode="HTML"
            )
        ))
    await inline.answer(results, cache_time=30)

# ─── MAIN ────────────────────────────────────────────────────────────────────
async def health(request): return web.Response(text="ok")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", 8080)))
    await site.start()

async def main():
    print("init_db...", flush=True); init_db()
    print("creating bot...", flush=True)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    print("starting polling + web...", flush=True)
    logger.info("Bot started")
    await asyncio.gather(start_web(), dp.start_polling(bot))

if __name__ == "__main__":
    import sys
    try: asyncio.run(main())
    except Exception as e: print(f"FATAL ERROR: {e}", flush=True); sys.exit(1)
