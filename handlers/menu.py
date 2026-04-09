from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

import db
from i18n import t
from keyboards import main_menu_reply_keyboard


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    un = user.username or ""
    await db.upsert_user(user.id, un)
    await update.message.reply_text(
        t("menu.welcome"), reply_markup=main_menu_reply_keyboard()
    )


async def main_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    await q.answer()
    try:
        await q.edit_message_text(t("menu.welcome"))
    except Exception:
        pass
    await q.message.reply_text(
        t("menu.reply_menu_visible"),
        reply_markup=main_menu_reply_keyboard(),
    )


def register(app) -> None:
    app.add_handler(CommandHandler("start", start_cmd))


def register_main_callback(app) -> None:
    """Register after ConversationHandlers so menu:main is not handled too early."""
    app.add_handler(
        CallbackQueryHandler(main_menu_callback, pattern=r"^menu:main$")
    )

