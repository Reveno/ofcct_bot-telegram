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

DATABASE_URL: str | None = os.getenv("DATABASE_URL") or None
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

LESSON_TIMES: dict[int, tuple[str, str]] = {
    0: ("07:45", "09:20"),
    1: ("09:30", "11:05"),
    2: ("11:20", "12:55"),
    3: ("13:10", "14:45"),
    4: ("15:00", "16:35"),
    5: ("16:45", "18:20"),
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
