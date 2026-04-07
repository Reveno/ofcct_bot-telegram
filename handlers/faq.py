from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import back_to_menu_keyboard, faq_list_keyboard


async def open_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    rows = await db.get_all_faq()
    if not rows:
        await q.edit_message_text(
            t("faq.title") + "\n\n" + t("schedule.empty"),
            reply_markup=back_to_menu_keyboard(),
        )
        return
    items = [(r["id"], r["question"]) for r in rows]
    await q.edit_message_text(
        t("faq.title"), reply_markup=faq_list_keyboard(items)
    )


async def show_faq_item(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
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
    text = f"<b>{row['question']}</b>\n\n{row['answer']}"
    await q.edit_message_text(
        text,
        reply_markup=back_to_menu_keyboard(),
        parse_mode="HTML",
    )


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_faq, pattern=r"^menu:faq$"))
    app.add_handler(CallbackQueryHandler(show_faq_item, pattern=r"^faq:\d+$"))
