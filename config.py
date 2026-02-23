import os
MAIN_BOT_TOKEN = os.environ.get("MAIN_BOT_TOKEN")
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")

SESSION_FOLDER = "data/sessions"
SESSION_2FA_FOLDER = "data/sessions_2fa"
CHAT_FOLDER = "data/chats"