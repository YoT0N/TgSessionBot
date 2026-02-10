# session_handler.py
import os
from telethon.sync import TelegramClient
from telethon.errors import SessionPasswordNeededError, FloodWaitError, PhoneNumberInvalidError
import logging

logger = logging.getLogger(__name__)


async def sign_in_with_code(phone: str, code: str, api_id: int, api_hash: str, session_folder: str):
    """
    Намагається увійти в Telegram, використовуючи номер і код.
    Повертає (успіх, шлях_до_сесії або повідомлення_про_помилку).
    """
    os.makedirs(session_folder, exist_ok=True)
    session_name = f"{phone.replace('+', '')}.session"
    session_path = os.path.join(session_folder, session_name)

    client = TelegramClient(session_path, api_id, api_hash)
    try:
        await client.connect()
        # Відправляємо запит на код
        await client.send_code_request(phone)
        # Відразу ж намагаємося увійти з отриманим кодом
        await client.sign_in(phone, code=code)

        logger.info(f"Успішна авторизація для {phone}!")
        await client.disconnect()
        return True, session_path

    except PhoneNumberInvalidError:
        error_msg = f"Номер телефону {phone} недійсний."
        logger.error(error_msg)
        return False, error_msg
    except SessionPasswordNeededError:
        error_msg = "На цьому акаунті ввімкнена 2FA. Цей метод не підтримує паролі."
        logger.error(error_msg)
        return False, error_msg
    except FloodWaitError as e:
        error_msg = f"Забагато спроб. Спробуйте через {e.seconds} секунд."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        # Це те саме повідомлення, яке ти побачиш, якщо Telegram заблокує спробу
        error_msg = f"Помилка входу: {e}. Можливо, Telegram заблокував спробу через підозрілу активність."
        logger.error(error_msg)
        return False, error_msg
    finally:
        if client.is_connected():
            await client.disconnect()