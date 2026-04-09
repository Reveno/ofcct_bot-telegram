from telegram import ReplyKeyboardRemove, Update
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
    back_to_menu_keyboard,
    faq_button_label,
    faq_reply_keyboard,
    main_menu_keyboard,
)

WAITING_SELECTION = 1


async def _faq_remove_keyboard(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int
) -> None:
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="\u2060",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception:
        pass


async def faq_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q or not q.message:
        return ConversationHandler.END
    await q.answer()
    rows = await db.get_all_faq()
    if not rows:
        await q.edit_message_text(
            t("faq.title") + "\n\n" + t("schedule.empty"),
            reply_markup=back_to_menu_keyboard(),
        )
        return ConversationHandler.END
    choice_map: dict[str, int] = {}
    labels: list[str] = []
    for i, r in enumerate(rows):
        qtext = r["question"]
        label = faq_button_label(qtext, i)
        choice_map[label] = int(r["id"])
        labels.append(label)
    context.user_data["faq_choice_map"] = choice_map
    await q.edit_message_text(
        t("faq.title"),
        reply_markup=back_to_menu_keyboard(),
    )
    await q.message.reply_text(
        t("faq.reply_hint"),
        reply_markup=faq_reply_keyboard(labels),
    )
    return WAITING_SELECTION


async def faq_pick_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return WAITING_SELECTION
    raw = update.message.text.strip()
    if raw == t("faq.reply_back_to_menu"):
        await _faq_remove_keyboard(context, update.effective_chat.id)
        await update.message.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_keyboard(),
        )
        context.user_data.pop("faq_choice_map", None)
        return ConversationHandler.END
    cmap = context.user_data.get("faq_choice_map") or {}
    fid = cmap.get(raw)
    if fid is None:
        await update.message.reply_text(t("faq.not_found"))
        return WAITING_SELECTION
    row = await db.get_faq_by_id(int(fid))
    if not row:
        await update.message.reply_text(t("faq.not_found"))
        return WAITING_SELECTION
    q_esc = str(row["question"]).replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    )
    a_esc = str(row["answer"]).replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;"
    )
    text = f"<b>{q_esc}</b>\n\n{a_esc}"
    await update.message.reply_text(text, parse_mode="HTML")
    return WAITING_SELECTION


async def faq_exit_via_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q and q.message:
        await q.answer()
        await q.edit_message_text(
            t("menu.welcome"),
            reply_markup=main_menu_keyboard(),
        )
        await _faq_remove_keyboard(context, q.message.chat_id)
    context.user_data.pop("faq_choice_map", None)
    return ConversationHandler.END


async def faq_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await _faq_remove_keyboard(context, update.message.chat_id)
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_keyboard(),
        )
    context.user_data.pop("faq_choice_map", None)
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(faq_start, pattern=r"^menu:faq$"),
        ],
        states={
            WAITING_SELECTION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, faq_pick_text
                ),
                CallbackQueryHandler(
                    faq_exit_via_main, pattern=r"^menu:main$"
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", faq_cancel)],
        name="faq_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
