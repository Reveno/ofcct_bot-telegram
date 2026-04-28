import html

from telegram import Update
from telegram.ext import (
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

ADM_LIST, ADM_DETAIL = range(2)


async def _adm_end_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("adm_items", None)
    context.user_data.pop("adm_label_to_id", None)
    msg = update.effective_message
    if msg:
        await msg.reply_text(t("menu.welcome"), reply_markup=await main_menu_reply_keyboard())
    return ConversationHandler.END


async def _adm_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await db.is_menu_section_visible("admissions"):
        return ConversationHandler.END
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    rows = await db.get_all_admission_faq()
    if not rows:
        await msg.reply_text(t("admissions.empty"), reply_markup=await main_menu_reply_keyboard())
        return ConversationHandler.END
    items = []
    for r in rows:
        q = str(r.get("question") or "").strip()
        d = str(r.get("date_text") or "").strip()
        label = f"{q} ({d})" if d else q
        items.append((int(r["id"]), label))
    context.user_data["adm_items"] = items
    context.user_data["adm_label_to_id"] = {
        reply_indexed_label(i, title): fid
        for i, (fid, title) in enumerate(items, start=1)
    }
    await msg.reply_text(t("admissions.title"), reply_markup=faq_list_reply_keyboard(items))
    return ADM_LIST


async def _adm_list_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return ADM_LIST
    txt = update.message.text.strip()
    if txt in (t("common.back"), t("schedule.to_main_menu")):
        return await _adm_end_main(update, context)
    label_map = context.user_data.get("adm_label_to_id") or {}
    item_id = label_map.get(txt)
    if item_id is None:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return ADM_LIST
    row = await db.get_admission_faq_by_id(int(item_id))
    if not row:
        await update.message.reply_text(t("faq.not_found"), reply_markup=await main_menu_reply_keyboard())
        return ConversationHandler.END
    q_esc = html.escape(str(row.get("question") or ""))
    d_esc = html.escape(str(row.get("date_text") or ""))
    a_esc = html.escape(str(row.get("answer") or ""))
    header = f"<b>{q_esc}</b>"
    if d_esc:
        header += f"\n🗓 {d_esc}"
    await update.message.reply_text(
        f"{header}\n\n{a_esc}",
        parse_mode="HTML",
        reply_markup=faq_answer_reply_keyboard(),
    )
    return ADM_DETAIL


async def _adm_detail_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return ADM_DETAIL
    txt = update.message.text.strip()
    if txt == t("faq.back_to_questions"):
        items = context.user_data.get("adm_items") or []
        await update.message.reply_text(
            t("admissions.title"), reply_markup=faq_list_reply_keyboard(items)
        )
        return ADM_LIST
    if txt in (t("common.back"), t("schedule.to_main_menu")):
        return await _adm_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return ADM_DETAIL


async def _adm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    context.user_data.pop("adm_items", None)
    context.user_data.pop("adm_label_to_id", None)
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.admissions")),
                _adm_open,
            ),
        ],
        states={
            ADM_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, _adm_list_text)],
            ADM_DETAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, _adm_detail_text)],
        },
        fallbacks=[CommandHandler("cancel", _adm_cancel)],
        name="admissions_student_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
