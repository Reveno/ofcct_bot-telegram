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
from keyboards import (
    all_main_menu_button_texts,
    main_menu_reply_keyboard,
    main_menu_text_pattern,
)

WAITING_TEXT = 1


def _user_ref(user) -> str:
    if user.username:
        return f"@{user.username} ({user.id})"
    return str(user.id)


async def start_feedback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    msg = update.message
    if q:
        await q.answer()
        await q.edit_message_text(t("feedback.prompt"))
    elif msg:
        await msg.reply_text(t("feedback.prompt"))
    else:
        return ConversationHandler.END
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
    stripped = text.strip()
    if stripped in all_main_menu_button_texts():
        await update.message.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
        return ConversationHandler.END
    uid = update.effective_user.id
    remain = await db.get_feedback_cooldown_remaining_sec(uid)
    if remain > 0:
        minutes = max(1, (remain + 59) // 60)
        await update.message.reply_text(
            t("feedback.rate_limited", minutes=minutes),
            reply_markup=main_menu_reply_keyboard(),
        )
        return WAITING_TEXT
    fid = await db.insert_feedback(uid, text)
    await db.touch_user_last_feedback(uid)
    await update.message.reply_text(
        t("feedback.saved"),
        reply_markup=main_menu_reply_keyboard(),
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
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def feedback_exit_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q and q.message:
        await q.answer()
        try:
            await q.edit_message_text(t("menu.welcome"))
        except Exception:
            pass
        await q.message.reply_text(
            t("menu.reply_menu_visible"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


def register(app, admin_app) -> None:
    app.bot_data["admin_app"] = admin_app
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_feedback, pattern=r"^menu:feedback$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.feedback")),
                start_feedback,
            ),
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
