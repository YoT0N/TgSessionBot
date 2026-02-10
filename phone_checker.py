"""
phone_checker.py
Модуль для перевірки номерів телефону користувачів
"""

import logging
from telethon import TelegramClient
from telethon.tl.types import User
from config import API_ID, API_HASH

logger = logging.getLogger(__name__)


async def get_phone_by_user_id(client: TelegramClient, user_id: int):
    """
    Отримує номер телефону за user_id.

    Args:
        client: Активний TelegramClient
        user_id: ID користувача

    Returns:
        str | None: Номер телефону або None
    """
    try:
        user = await client.get_entity(user_id)

        if isinstance(user, User) and user.phone:
            logger.info(f"✅ Номер знайдено для user_id {user_id}: {user.phone}")
            return user.phone
        else:
            logger.info(f"❌ Номер прихований для user_id {user_id}")
            return None

    except ValueError:
        logger.warning(f"❌ Не вдалося знайти користувача {user_id}")
        return None
    except Exception as e:
        logger.error(f"❌ Помилка при отриманні даних: {e}")
        return None


async def get_phone_by_username(client: TelegramClient, username: str):
    """
    Отримує номер телефону за username.

    ЦЕ ПРАЦЮЄ! Username - це публічна інформація в Telegram.

    Args:
        client: Активний TelegramClient
        username: Username користувача (без @)

    Returns:
        dict: {'phone': str|None, 'user_id': int, 'first_name': str, ...}
    """
    try:
        # Видаляємо @ якщо є
        username = username.lstrip('@')

        logger.info(f"🔍 Шукаю користувача @{username}...")

        # Отримуємо entity за username - ЦЕ ПРАЦЮЄ ЗАВЖДИ для публічних username!
        user = await client.get_entity(username)

        if not isinstance(user, User):
            logger.error(f"❌ @{username} не є користувачем")
            return None

        result = {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone,  # Буде None якщо прихований
            'is_bot': user.bot,
            'phone_visible': user.phone is not None
        }

        if user.phone:
            logger.info(f"✅ Номер ВІДКРИТИЙ для @{username}: {user.phone}")
        else:
            logger.info(f"🔒 Номер ПРИХОВАНИЙ для @{username}")

        return result

    except ValueError:
        logger.error(f"❌ Користувача @{username} не знайдено")
        return None
    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        return None


async def check_phone_visibility(session_path: str, api_id: int, api_hash: str, username: str):
    """
    Перевіряє чи відкритий номер телефону у користувача.

    Standalone функція - можна викликати без активного клієнта.

    Args:
        session_path: Шлях до файлу сесії
        api_id: Telegram API ID
        api_hash: Telegram API Hash
        username: Username користувача

    Returns:
        dict | None: Інформація про користувача або None
    """
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            logger.error("❌ Сесія не авторизована")
            return None

        result = await get_phone_by_username(client, username)
        return result

    finally:
        await client.disconnect()


# ============================================
# ТЕСТУВАННЯ
# ============================================

async def test_phone_checker():
    """Тестова функція для перевірки роботи"""
    from config import API_ID, API_HASH

    session_path = "sessions/my_account.session"

    print("=" * 60)
    print("🔍 Тестування перевірки номерів телефону")
    print("=" * 60)

    # Приклади username для тестування
    test_usernames = [
        "durov",  # Павло Дуров (засновник Telegram)
        "telegram",  # Офіційний Telegram
        # Додай свій username для тесту
    ]

    client = TelegramClient(session_path, API_ID, API_HASH)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            print("❌ Спочатку авторизуйся через create_my_session.py")
            return

        for username in test_usernames:
            print(f"\n{'=' * 60}")
            print(f"Перевіряю: @{username}")
            print("=" * 60)

            result = await get_phone_by_username(client, username)

            if result:
                print(f"✅ Користувач знайдений:")
                print(f"   User ID: {result['user_id']}")
                print(f"   Ім'я: {result['first_name']} {result['last_name'] or ''}")
                print(f"   Username: @{result['username']}")
                print(f"   Бот: {'Так' if result['is_bot'] else 'Ні'}")

                if result['phone']:
                    print(f"   📱 Номер: {result['phone']} (ВІДКРИТИЙ ✅)")
                else:
                    print(f"   🔒 Номер: ПРИХОВАНИЙ ❌")
            else:
                print(f"❌ Користувача не знайдено")

    finally:
        await client.disconnect()


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_phone_checker())