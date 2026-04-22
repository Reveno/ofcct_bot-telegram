import html

from telegram import Update
from telegram.error import BadRequest
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
    faq_answer_reply_keyboard,
    faq_list_reply_keyboard,
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    reply_indexed_label,
)

FAQ_LIST, FAQ_DETAIL = range(2)


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _faq_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("faq_items", None)
    context.user_data.pop("faq_label_to_id", None)
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _faq_open_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()

    context.user_data.pop("faq_items", None)
    context.user_data.pop("faq_label_to_id", None)

    rows = await db.get_all_faq()
    if not rows:
        text = t("faq.title") + "\n\n" + t("schedule.empty")
        if update.message:
            await update.message.reply_text(
                text,
                reply_markup=main_menu_reply_keyboard(),
            )
        elif q and q.message:
            await q.message.reply_text(
                text,
                reply_markup=main_menu_reply_keyboard(),
            )
        return ConversationHandler.END

    items = [(int(r["id"]), r["question"]) for r in rows]
    context.user_data["faq_items"] = items
    label_to_id = {
        reply_indexed_label(i, q): fid
        for i, (fid, q) in enumerate(items, start=1)
    }
    context.user_data["faq_label_to_id"] = label_to_id

    title = t("faq.title")
    kb = faq_list_reply_keyboard(items)
    if update.message:
        await update.message.reply_text(title, reply_markup=kb)
    elif q and q.message:
        await q.message.reply_text(title, reply_markup=kb)
    else:
        return ConversationHandler.END
    return FAQ_LIST


async def _faq_list_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return FAQ_LIST
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _faq_end_main(update, context)

    label_to_id = context.user_data.get("faq_label_to_id") or {}
    fid = label_to_id.get(text)
    if fid is None:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return FAQ_LIST

    row = await db.get_faq_by_id(int(fid))
    if not row:
        await update.message.reply_text(
            t("faq.not_found"),
            reply_markup=main_menu_reply_keyboard(),
        )
        return ConversationHandler.END

    q_esc = html.escape(str(row.get("question") or ""))
    a_esc = html.escape(str(row.get("answer") or ""))
    body = f"<b>{q_esc}</b>\n\n{a_esc}"
    await update.message.reply_text(
        body,
        reply_markup=faq_answer_reply_keyboard(),
        parse_mode="HTML",
    )
    file_id = str(row.get("file_id") or "").strip()
    if file_id:
        try:
            await update.message.reply_document(document=file_id)
        except BadRequest:
            pass
    return FAQ_DETAIL


async def _faq_detail_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return FAQ_DETAIL
    text = update.message.text.strip()
    if text == t("faq.back_to_questions"):
        items = context.user_data.get("faq_items")
        if not items:
            return await _faq_end_main(update, context)
        await update.message.reply_text(
            t("faq.title"),
            reply_markup=faq_list_reply_keyboard(items),
        )
        return FAQ_LIST
    if text in (_back_label(), _menu_label()):
        return await _faq_end_main(update, context)

    await update.message.reply_text(t("schedule.use_keyboard"))
    return FAQ_DETAIL


async def _faq_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    context.user_data.pop("faq_items", None)
    context.user_data.pop("faq_label_to_id", None)
    return ConversationHandler.END


async def _faq_main_cb(
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
    context.user_data.pop("faq_items", None)
    context.user_data.pop("faq_label_to_id", None)
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_faq_open_list, pattern=r"^menu:faq$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.faq")),
                _faq_open_list,
            ),
        ],
        states={
            FAQ_LIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _faq_list_text),
                CallbackQueryHandler(_faq_main_cb, pattern=r"^menu:main$"),
            ],
            FAQ_DETAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _faq_detail_text),
                CallbackQueryHandler(_faq_main_cb, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _faq_cancel)],
        name="faq_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
