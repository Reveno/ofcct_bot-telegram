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
    all_main_menu_button_texts,
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    schedule_groups_reply_keyboard,
    subscription_reply_keyboard,
)

SUB_STATE = 1
SUB_GROUP = 2


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


def _pick_group_label() -> str:
    return t("subscription.pick_group_btn")


def _clear_group_label() -> str:
    return t("subscription.clear_group_btn")


async def _sub_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _sub_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("subscription"):
        return ConversationHandler.END
    q = update.callback_query
    if q:
        await q.answer()

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    row = await db.get_user(user.id)
    sub = bool(row and row.get("subscribed"))
    pg = (row or {}).get("preferred_group")
    if isinstance(pg, str):
        pg = pg.strip() or None
    else:
        pg = None
    status = t("subscription.status_on") if sub else t("subscription.status_off")
    hint = ""
    if pg:
        hint = "\n\n" + t("subscription.group_current", group=pg)
    body = status + hint

    if update.message:
        await update.message.reply_text(
            body,
            reply_markup=subscription_reply_keyboard(sub, preferred_group=pg),
        )
    elif q and q.message:
        await q.message.reply_text(
            body,
            reply_markup=subscription_reply_keyboard(sub, preferred_group=pg),
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

    row = await db.get_user(user.id)
    sub = bool(row and row.get("subscribed"))
    pg = (row or {}).get("preferred_group")
    if isinstance(pg, str):
        pg = pg.strip() or None
    else:
        pg = None

    if text == _pick_group_label():
        groups = await db.get_all_groups()
        if not groups:
            await update.message.reply_text(
                t("schedule.no_groups"),
                reply_markup=subscription_reply_keyboard(sub, preferred_group=pg),
            )
            return SUB_STATE
        await update.message.reply_text(
            t("subscription.choose_group_title"),
            reply_markup=schedule_groups_reply_keyboard(groups),
        )
        return SUB_GROUP

    if text == _clear_group_label():
        await db.set_user_preferred_group(user.id, None)
        row2 = await db.get_user(user.id)
        sub2 = bool(row2 and row2.get("subscribed"))
        await update.message.reply_text(
            t("subscription.group_cleared"),
            reply_markup=subscription_reply_keyboard(sub2, preferred_group=None),
        )
        return SUB_STATE

    sub_on = t("subscription.subscribe")
    sub_off = t("subscription.unsubscribe")
    if text not in (sub_on, sub_off):
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SUB_STATE

    current = bool(row and row.get("subscribed"))
    if (text == sub_on and current) or (text == sub_off and not current):
        status = (
            t("subscription.status_on") if current else t("subscription.status_off")
        )
        hint = ""
        if pg:
            hint = "\n\n" + t("subscription.group_current", group=pg)
        await update.message.reply_text(
            status + hint,
            reply_markup=subscription_reply_keyboard(current, preferred_group=pg),
        )
        return SUB_STATE

    new_state = await db.toggle_subscription(user.id)
    row3 = await db.get_user(user.id)
    pg3 = (row3 or {}).get("preferred_group")
    if isinstance(pg3, str):
        pg3 = pg3.strip() or None
    else:
        pg3 = None
    status = (
        t("subscription.status_on") if new_state else t("subscription.status_off")
    )
    hint = (
        t("subscription.toggled_on") if new_state else t("subscription.toggled_off")
    )
    gh = ""
    if pg3:
        gh = "\n\n" + t("subscription.group_current", group=pg3)
    await update.message.reply_text(
        f"{status}\n\n{hint}{gh}",
        reply_markup=subscription_reply_keyboard(new_state, preferred_group=pg3),
    )
    return SUB_STATE


async def _sub_group_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SUB_GROUP
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _sub_open(update, context)

    user = update.effective_user
    if not user:
        return ConversationHandler.END

    stripped = text
    if stripped in all_main_menu_button_texts():
        await update.message.reply_text(
            t("menu.welcome"),
            reply_markup=await main_menu_reply_keyboard(),
        )
        return ConversationHandler.END

    groups = await db.get_all_groups()
    if text not in groups:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SUB_GROUP

    await db.set_user_preferred_group(user.id, text)
    row = await db.get_user(user.id)
    sub = bool(row and row.get("subscribed"))
    await update.message.reply_text(
        t("subscription.group_picked", group=text),
        reply_markup=subscription_reply_keyboard(sub, preferred_group=text),
    )
    return SUB_STATE


async def _sub_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=await main_menu_reply_keyboard(),
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
            reply_markup=await main_menu_reply_keyboard(),
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
            SUB_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _sub_group_text),
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
