import os
import json
import asyncio
from aiohttp import web
import aiohttp

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("BOT_TOKEN и ADMIN_ID обязательны")

async def send_message(chat_id, text):
    """Отправка сообщения через Telegram API"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json={"chat_id": chat_id, "text": text}) as resp:
            return await resp.json()

async def handle_webhook(request):
    """Обработчик вебхука с логированием"""
    try:
        data = await request.json()
        print(f"📥 Получен запрос: {json.dumps(data, indent=2)}")
        
        # Проверяем, что это сообщение
        if "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            user = message.get("from", {})
            text = message.get("text", "❌ Нет текста")
            username = user.get("username", "без юзера")
            full_name = user.get("first_name", "") + " " + user.get("last_name", "")
            
            print(f"📩 Сообщение от {full_name} (@{username}): {text}")
            
            # Отправляем копию админу
            await send_message(
                ADMIN_ID,
                f"📩 От: {full_name} (@{username})\n\n{text}"
            )
            
            # Отвечаем пользователю
            await send_message(chat_id, "✅ Сообщение получено и передано админу.")
            
        elif "callback_query" in data:
            print(f"🔄 Callback: {data['callback_query']}")
            
        else:
            print(f"⚠️ Другой тип обновления: {list(data.keys())}")
            
    except Exception as e:
        print(f"❌ Ошибка в handle_webhook: {e}")
    
    return web.Response(text="OK")

async def on_startup():
    """Установка вебхука"""
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    if WEBHOOK_URL:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={WEBHOOK_URL}&drop_pending_updates=true"
        print(f"🔗 Устанавливаю вебхук: {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                result = await resp.json()
                if result.get("ok"):
                    print(f"✅ Вебхук установлен: {WEBHOOK_URL}")
                else:
                    print(f"❌ Ошибка установки вебхука: {result}")
    else:
        print("⚠️ WEBHOOK_URL не задан!")

async def health_check(request):
    """Проверка здоровья"""
    return web.Response(text="I'm alive ✅")

app = web.Application()
app.router.add_post("/webhook", handle_webhook)
app.router.add_get("/", health_check)
app.router.add_get("/health", health_check)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    
    # Устанавливаем вебхук перед запуском
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(on_startup())
    
    print(f"🚀 Запуск на порту {port}...")
    print(f"🔗 Вебхук ожидает запросы на /webhook")
    web.run_app(app, host="0.0.0.0", port=port)
