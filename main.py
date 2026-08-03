import asyncio
import os
from telethon import TelegramClient, events
from telethon.tl.types import Message

# ============ ДАННЫЕ ============
API_ID = int(os.getenv("API_ID"))  # Твой api_id с my.telegram.org
API_HASH = os.getenv("API_HASH")   # Твой api_hash
PHONE_NUMBER = os.getenv("PHONE_NUMBER")  # Твой номер с +7
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Твой Telegram ID

if not API_ID or not API_HASH or not PHONE_NUMBER or not ADMIN_ID:
    raise ValueError("Все переменные обязательны: API_ID, API_HASH, PHONE_NUMBER, ADMIN_ID")

# ============ СОЗДАЁМ КЛИЕНТА ============
client = TelegramClient("userbot_session", API_ID, API_HASH)

# ============ ОБРАБОТЧИК СООБЩЕНИЙ ============
@client.on(events.NewMessage)
async def handler(event):
    """Перехватывает ВСЕ сообщения на аккаунте"""
    try:
        message = event.message
        if not message or not message.text:
            return
        
        sender_id = message.sender_id
        chat_id = message.chat_id
        text = message.text[:500]  # Обрезаем длинные сообщения
        
        # Формируем информацию
        if sender_id == chat_id:
            source = f"Личный чат (твой)"
        else:
            try:
                entity = await client.get_entity(chat_id)
                if hasattr(entity, "title"):
                    source = f"Чат: {entity.title}"
                elif hasattr(entity, "first_name"):
                    source = f"Личка: @{entity.username or 'без юзера'} ({entity.first_name})"
                else:
                    source = f"Чат ID: {chat_id}"
            except:
                source = f"Чат ID: {chat_id}"
        
        # Отправляем копию админу
        await client.send_message(
            ADMIN_ID,
            f"📩 *Перехват*\n\n"
            f"📌 {source}\n"
            f"🆔 От: {sender_id}\n"
            f"💬 Текст: {text}"
        )
        print(f"✅ Переслано: {text[:50]}...")
    except Exception as e:
        print(f"❌ Ошибка в обработчике: {e}")

# ============ ЗАПУСК ============
async def main():
    print("🚀 Запуск юзербота...")
    
    # Авторизация
    await client.start(phone=PHONE_NUMBER)
    print(f"✅ Авторизован как: {await client.get_me()}")
    print("👂 Слушаю все сообщения...")
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
