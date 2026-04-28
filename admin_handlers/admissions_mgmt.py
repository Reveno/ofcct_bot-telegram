import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from admin_keyboards import admin_main_keyboard
from config import ADMIN_IDS
from i18n import t

ADD_Q, ADD_A, ADD_D, EDIT_Q, EDIT_A, EDIT_D = range(6)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


async def _payload() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.get_all_admission_faq()
    kb_rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(t("admin.faq_add_btn"), callback_data="adm:ad_add")]
    ]
    for r in rows:
        rid = int(r["id"])
        q = str(r.get("question") or "").strip()
        short = q if len(q) <= 28 else q[:25] + "…"
        kb_rows.append(
            [
                InlineKeyboardButton(f"✏️ {short}", callback_data=f"adm:ad_e:{rid}"),
                InlineKeyboardButton("🗑", callback_data=f"adm:ad_d:{rid}"),
            ]
        )
    kb_rows.append([InlineKeyboardButton(t("common.back"), callback_data="adm:sections")])
    return t("admin.admissions_panel_title"), InlineKeyboardMarkup(kb_rows)


async def _render(q) -> None:
    text, kb = await _payload()
    await q.edit_message_text(text, reply_markup=kb)


async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    u = update.effective_user
    if not q:
        return ConversationHandler.END
    if not _ok(u.id if u else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await _render(q)
    return ConversationHandler.END


async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()
    await q.edit_message_text(t("admin.faq_add_start"))
    return ADD_Q


async def add_q(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return ADD_Q
    context.user_data["ad_q"] = update.message.text.strip()
    await update.message.reply_text(t("admin.faq_add_answer"))
    return ADD_A


async def add_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return ADD_A
    context.user_data["ad_a"] = update.message.text.strip()
    await update.message.reply_text(t("admin.admissions_ask_date"))
    return ADD_D


async def add_d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return ADD_D
    q = str(context.user_data.get("ad_q") or "").strip()
    a = str(context.user_data.get("ad_a") or "").strip()
    d = update.message.text.strip()
    if not q or not a:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    oi = await db.get_next_admission_order_index()
    await db.insert_admission_faq(q, a, "" if d.lower() == "/skip" else d, oi)
    context.user_data.pop("ad_q", None)
    context.user_data.pop("ad_a", None)
    await update.message.reply_text(t("admin.faq_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    m = re.match(r"^adm:ad_e:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return ConversationHandler.END
    rid = int(m.group(1))
    row = await db.get_admission_faq_by_id(rid)
    if not row:
        await q.answer()
        return ConversationHandler.END
    context.user_data["ad_id"] = rid
    await q.answer()
    await q.edit_message_text(t("admin.faq_edit_question", q=row.get("question", "")))
    return EDIT_Q


async def edit_q(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return EDIT_Q
    txt = update.message.text.strip()
    if txt.lower() != "/skip":
        context.user_data["ad_q"] = txt
    await update.message.reply_text(t("admin.faq_edit_answer", a="..."))
    return EDIT_A


async def edit_a(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return EDIT_A
    txt = update.message.text.strip()
    if txt.lower() != "/skip":
        context.user_data["ad_a"] = txt
    await update.message.reply_text(t("admin.admissions_ask_date_edit"))
    return EDIT_D


async def edit_d(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return EDIT_D
    rid = int(context.user_data.get("ad_id") or 0)
    row = await db.get_admission_faq_by_id(rid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    txt = update.message.text.strip()
    new_q = context.user_data.get("ad_q", row.get("question"))
    new_a = context.user_data.get("ad_a", row.get("answer"))
    new_d = row.get("date_text")
    if txt.lower() != "/skip":
        new_d = "" if txt == "-" else txt
    await db.update_admission_faq(
        rid,
        question=str(new_q or ""),
        answer=str(new_a or ""),
        date_text=str(new_d or ""),
    )
    context.user_data.pop("ad_id", None)
    context.user_data.pop("ad_q", None)
    context.user_data.pop("ad_a", None)
    await update.message.reply_text(t("admin.faq_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def del_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    m = re.match(r"^adm:ad_d:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await db.delete_admission_faq(int(m.group(1)))
    await q.answer(t("admin.faq_deleted"))
    await _render(q)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("ad_id", None)
    context.user_data.pop("ad_q", None)
    context.user_data.pop("ad_a", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_start, pattern=r"^adm:ad_add$"),
            CallbackQueryHandler(edit_start, pattern=r"^adm:ad_e:\d+$"),
        ],
        states={
            ADD_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_q)],
            ADD_A: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_a)],
            ADD_D: [MessageHandler(filters.TEXT, add_d)],
            EDIT_Q: [MessageHandler(filters.TEXT, edit_q)],
            EDIT_A: [MessageHandler(filters.TEXT, edit_a)],
            EDIT_D: [MessageHandler(filters.TEXT, edit_d)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="admissions_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(CallbackQueryHandler(menu_cb, pattern=r"^adm:admissions$"))
    app.add_handler(CallbackQueryHandler(del_cb, pattern=r"^adm:ad_d:\d+$"))
    app.add_handler(conv)
