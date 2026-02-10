"""
test_sessions.py
Скрипт для тестування та перевірки сесій
"""

import asyncio
import os
from session_handler import check_session_valid, delete_session
from config import API_ID, API_HASH, SESSION_FOLDER


async def list_sessions():
    """Показує всі існуючі сесії"""
    print("\n" + "=" * 50)
    print("📋 Список збережених сесій")
    print("=" * 50 + "\n")

    if not os.path.exists(SESSION_FOLDER):
        print("❌ Папка sessions/ не існує")
        return

    session_files = [f for f in os.listdir(SESSION_FOLDER) if f.endswith('.session')]

    if not session_files:
        print("📭 Немає збережених сесій")
        return

    print(f"Знайдено сесій: {len(session_files)}\n")

    for idx, session_file in enumerate(session_files, 1):
        phone = '+' + session_file.replace('.session', '')
        print(f"{idx}. {phone}")

        # Перевіряємо валідність
        is_valid = await check_session_valid(phone, API_ID, API_HASH, SESSION_FOLDER)
        status = "✅ Активна" if is_valid else "❌ Неактивна"
        print(f"   Статус: {status}\n")


async def check_specific_session():
    """Перевіряє конкретну сесію"""
    print("\n" + "=" * 50)
    print("🔍 Перевірка сесії")
    print("=" * 50 + "\n")

    phone = input("Введи номер телефону (з +): ").strip()

    if not phone.startswith('+'):
        phone = '+' + phone

    print(f"\n🔄 Перевіряю сесію для {phone}...")

    is_valid = await check_session_valid(phone, API_ID, API_HASH, SESSION_FOLDER)

    if is_valid:
        print(f"✅ Сесія для {phone} активна та валідна!")
    else:
        print(f"❌ Сесія для {phone} неактивна або не існує")


async def delete_specific_session():
    """Видаляє конкретну сесію"""
    print("\n" + "=" * 50)
    print("🗑️  Видалення сесії")
    print("=" * 50 + "\n")

    phone = input("Введи номер телефону (з +): ").strip()

    if not phone.startswith('+'):
        phone = '+' + phone

    confirm = input(f"\n⚠️  Ти впевнений, що хочеш видалити сесію для {phone}? (так/ні): ").strip().lower()

    if confirm in ['так', 'yes', 'y']:
        success = await delete_session(phone, SESSION_FOLDER)
        if success:
            print(f"✅ Сесію для {phone} видалено")
        else:
            print(f"❌ Не вдалося видалити сесію (можливо, її не існує)")
    else:
        print("❌ Скасовано")


async def clean_invalid_sessions():
    """Видаляє всі неактивні сесії"""
    print("\n" + "=" * 50)
    print("🧹 Очищення неактивних сесій")
    print("=" * 50 + "\n")

    if not os.path.exists(SESSION_FOLDER):
        print("❌ Папка sessions/ не існує")
        return

    session_files = [f for f in os.listdir(SESSION_FOLDER) if f.endswith('.session')]

    if not session_files:
        print("📭 Немає сесій для перевірки")
        return

    print(f"🔄 Перевіряю {len(session_files)} сесій...\n")

    deleted_count = 0

    for session_file in session_files:
        phone = '+' + session_file.replace('.session', '')
        is_valid = await check_session_valid(phone, API_ID, API_HASH, SESSION_FOLDER)

        if not is_valid:
            print(f"❌ {phone} - неактивна, видаляю...")
            await delete_session(phone, SESSION_FOLDER)
            deleted_count += 1
        else:
            print(f"✅ {phone} - активна")

    print(f"\n🗑️  Видалено неактивних сесій: {deleted_count}")


async def main_menu():
    """Головне меню"""
    while True:
        print("\n" + "=" * 50)
        print("🔧 Тестування та управління сесіями")
        print("=" * 50)
        print("\n1. 📋 Показати всі сесії")
        print("2. 🔍 Перевірити конкретну сесію")
        print("3. 🗑️  Видалити конкретну сесію")
        print("4. 🧹 Очистити неактивні сесії")
        print("5. 🚪 Вийти")
        print()

        choice = input("Вибери опцію (1-5): ").strip()

        if choice == '1':
            await list_sessions()
        elif choice == '2':
            await check_specific_session()
        elif choice == '3':
            await delete_specific_session()
        elif choice == '4':
            await clean_invalid_sessions()
        elif choice == '5':
            print("\n👋 До побачення!")
            break
        else:
            print("\n❌ Невірний вибір. Спробуй ще раз.")

        input("\nНатисни Enter для продовження...")


if __name__ == "__main__":
    try:
        asyncio.run(main_menu())
    except KeyboardInterrupt:
        print("\n\n👋 До побачення!")
    except Exception as e:
        print(f"\n❌ Помилка: {e}")