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
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    subscription_reply_keyboard,
)

SUB_STATE = 1


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _sub_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _sub_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    row = await db.get_user(user.id)
    sub = bool(row and row.get("subscribed"))
    status = t("subscription.status_on") if sub else t("subscription.status_off")

    if update.message:
        await update.message.reply_text(
            status,
            reply_markup=subscription_reply_keyboard(sub),
        )
    elif q and q.message:
        await q.message.reply_text(
            status,
            reply_markup=subscription_reply_keyboard(sub),
        )
    else:
        return ConversationHandler.END
    return SUB_STATE


async def _sub_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SUB_STATE
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _sub_end_main(update, context)

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    sub_on = t("subscription.subscribe")
    sub_off = t("subscription.unsubscribe")
    if text not in (sub_on, sub_off):
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SUB_STATE

    row = await db.get_user(user.id)
    current = bool(row and row.get("subscribed"))
    if (text == sub_on and current) or (text == sub_off and not current):
        status = (
            t("subscription.status_on") if current else t("subscription.status_off")
        )
        await update.message.reply_text(
            status,
            reply_markup=subscription_reply_keyboard(current),
        )
        return SUB_STATE

    new_state = await db.toggle_subscription(user.id)
    status = (
        t("subscription.status_on") if new_state else t("subscription.status_off")
    )
    hint = (
        t("subscription.toggled_on") if new_state else t("subscription.toggled_off")
    )
    await update.message.reply_text(
        f"{status}\n\n{hint}",
        reply_markup=subscription_reply_keyboard(new_state),
    )
    return SUB_STATE


async def _sub_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _sub_main_cb(
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


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_sub_open, pattern=r"^menu:subscription$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(
                    main_menu_text_pattern("menu.subscription")
                ),
                _sub_open,
            ),
        ],
        states={
            SUB_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _sub_text),
                CallbackQueryHandler(_sub_main_cb, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _sub_cancel)],
        name="subscription_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
