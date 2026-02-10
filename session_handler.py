"""
session_handler.py
Модуль для роботи з Telegram сесіями та авторизацією
"""

import os
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError
)
import logging

logger = logging.getLogger(__name__)


async def send_verification_code(phone: str, api_id: int, api_hash: str, session_folder: str):
    """
    Відправляє код підтвердження на вказаний номер телефону.

    Args:
        phone: Номер телефону з кодом країни (наприклад, +380...)
        api_id: Telegram API ID
        api_hash: Telegram API Hash
        session_folder: Папка для збереження сесій

    Returns:
        tuple: (успіх: bool, клієнт або повідомлення_про_помилку: str)
    """
    os.makedirs(session_folder, exist_ok=True)

    # Видаляємо '+' для імені файлу сесії
    session_name = f"{phone.replace('+', '')}.session"
    session_path = os.path.join(session_folder, session_name)

    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()

        # Перевіряємо, чи вже авторизований
        if await client.is_user_authorized():
            logger.warning(f"Користувач {phone} вже авторизований")
            await client.disconnect()
            return False, "Цей номер вже авторизований у системі."

        # Відправляємо запит на код
        await client.send_code_request(phone)
        logger.info(f"✅ Код успішно надіслано на {phone}")

        # Повертаємо клієнт для подальшого використання
        # НЕ відключаємо клієнт, він потрібен для sign_in
        return True, client

    except PhoneNumberInvalidError:
        error_msg = f"Номер телефону {phone} недійсний або має неправильний формат."
        logger.error(error_msg)
        if client.is_connected():
            await client.disconnect()
        return False, error_msg

    except FloodWaitError as e:
        error_msg = f"⏱ Забагато спроб. Зачекай {e.seconds} секунд і спробуй знову."
        logger.error(error_msg)
        if client.is_connected():
            await client.disconnect()
        return False, error_msg

    except Exception as e:
        error_msg = f"Помилка при відправці коду: {str(e)}"
        logger.error(error_msg)
        if client.is_connected():
            await client.disconnect()
        return False, error_msg


async def sign_in_with_code(client: TelegramClient, phone: str, code: str, session_folder: str):
    """
    Виконує вхід в Telegram використовуючи код підтвердження.

    Args:
        client: Активний TelegramClient з відправленим запитом на код
        phone: Номер телефону
        code: 5-значний код підтвердження
        session_folder: Папка для збереження сесій

    Returns:
        tuple: (успіх: bool, шлях_до_сесії або повідомлення_про_помилку: str)
    """
    try:
        if not client.is_connected():
            await client.connect()

        # Намагаємось увійти з кодом
        await client.sign_in(phone, code=code)

        # Перевіряємо успішність авторизації
        if await client.is_user_authorized():
            session_name = f"{phone.replace('+', '')}.session"
            session_path = os.path.join(session_folder, session_name)

            logger.info(f"✅ Успішна авторизація для {phone}!")
            logger.info(f"Сесія збережена: {session_path}")

            return True, session_path
        else:
            error_msg = "Не вдалося авторизуватись. Спробуй ще раз."
            logger.error(error_msg)
            return False, error_msg

    except PhoneCodeInvalidError:
        error_msg = "❌ Невірний код підтвердження. Перевір і спробуй ще раз."
        logger.error(error_msg)
        return False, error_msg

    except PhoneCodeExpiredError:
        error_msg = "⏱ Код підтвердження застарів. Почни процес заново."
        logger.error(error_msg)
        return False, error_msg

    except SessionPasswordNeededError:
        error_msg = (
            "🔐 На цьому акаунті ввімкнена двофакторна автентифікація (2FA).\n\n"
            "Наразі бот не підтримує вхід з паролем.\n"
            "Вимкни 2FA в налаштуваннях Telegram або зв'яжись з адміністратором."
        )
        logger.error(error_msg)
        return False, error_msg

    except FloodWaitError as e:
        error_msg = f"⏱ Забагато спроб входу. Зачекай {e.seconds} секунд."
        logger.error(error_msg)
        return False, error_msg

    except Exception as e:
        error_msg = (
            f"Непередбачена помилка: {str(e)}\n\n"
            "Можливі причини:\n"
            "• Telegram заблокував спробу входу через підозрілу активність\n"
            "• Проблеми з мережею\n"
            "• Некоректні API credentials"
        )
        logger.error(f"Помилка входу: {e}")
        return False, error_msg


async def check_session_valid(phone: str, api_id: int, api_hash: str, session_folder: str):
    """
    Перевіряє, чи існує та валідна сесія для вказаного номера.

    Args:
        phone: Номер телефону
        api_id: Telegram API ID
        api_hash: Telegram API Hash
        session_folder: Папка з сесіями

    Returns:
        bool: True якщо сесія валідна, False інакше
    """
    session_name = f"{phone.replace('+', '')}.session"
    session_path = os.path.join(session_folder, session_name)

    if not os.path.exists(session_path):
        logger.info(f"Сесія для {phone} не знайдена")
        return False

    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()
        is_authorized = await client.is_user_authorized()

        if is_authorized:
            logger.info(f"✅ Сесія для {phone} валідна")
        else:
            logger.info(f"❌ Сесія для {phone} не авторизована")

        return is_authorized

    except Exception as e:
        logger.error(f"Помилка при перевірці сесії для {phone}: {e}")
        return False

    finally:
        if client.is_connected():
            await client.disconnect()


async def delete_session(phone: str, session_folder: str):
    """
    Видаляє сесію для вказаного номера.

    Args:
        phone: Номер телефону
        session_folder: Папка з сесіями

    Returns:
        bool: True якщо сесію видалено, False якщо сесії не існувало
    """
    session_name = f"{phone.replace('+', '')}.session"
    session_path = os.path.join(session_folder, session_name)

    try:
        if os.path.exists(session_path):
            os.remove(session_path)
            logger.info(f"✅ Сесію {phone} видалено")
            return True
        else:
            logger.info(f"Сесія {phone} не існує")
            return False
    except Exception as e:
        logger.error(f"Помилка при видаленні сесії {phone}: {e}")
        return False