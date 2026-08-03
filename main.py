#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram-бот для скачивания и публикации видео (YouTube / TikTok / Instagram).
Работает через вебхук на aiohttp, без aiogram. Хранение данных — в памяти.

Запуск: python main.py
"""

import asyncio
import html
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession, ClientTimeout, web
from dotenv import load_dotenv
from yt_dlp import YoutubeDL

# --------------------------------------------------------------------------- #
# Конфигурация
# --------------------------------------------------------------------------- #

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "") # опционально, для заголовка секрета Telegram
PORT = int(os.getenv("PORT", "8080"))
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "black_ide")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ne_otvechu_bot")

if not BOT_TOKEN:
 raise RuntimeError("Не задан BOT_TOKEN в переменных окружения.")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE_API_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

logging.basicConfig(
 level=logging.INFO,
 format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("video-bot")

SIGNATURE_HTML = f'<a href="https://t.me/{BOT_USERNAME}">@{BOT_USERNAME}</a>'

URL_RE = re.compile(r"https?://\S+")
SUPPORTED_HOSTS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")

MAX_TELEGRAM_UPLOAD_BYTES = 50 * 1024 * 1024 # ограничение обычного Bot API на файл


# --------------------------------------------------------------------------- #
# Модели данных (в памяти)
# --------------------------------------------------------------------------- #

@dataclass
class VideoItem:
 id: int
 title: str
 file_path: str
 saved_at: float


@dataclass
class UserState:
 user_id: int
 state: str = "idle" # idle | awaiting_link | awaiting_pick | awaiting_channel | awaiting_text
 videos: Dict[int, VideoItem] = field(default_factory=dict)
 next_video_id: "count" = field(default_factory=lambda: count(1))
 # временные данные текущего сценария публикации
 pending_video_id: Optional[int] = None
 pending_channel_id: Optional[str] = None
 last_menu_message_id: Optional[int] = None


class Storage:
 """Простое in-memory хранилище состояний пользователей."""

 def __init__(self) -> None:
 self._users: Dict[int, UserState] = {}

 def get(self, user_id: int) -> UserState:
 if user_id not in self._users:
 self._users[user_id] = UserState(user_id=user_id)
 return self._users[user_id]

 def reset_scenario(self, user_id: int) -> None:
 u = self.get(user_id)
 u.state = "idle"
 u.pending_video_id = None
 u.pending_channel_id = None


STORAGE = Storage()


# --------------------------------------------------------------------------- #
# Telegram API клиент (тонкая обёртка через aiohttp)
# --------------------------------------------------------------------------- #

class TelegramAPI:
 def __init__(self, session: ClientSession):
 self.session = session

 async def _post(self, method: str, payload: Optional[dict] = None, files: Optional[dict] = None) -> dict:
 url = f"{API_URL}/{method}"
 try:
 if files:
 form = aiohttp_form_data(payload or {}, files)
 async with self.session.post(url, data=form) as resp:
 data = await resp.json()
 else:
 async with self.session.post(url, json=payload or {}) as resp:
 data = await resp.json()
 except Exception:
 log.exception("Ошибка HTTP-запроса к методу %s", method)
 return {"ok": False, "description": "network_error"}

 if not data.get("ok"):
 log.warning("Telegram API %s вернул ошибку: %s", method, data)
 return data

 async def send_message(
 self,
 chat_id: Any,
 text: str,
 reply_markup: Optional[dict] = None,
 disable_web_page_preview: bool = True,
 ) -> dict:
 payload = {
 "chat_id": chat_id,
 "text": text,
 "parse_mode": "HTML",
 "disable_web_page_preview": disable_web_page_preview,
 }
 if reply_markup is not None:
 payload["reply_markup"] = reply_markup
 return await self._post("sendMessage", payload)

 async def edit_message_text(
 self,
 chat_id: Any,
 message_id: int,
 text: str,
 reply_markup: Optional[dict] = None,
 ) -> dict:
 payload = {
 "chat_id": chat_id,
 "message_id": message_id,
 "text": text,
 "parse_mode": "HTML",
 "disable_web_page_preview": True,
 }
 if reply_markup is not None:
 payload["reply_markup"] = reply_markup
 return await self._post("editMessageText", payload)

 async def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None, show_alert: bool = False) -> dict:
 payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
 if text:
 payload["text"] = text
 payload["show_alert"] = show_alert
 return await self._post("answerCallbackQuery", payload)

 async def send_video_from_file(
 self,
 chat_id: Any,
 file_path: str,
 caption: Optional[str] = None,
 reply_markup: Optional[dict] = None,
 ) -> dict:
 payload: Dict[str, Any] = {"chat_id": str(chat_id)}
 if caption:
 payload["caption"] = caption
 payload["parse_mode"] = "HTML"
 if reply_markup is not None:
 payload["reply_markup"] = json.dumps(reply_markup)

 with open(file_path, "rb") as f:
 file_bytes = f.read()

 files = {"video": (os.path.basename(file_path), file_bytes, "video/mp4")}
 return await self._post("sendVideo", payload, files=files)

 async def get_chat_member(self, chat_id: Any, user_id: int) -> dict:
 payload = {"chat_id": chat_id, "user_id": user_id}
 return await self._post("getChatMember", payload)

 async def get_me(self) -> dict:
 return await self._post("getMe")

 async def set_webhook(self, url: str, secret_token: Optional[str] = None) -> dict:
 payload: Dict[str, Any] = {"url": url, "allowed_updates": ["message", "callback_query"]}
 if secret_token:
 payload["secret_token"] = secret_token
 return await self._post("setWebhook", payload)


def aiohttp_form_data(payload: dict, files: dict):
 from aiohttp import FormData

 form = FormData()
 for key, value in payload.items():
 if value is None:
 continue
 form.add_field(key, str(value))
 for field_name, (filename, content, content_type) in files.items():
 form.add_field(field_name, content, filename=filename, content_type=content_type)
 return form


# --------------------------------------------------------------------------- #
# Клавиатуры
# --------------------------------------------------------------------------- #

def main_menu_keyboard() -> dict:
 return {
 "inline_keyboard": [
 [{"text": "📥 Скачать видео", "callback_data": "menu:download"}],
 [{"text": "🆘 Поддержка", "url": f"https://t.me/{SUPPORT_USERNAME}"}],
 ]
 }


def back_to_menu_keyboard() -> dict:
 return {
 "inline_keyboard": [
 [{"text": "⬅️ В главное меню", "callback_data": "menu:main"}],
 ]
 }


def after_download_keyboard(video_id: int) -> dict:
 return {
 "inline_keyboard": [
 [{"text": "📤 Опубликовать в канал", "callback_data": f"publish:start:{video_id}"}],
 [{"text": "⬅️ В главное меню", "callback_data": "menu:main"}],
 ]
 }


def library_keyboard(videos: List[VideoItem]) -> dict:
 rows = []
 for v in videos:
 rows.append([{"text": f"🎬 №{v.id} — {v.title[:40]}", "callback_data": f"publish:pick:{v.id}"}])
 rows.append([{"text": "⬅️ В главное меню", "callback_data": "menu:main"}])
 return {"inline_keyboard": rows}


def cancel_keyboard() -> dict:
 return {
 "inline_keyboard": [
 [{"text": "❌ Отмена", "callback_data": "menu:main"}],
 ]
 }


# --------------------------------------------------------------------------- #
# Тексты
# --------------------------------------------------------------------------- #

WELCOME_TEXT = (
 "✨ <b>Добро пожаловать!</b>\n\n"
 "Я помогу тебе скачать видео с <b>YouTube</b>, <b>TikTok</b> и <b>Instagram</b>, "
 "а затем опубликовать его в свой канал одним нажатием кнопки.\n\n"
 "Выбери действие ниже 👇"
)

ASK_LINK_TEXT = (
 "🔗 <b>Отправь ссылку на видео</b>\n\n"
 "Поддерживаются: YouTube, TikTok, Instagram.\n"
 "Просто вставь ссылку в чат."
)

DOWNLOADING_TEXT = "⏳ <b>Скачиваю видео…</b> Это может занять до минуты."

EMPTY_LIBRARY_TEXT = (
 "📭 <b>Библиотека пуста</b>\n\n"
 "Сначала скачай хотя бы одно видео через «📥 Скачать видео»."
)

ASK_CHANNEL_TEXT = (
 "📡 <b>Введи ID канала</b>\n\n"
 "Например: <code>-1001234567890</code>\n"
 "Бот должен быть добавлен в канал как <b>администратор</b>."
)

ASK_TEXT_TEXT = (
 "✍️ <b>Введи текст для поста</b>\n\n"
 "Он будет опубликован вместе с видео. Подпись бота добавится автоматически."
)


# --------------------------------------------------------------------------- #
# yt-dlp скачивание
# --------------------------------------------------------------------------- #

def is_supported_url(url: str) -> bool:
 return any(host in url for host in SUPPORTED_HOSTS)


def download_video_sync(url: str, out_dir: str) -> Dict[str, Any]:
 """Синхронная функция скачивания (запускается в executor)."""
 timestamp = int(time.time() * 1000)
 out_template = os.path.join(out_dir, f"%(id)s_{timestamp}.%(ext)s")

 ydl_opts = {
 "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
 "outtmpl": out_template,
 "merge_output_format": "mp4",
 "quiet": True,
 "no_warnings": True,
 "noplaylist": True,
 "restrictfilenames": True,
 "max_filesize": MAX_TELEGRAM_UPLOAD_BYTES,
 }

 with YoutubeDL(ydl_opts) as ydl:
 info = ydl.extract_info(url, download=True)
 file_path = ydl.prepare_filename(info)
 # merge_output_format может поменять расширение на mp4
 if not os.path.exists(file_path):
 base, _ = os.path.splitext(file_path)
 candidate = base + ".mp4"
 if os.path.exists(candidate):
 file_path = candidate

 title = info.get("title") or "Видео"
 return {"file_path": file_path, "title": title}


async def download_video(url: str) -> Dict[str, Any]:
 loop = asyncio.get_running_loop()
 return await loop.run_in_executor(None, download_video_sync, url, DOWNLOAD_DIR)


# --------------------------------------------------------------------------- #
# Обработчики бизнес-логики
# --------------------------------------------------------------------------- #

class Bot:
 def __init__(self, api: TelegramAPI):
 self.api = api

 # ---------- Главное меню ---------- #

 async def show_main_menu(self, chat_id: int, edit_message_id: Optional[int] = None) -> None:
 STORAGE.reset_scenario(chat_id)
 if edit_message_id:
 res = await self.api.edit_message_text(chat_id, edit_message_id, WELCOME_TEXT, main_menu_keyboard())
 if res.get("ok"):
 return
 await self.api.send_message(chat_id, WELCOME_TEXT, main_menu_keyboard())

 # ---------- Скачивание ---------- #

 async def start_download_flow(self, chat_id: int, message_id: Optional[int] = None) -> None:
 user = STORAGE.get(chat_id)
 user.state = "awaiting_link"
 if message_id:
 res = await self.api.edit_message_text(chat_id, message_id, ASK_LINK_TEXT, cancel_keyboard())
 if res.get("ok"):
 return
 await self.api.send_message(chat_id, ASK_LINK_TEXT, cancel_keyboard())

 async def handle_link_message(self, chat_id: int, text: str) -> None:
 match = URL_RE.search(text or "")
 if not match:
 await self.api.send_message(
 chat_id,
 "⚠️ <b>Это не похоже на ссылку.</b>\nПопробуй ещё раз или отмени действие.",
 cancel_keyboard(),
 )
 return

 url = match.group(0)
 if not is_supported_url(url):
 await self.api.send_message(
 chat_id,
 "⚠️ <b>Платформа не поддерживается.</b>\nПришли ссылку с YouTube, TikTok или Instagram.",
 cancel_keyboard(),
 )
 return

 status_msg = await self.api.send_message(chat_id, DOWNLOADING_TEXT)
 status_message_id = status_msg.get("result", {}).get("message_id")

 try:
 result = await download_video(url)
 except Exception as exc:
 log.exception("Ошибка скачивания видео по ссылке %s", url)
 err_text = (
 "❌ <b>Не удалось скачать видео.</b>\n\n"
 f"<i>{html.escape(str(exc))[:300]}</i>"
 )
 if status_message_id:
 await self.api.edit_message_text(chat_id, status_message_id, err_text, back_to_menu_keyboard())
 else:
 await self.api.send_message(chat_id, err_text, back_to_menu_keyboard())
 STORAGE.reset_scenario(chat_id)
 return

 file_path = result["file_path"]
 title = result["title"]

 try:
 file_size = os.path.getsize(file_path)
 except OSError:
 file_size = 0

 if file_size > MAX_TELEGRAM_UPLOAD_BYTES:
 await self.api.edit_message_text(
 chat_id,
 status_message_id,
 "❌ <b>Видео слишком большое</b> для отправки через Telegram (лимит 50 МБ).",
 back_to_menu_keyboard(),
 ) if status_message_id else await self.api.send_message(
 chat_id, "❌ <b>Видео слишком большое</b> для отправки через Telegram (лимит 50 МБ).", back_to_menu_keyboard()
 )
 os.remove(file_path)
 STORAGE.reset_scenario(chat_id)
 return

 user = STORAGE.get(chat_id)
 video_id = next(user.next_video_id)
 user.videos[video_id] = VideoItem(
 id=video_id,
 title=title,
 file_path=file_path,
 saved_at=time.time(),
 )

 caption = f"✅ <b>{html.escape(title)}</b>\n\nСохранено в библиотеку под №{video_id}."
 send_res = await self.api.send_video_from_file(chat_id, file_path, caption=caption)

 if status_message_id:
 if send_res.get("ok"):
 await self.api.edit_message_text(
 chat_id, status_message_id, "✅ <b>Готово!</b> Видео отправлено выше.", after_download_keyboard(video_id)
 )
 else:
 await self.api.edit_message_text(
 chat_id,
 status_message_id,
 "⚠️ <b>Видео скачано, но не удалось отправить его в чат.</b>\nПопробуй опубликовать в канал.",
 after_download_keyboard(video_id),
 )
 else:
 await self.api.send_message(chat_id, "Что дальше?", after_download_keyboard(video_id))

 STORAGE.reset_scenario(chat_id)

 # ---------- Публикация в канал ---------- #

 async def start_publish_flow(self, chat_id: int, message_id: Optional[int], preselected_video_id: Optional[int] = None) -> None:
 user = STORAGE.get(chat_id)

 if preselected_video_id is not None and preselected_video_id in user.videos:
 user.pending_video_id = preselected_video_id
 user.state = "awaiting_channel"
 text = ASK_CHANNEL_TEXT
 keyboard = cancel_keyboard()
 else:
 if not user.videos:
 text = EMPTY_LIBRARY_TEXT
 keyboard = back_to_menu_keyboard()
 user.state = "idle"
 else:
 text = "📚 <b>Выбери видео из библиотеки:</b>"
 keyboard = library_keyboard(list(user.videos.values()))
 user.state = "awaiting_pick"

 if message_id:
 res = await self.api.edit_message_text(chat_id, message_id, text, keyboard)
 if res.get("ok"):
 return
 await self.api.send_message(chat_id, text, keyboard)

 async def handle_pick_video(self, chat_id: int, video_id: int, message_id: Optional[int]) -> None:
 user = STORAGE.get(chat_id)
 if video_id not in user.videos:
 await self.api.answer_callback_query_safe(None)
 return
 user.pending_video_id = video_id
 user.state = "awaiting_channel"
 if message_id:
 res = await self.api.edit_message_text(chat_id, message_id, ASK_CHANNEL_TEXT, cancel_keyboard())
 if res.get("ok"):
 return
 await self.api.send_message(chat_id, ASK_CHANNEL_TEXT, cancel_keyboard())

 async def handle_channel_message(self, chat_id: int, text: str) -> None:
 user = STORAGE.get(chat_id)
 channel_id = (text or "").strip()

 if not re.match(r"^-?\d+$", channel_id) and not channel_id.startswith("@"):
 await self.api.send_message(
 chat_id,
 "⚠️ <b>Некорректный ID канала.</b>\nПример: <code>-1001234567890</code> или <code>@channel_username</code>.",
 cancel_keyboard(),
 )
 return

 me = await self.api.get_me()
 bot_id = me.get("result", {}).get("id")

 member_res = await self.api.get_chat_member(channel_id, bot_id)
 if not member_res.get("ok"):
 desc = member_res.get("description", "неизвестная ошибка")
 await self.api.send_message(
 chat_id,
 f"❌ <b>Не удалось проверить доступ к каналу.</b>\n<i>{html.escape(desc)}</i>\n\n"
 "Убедись, что бот добавлен в канал.",
 cancel_keyboard(),
 )
 return

 status = member_res.get("result", {}).get("status")
 if status not in ("administrator", "creator"):
 await self.api.send_message(
 chat_id,
 "❌ <b>Бот не является администратором этого канала.</b>\n"
 "Добавь бота в администраторы и попробуй снова.",
 cancel_keyboard(),
 )
 return

 user.pending_channel_id = channel_id
 user.state = "awaiting_text"
 await self.api.send_message(chat_id, ASK_TEXT_TEXT, cancel_keyboard())

 async def handle_post_text_message(self, chat_id: int, text: str) -> None:
 user = STORAGE.get(chat_id)
 video_id = user.pending_video_id
 channel_id = user.pending_channel_id

 if video_id is None or channel_id is None or video_id not in user.videos:
 await self.api.send_message(chat_id, "⚠️ <b>Сессия публикации истекла.</b> Начни заново.", back_to_menu_keyboard())
 STORAGE.reset_scenario(chat_id)
 return

 video = user.videos[video_id]
 user_text = html.escape(text or "")
 caption = f"{user_text}\n\n{SIGNATURE_HTML}" if user_text.strip() else SIGNATURE_HTML

 if not os.path.exists(video.file_path):
 await self.api.send_message(
 chat_id, "❌ <b>Файл видео не найден.</b> Возможно, бот перезапускался.", back_to_menu_keyboard()
 )
 STORAGE.reset_scenario(chat_id)
 return

 send_res = await self.api.send_video_from_file(channel_id, video.file_path, caption=caption)

 if send_res.get("ok"):
 await self.api.send_message(
 chat_id,
 f"✅ <b>Видео опубликовано в канал!</b>\n\nID видео: №{video_id}",
 main_menu_keyboard(),
 )
 else:
 desc = send_res.get("description", "неизвестная ошибка")
 await self.api.send_message(
 chat_id,
 f"❌ <b>Не удалось опубликовать видео.</b>\n<i>{html.escape(desc)}</i>",
 back_to_menu_keyboard(),
 )

 STORAGE.reset_scenario(chat_id)


# небольшой хелпер, чтобы answerCallbackQuery можно было безопасно "проглотить"
async def _noop(*_args, **_kwargs):
 return {"ok": True}


TelegramAPI.answer_callback_query_safe = _noop # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Роутинг обновлений Telegram
# --------------------------------------------------------------------------- #

class UpdateRouter:
 def __init__(self, bot: Bot, api: TelegramAPI):
 self.bot = bot
 self.api = api

 async def handle_update(self, update: dict) -> None:
 try:
 if "callback_query" in update:
 await self._handle_callback_query(update["callback_query"])
 elif "message" in update:
 await self._handle_message(update["message"])
 except Exception:
 log.exception("Ошибка при обработке обновления: %s", update)

 async def _handle_callback_query(self, cq: dict) -> None:
 callback_id = cq.get("id")
 data = cq.get("data", "")
 message = cq.get("from") or {}
 chat = cq.get("message", {}).get("chat", {})
 chat_id = chat.get("id")
 message_id = cq.get("message", {}).get("message_id")

 if chat_id is None:
 await self.api.answer_callback_query(callback_id)
 return

 await self.api.answer_callback_query(callback_id)

 if data == "menu:main":
 await self.bot.show_main_menu(chat_id, edit_message_id=message_id)
 elif data == "menu:download":
 await self.bot.start_download_flow(chat_id, message_id=message_id)
 elif data.startswith("publish:start:"):
 video_id = int(data.split(":")[-1])
 await self.bot.start_publish_flow(chat_id, message_id, preselected_video_id=video_id)
 elif data == "publish:start":
 await self.bot.start_publish_flow(chat_id, message_id)
 elif data.startswith("publish:pick:"):
 video_id = int(data.split(":")[-1])
 await self.bot.handle_pick_video(chat_id, video_id, message_id)
 else:
 log.warning("Неизвестный callback_data: %s", data)

 async def _handle_message(self, message: dict) -> None:
 chat = message.get("chat", {})
 chat_id = chat.get("id")
 text = message.get("text", "")

 if chat_id is None:
 return

 if text == "/start" or text == "/menu":
 await self.bot.show_main_menu(chat_id)
 return

 user = STORAGE.get(chat_id)

 if user.state == "awaiting_link":
 await self.bot.handle_link_message(chat_id, text)
 elif user.state == "awaiting_pick":
 if text.strip().isdigit():
 await self.bot.handle_pick_video(chat_id, int(text.strip()), message_id=None)
 else:
 await self.api.
