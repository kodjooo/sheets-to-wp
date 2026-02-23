import os
import asyncio
from telethon import TelegramClient


async def main():
    api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    session_name = os.getenv("TELEGRAM_SESSION_NAME", "racefinder_telethon").strip()

    if not api_id_raw or not api_hash:
        raise RuntimeError("Нужно задать TELEGRAM_API_ID и TELEGRAM_API_HASH")

    api_id = int(api_id_raw)
    client = TelegramClient(session_name, api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print(f"Сессия готова: {session_name}. Авторизован как: {getattr(me, 'username', None) or me.id}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
