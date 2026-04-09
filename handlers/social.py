from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from i18n import t
from keyboards import social_keyboard


async def open_social(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        t("social.title"), reply_markup=social_keyboard()
    )


async def open_social_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        t("social.title"), reply_markup=social_keyboard()
    )


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_social, pattern=r"^menu:social$"))
