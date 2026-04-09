import os
from functools import wraps
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ContextTypes

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_BOT_TOKEN: str = os.getenv("ADMIN_BOT_TOKEN", "")

ADMIN_IDS: list[int] = []
for _part in os.getenv("ADMIN_IDS", "").split(","):
    _part = _part.strip()
    if not _part:
        continue
    try:
        ADMIN_IDS.append(int(_part))
    except ValueError:
        pass

_admin_chat = os.getenv("ADMIN_CHAT_ID", "0")
try:
    ADMIN_CHAT_ID: int = int(_admin_chat)
except ValueError:
    ADMIN_CHAT_ID = 0

# Railway: для приватної мережі спочатку використовуйте DATABASE_PRIVATE_URL (змінні Postgres-сервісу)
_raw_db = (
    os.getenv("DATABASE_PRIVATE_URL", "").strip()
    or os.getenv("DATABASE_URL", "").strip()
    or None
)
DATABASE_URL: str | None = _raw_db
USE_POSTGRES: bool = bool(DATABASE_URL)

SQLITE_PATH: str = os.getenv("SQLITE_PATH", "college.db")

SOCIAL_INSTAGRAM_URL: str = os.getenv(
    "SOCIAL_INSTAGRAM_URL", "https://www.instagram.com/"
)
SOCIAL_TELEGRAM_URL: str = os.getenv(
    "SOCIAL_TELEGRAM_URL", "https://t.me/"
)
SOCIAL_SITE_URL: str = os.getenv("SOCIAL_SITE_URL", "https://example.com/")
SOCIAL_FACEBOOK_URL: str = os.getenv(
    "SOCIAL_FACEBOOK_URL", "https://www.facebook.com/"
)

# Розклад дзвінків (повний день): 1–5 пара — як у офіційній таблиці коледжу.
# «0 пара» залишаємо на той самий інтервал, що й 1-а (рідкісні таблиці в Excel).
LESSON_TIMES: dict[int, tuple[str, str]] = {
    0: ("08:55", "10:20"),
    1: ("08:55", "10:20"),
    2: ("10:30", "11:50"),
    3: ("12:20", "13:40"),
    4: ("13:50", "15:10"),
    5: ("15:20", "16:30"),
}

F = TypeVar("F", bound=Callable[..., Any])


def admin_only(func: F) -> F:
    @wraps(func)
    async def wrapper(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any
    ) -> Any:
        from i18n import t

        user = update.effective_user
        if not user or user.id not in ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer(
                    text=t("admin.access_denied_short"), show_alert=True
                )
            elif update.message:
                await update.message.reply_text(t("admin.access_denied"))
            elif update.edited_message:
                await update.edited_message.reply_text(t("admin.access_denied"))
            return None
        return await func(update, context, *args, **kwargs)

    return wrapper  # type: ignore[return-value]
