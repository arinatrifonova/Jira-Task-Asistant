import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY")
TELEGRAM_USER_ID_RAW = os.getenv("TELEGRAM_USER_ID")

required_settings = {
    "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
    "JIRA_BASE_URL": JIRA_BASE_URL,
    "JIRA_EMAIL": JIRA_EMAIL,
    "JIRA_API_TOKEN": JIRA_API_TOKEN,
    "JIRA_PROJECT_KEY": JIRA_PROJECT_KEY,
}

missing = [name for name, value in required_settings.items() if not value]

if missing:
    raise ValueError(f"Не заполнены настройки: {', '.join(missing)}")

###
if not TELEGRAM_USER_ID_RAW:
    raise ValueError("Не задан TELEGRAM_USER_ID")

try:
    TELEGRAM_USER_ID = int(TELEGRAM_USER_ID_RAW)
except ValueError:
    raise ValueError("TELEGRAM_USER_ID должен быть числом")
