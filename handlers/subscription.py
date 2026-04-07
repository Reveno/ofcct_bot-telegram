from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import subscription_keyboard


async def open_subscription(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    if not user:
        return
    row = await db.get_user(user.id)
    sub = bool(row and row.get("subscribed"))
    status = t("subscription.status_on") if sub else t("subscription.status_off")
    text = status
    await q.edit_message_text(
        text, reply_markup=subscription_keyboard(sub)
    )


async def toggle_subscription_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    user = update.effective_user
    if not user:
        return
    new_state = await db.toggle_subscription(user.id)
    status = (
        t("subscription.status_on") if new_state else t("subscription.status_off")
    )
    hint = (
        t("subscription.toggled_on") if new_state else t("subscription.toggled_off")
    )
    text = f"{status}\n\n{hint}"
    await q.edit_message_text(
        text, reply_markup=subscription_keyboard(new_state)
    )


def register(app) -> None:
    app.add_handler(
        CallbackQueryHandler(open_subscription, pattern=r"^menu:subscription$")
    )
    app.add_handler(
        CallbackQueryHandler(toggle_subscription_cb, pattern=r"^sub:toggle$")
    )
