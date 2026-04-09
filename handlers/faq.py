import html

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

import db
from i18n import t
from keyboards import (
    back_to_menu_keyboard,
    faq_list_keyboard,
    main_menu_text_pattern,
)


async def open_faq_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    rows = await db.get_all_faq()
    if not rows:
        await q.edit_message_text(
            t("faq.title") + "\n\n" + t("schedule.empty"),
            reply_markup=back_to_menu_keyboard(),
        )
        return
    items = [(int(r["id"]), r["question"]) for r in rows]
    await q.edit_message_text(
        t("faq.title"), reply_markup=faq_list_keyboard(items)
    )


async def open_faq_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    rows = await db.get_all_faq()
    if not rows:
        await update.message.reply_text(
            t("faq.title") + "\n\n" + t("schedule.empty"),
            reply_markup=back_to_menu_keyboard(),
        )
        return
    items = [(int(r["id"]), r["question"]) for r in rows]
    await update.message.reply_text(
        t("faq.title"), reply_markup=faq_list_keyboard(items)
    )


async def show_faq_item(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q:
        return
    await q.answer()
    fid_s = (q.data or "").split(":", 1)[-1]
    try:
        fid = int(fid_s)
    except ValueError:
        await q.edit_message_text(
            t("faq.not_found"), reply_markup=back_to_menu_keyboard()
        )
        return
    row = await db.get_faq_by_id(fid)
    if not row:
        await q.edit_message_text(
            t("faq.not_found"), reply_markup=back_to_menu_keyboard()
        )
        return
    q_esc = html.escape(str(row.get("question") or ""))
    a_esc = html.escape(str(row.get("answer") or ""))
    text = f"<b>{q_esc}</b>\n\n{a_esc}"
    await q.edit_message_text(
        text,
        reply_markup=back_to_menu_keyboard(),
        parse_mode="HTML",
    )


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_faq_cb, pattern=r"^menu:faq$"))
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(main_menu_text_pattern("menu.faq")),
            open_faq_from_message,
        )
    )
    app.add_handler(
        CallbackQueryHandler(show_faq_item, pattern=r"^faq:\d+$")
    )
