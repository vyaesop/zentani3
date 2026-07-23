import os

from .settings import *  # noqa


DEBUG = True
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ── Hermetic guards ─────────────────────────────────────────────────
# `.env` holds REAL Neon/Telegram/Cloudinary/Gemini credentials, and parts of
# the code (telegram_notify) read os.environ at call time. Local/test runs
# must never talk to those services, so scrub both settings and process env.
GEMINI_API_KEY = ""
AI_IMAGE_GENERATOR_ENDPOINT = ""
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "zent-cache-local",
        "TIMEOUT": 300,
    }
}
for _name in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALERT_CHAT_ID",
    "TELEGRAM_CUSTOMER_BOT_TOKEN",
    "TELEGRAM_CUSTOMER_CHANNEL_CHAT_ID",
    "TELEGRAM_CUSTOMER_BOT_USERNAME",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_CUSTOMER_WEBHOOK_SECRET",
    "TELEGRAM_ADMIN_WEBHOOK_SECRET",
):
    os.environ.pop(_name, None)
