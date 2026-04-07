from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from admin_keyboards import admin_reply_feedback_keyboard
from config import ADMIN_CHAT_ID
from i18n import t
from keyboards import back_to_menu_keyboard, main_menu_keyboard

WAITING_TEXT = 1


def _user_ref(user) -> str:
    if user.username:
        return f"@{user.username} ({user.id})"
    return str(user.id)


async def start_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        t("feedback.prompt"), reply_markup=back_to_menu_keyboard()
    )
    return WAITING_TEXT


async def receive_feedback_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    admin_app = context.bot_data.get("admin_app")
    if not update.message or not update.effective_user:
        return WAITING_TEXT
    text = update.message.text or ""
    if not text.strip():
        await update.message.reply_text(t("feedback.prompt"))
        return WAITING_TEXT
    uid = update.effective_user.id
    fid = await db.insert_feedback(uid, text)
    await update.message.reply_text(
        t("feedback.saved"), reply_markup=main_menu_keyboard()
    )
    if admin_app and ADMIN_CHAT_ID:
        body = t(
            "feedback.admin_new",
            id=fid,
            user_ref=_user_ref(update.effective_user),
            text=text,
        )
        try:
            await admin_app.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=body,
                reply_markup=admin_reply_feedback_keyboard(fid),
            )
        except Exception:
            pass
    return ConversationHandler.END


async def cancel_fb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"), reply_markup=main_menu_keyboard()
        )
    return ConversationHandler.END


async def feedback_exit_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text(
            t("menu.welcome"), reply_markup=main_menu_keyboard()
        )
    return ConversationHandler.END


def register(app, admin_app) -> None:
    app.bot_data["admin_app"] = admin_app
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_feedback, pattern=r"^menu:feedback$")
        ],
        states={
            WAITING_TEXT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_feedback_text),
                CallbackQueryHandler(feedback_exit_main, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_fb)],
        name="feedback_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
