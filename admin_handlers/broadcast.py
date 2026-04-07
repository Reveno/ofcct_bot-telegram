from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from admin_keyboards import admin_main_keyboard, broadcast_confirm_keyboard
from config import ADMIN_IDS
from i18n import t

WAIT_TEXT, CONFIRM = range(2)


async def broadcast_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(t("admin.broadcast_start"))
    return WAIT_TEXT


async def broadcast_cmd_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    args = context.args or []
    if args:
        text = " ".join(args).strip()
        context.user_data["bc_text"] = text
        subs = await db.get_all_subscribers()
        context.user_data["bc_subs"] = subs
        preview = t(
            "admin.broadcast_preview",
            text=text,
            count=len(subs),
        )
        await update.message.reply_text(
            preview, reply_markup=broadcast_confirm_keyboard()
        )
        return CONFIRM
    await update.message.reply_text(t("admin.broadcast_start"))
    return WAIT_TEXT


async def broadcast_receive_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return ConversationHandler.END
    if not update.message or not update.message.text:
        return WAIT_TEXT
    text = update.message.text.strip()
    context.user_data["bc_text"] = text
    subs = await db.get_all_subscribers()
    context.user_data["bc_subs"] = subs
    preview = t(
        "admin.broadcast_preview",
        text=text,
        count=len(subs),
    )
    await update.message.reply_text(
        preview, reply_markup=broadcast_confirm_keyboard()
    )
    return CONFIRM


async def broadcast_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE, student_app
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "bc:no":
        await q.edit_message_text(
            t("admin.upload_cancelled"), reply_markup=admin_main_keyboard()
        )
        context.user_data.pop("bc_text", None)
        context.user_data.pop("bc_subs", None)
        return ConversationHandler.END
    text = context.user_data.get("bc_text") or ""
    subs = context.user_data.get("bc_subs") or []
    if not text:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END
    if not subs:
        await q.edit_message_text(
            t("admin.broadcast_empty_subscribers"),
            reply_markup=admin_main_keyboard(),
        )
        context.user_data.pop("bc_text", None)
        context.user_data.pop("bc_subs", None)
        return ConversationHandler.END
    ok = 0
    errors = 0
    for row in subs:
        uid = int(row["user_id"])
        try:
            await student_app.bot.send_message(chat_id=uid, text=text)
            ok += 1
        except TelegramError:
            errors += 1
    await db.insert_broadcast(text, user.id)
    report = t(
        "admin.broadcast_sent",
        ok=ok,
        total=len(subs),
        errors=errors,
    )
    await q.edit_message_text(report, reply_markup=admin_main_keyboard())
    context.user_data.pop("bc_text", None)
    context.user_data.pop("bc_subs", None)
    return ConversationHandler.END


async def broadcast_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return ConversationHandler.END
    context.user_data.pop("bc_text", None)
    context.user_data.pop("bc_subs", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app, student_app) -> None:
    async def confirm_wrap(u, c):
        return await broadcast_confirm(u, c, student_app)

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", broadcast_cmd_entry),
            CallbackQueryHandler(broadcast_menu_cb, pattern=r"^adm:broadcast$"),
        ],
        states={
            WAIT_TEXT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, broadcast_receive_text
                )
            ],
            CONFIRM: [CallbackQueryHandler(confirm_wrap, pattern=r"^bc:(yes|no)$")],
        },
        fallbacks=[CommandHandler("cancel", broadcast_cancel)],
        name="broadcast_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
