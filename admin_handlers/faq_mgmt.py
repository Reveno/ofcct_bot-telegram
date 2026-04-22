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

ADD_Q, ADD_A, ADD_FILE, EDIT_Q, EDIT_A, EDIT_FILE = range(6)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


async def _faq_menu_payload() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.get_all_faq()
    lines = [t("admin.faq_menu_title")]
    kb_rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t("admin.faq_add_btn"), callback_data="adm:faq_add"
            )
        ]
    ]
    for r in rows:
        fid = int(r["id"])
        qtext = (r.get("question") or "").strip()
        short = qtext if len(qtext) <= 28 else qtext[:25] + "…"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {short}",
                    callback_data=f"adm:faq_e:{fid}",
                ),
                InlineKeyboardButton(
                    text="🗑", callback_data=f"adm:faq_d:{fid}"
                ),
            ]
        )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text=t("common.back"), callback_data="adm:home"
            )
        ]
    )
    return "\n\n".join(lines), InlineKeyboardMarkup(kb_rows)


async def _render_faq_panel(q) -> None:
    text, kb = await _faq_menu_payload()
    await q.edit_message_text(text, reply_markup=kb)


async def faq_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not update.message or not _ok(user.id if user else None):
        if update.message and user and user.id not in ADMIN_IDS:
            await update.message.reply_text(t("admin.access_denied"))
        return
    text, kb = await _faq_menu_payload()
    await update.message.reply_text(text, reply_markup=kb)


async def faq_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await _render_faq_panel(q)
    return ConversationHandler.END


async def faq_add_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await q.edit_message_text(t("admin.faq_add_start"))
    return ADD_Q


async def faq_add_receive_q(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ADD_Q
    context.user_data["faq_new_q"] = update.message.text.strip()
    await update.message.reply_text(t("admin.faq_add_answer"))
    return ADD_A


async def faq_add_receive_a(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ADD_A
    q = context.user_data.get("faq_new_q") or ""
    a = update.message.text.strip()
    if not q or not a:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    context.user_data["faq_new_a"] = a
    await update.message.reply_text(t("admin.faq_add_file"))
    return ADD_FILE


async def faq_add_receive_a_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.document:
        return ADD_A
    q = context.user_data.get("faq_new_q") or ""
    a = (update.message.caption or "").strip()
    if not q or not a:
        await update.message.reply_text(t("admin.faq_add_answer"))
        return ADD_A
    oi = await db.get_next_faq_order_index()
    await db.insert_faq(
        q,
        a,
        oi,
        file_id=update.message.document.file_id,
        file_name=update.message.document.file_name,
    )
    context.user_data.pop("faq_new_q", None)
    context.user_data.pop("faq_new_a", None)
    await update.message.reply_text(
        t("admin.faq_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def faq_add_receive_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message:
        return ADD_FILE
    q = context.user_data.get("faq_new_q") or ""
    a = context.user_data.get("faq_new_a") or ""
    if not q or not a:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    file_id: str | None = None
    file_name: str | None = None
    if update.message.document:
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name
    elif update.message.text:
        cmd = update.message.text.strip().lower()
        if cmd == "/skip":
            pass
        elif cmd == "/cancel":
            return await faq_cancel(update, context)
        else:
            await update.message.reply_text(t("admin.faq_add_file_invalid"))
            return ADD_FILE
    else:
        await update.message.reply_text(t("admin.faq_add_file_invalid"))
        return ADD_FILE
    oi = await db.get_next_faq_order_index()
    await db.insert_faq(q, a, oi, file_id=file_id, file_name=file_name)
    context.user_data.pop("faq_new_q", None)
    context.user_data.pop("faq_new_a", None)
    await update.message.reply_text(
        t("admin.faq_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def faq_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    m = re.match(r"^adm:faq_e:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return ConversationHandler.END
    fid = int(m.group(1))
    row = await db.get_faq_by_id(fid)
    if not row:
        await q.answer()
        return ConversationHandler.END
    await q.answer()
    context.user_data["faq_edit_id"] = fid
    await q.edit_message_text(
        t("admin.faq_edit_question", q=row.get("question", ""))
    )
    return EDIT_Q


async def faq_edit_receive_q(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return EDIT_Q
    txt = update.message.text.strip()
    if txt.lower() != "/skip":
        context.user_data["faq_new_q"] = txt
    else:
        context.user_data.pop("faq_new_q", None)
    fid = int(context.user_data.get("faq_edit_id") or 0)
    row = await db.get_faq_by_id(fid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    await update.message.reply_text(
        t("admin.faq_edit_answer", a=row.get("answer", ""))
    )
    return EDIT_A


async def faq_edit_receive_a(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return EDIT_A
    txt = update.message.text.strip()
    fid = int(context.user_data.get("faq_edit_id") or 0)
    row = await db.get_faq_by_id(fid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    new_q = (
        context.user_data["faq_new_q"]
        if "faq_new_q" in context.user_data
        else row.get("question")
    )
    if txt.lower() != "/skip":
        new_a = txt
    else:
        new_a = row.get("answer")
    context.user_data["faq_new_a"] = str(new_a or "")
    current_file_name = str(row.get("file_name") or "").strip()
    await update.message.reply_text(
        t(
            "admin.faq_edit_file",
            file_name=current_file_name if current_file_name else t("admin.faq_no_file"),
        )
    )
    return EDIT_FILE


async def faq_edit_receive_a_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.document:
        return EDIT_A
    fid = int(context.user_data.get("faq_edit_id") or 0)
    row = await db.get_faq_by_id(fid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    new_q = (
        context.user_data["faq_new_q"]
        if "faq_new_q" in context.user_data
        else row.get("question")
    )
    caption = (update.message.caption or "").strip()
    new_a = caption if caption else row.get("answer")
    await db.update_faq(
        fid,
        question=str(new_q),
        answer=str(new_a or ""),
        file_id=update.message.document.file_id,
        file_name=str(update.message.document.file_name or ""),
    )
    context.user_data.pop("faq_edit_id", None)
    context.user_data.pop("faq_new_q", None)
    context.user_data.pop("faq_new_a", None)
    await update.message.reply_text(
        t("admin.faq_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def faq_edit_receive_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message:
        return EDIT_FILE
    fid = int(context.user_data.get("faq_edit_id") or 0)
    row = await db.get_faq_by_id(fid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END

    new_q = (
        context.user_data["faq_new_q"]
        if "faq_new_q" in context.user_data
        else row.get("question")
    )
    new_a = context.user_data.get("faq_new_a", row.get("answer"))

    new_file_id = row.get("file_id")
    new_file_name = row.get("file_name")
    if update.message.document:
        new_file_id = update.message.document.file_id
        new_file_name = update.message.document.file_name
    elif update.message.text:
        cmd = update.message.text.strip().lower()
        if cmd == "/skip":
            pass
        elif cmd == "/remove":
            new_file_id = ""
            new_file_name = ""
        elif cmd == "/cancel":
            return await faq_cancel(update, context)
        else:
            await update.message.reply_text(t("admin.faq_add_file_invalid"))
            return EDIT_FILE
    else:
        await update.message.reply_text(t("admin.faq_add_file_invalid"))
        return EDIT_FILE

    await db.update_faq(
        fid,
        question=str(new_q),
        answer=str(new_a or ""),
        file_id=str(new_file_id or ""),
        file_name=str(new_file_name or ""),
    )
    context.user_data.pop("faq_edit_id", None)
    context.user_data.pop("faq_new_q", None)
    context.user_data.pop("faq_new_a", None)
    await update.message.reply_text(
        t("admin.faq_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def faq_delete_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:faq_d:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    fid = int(m.group(1))
    await q.answer()
    await db.delete_faq(fid)
    await _render_faq_panel(q)


async def faq_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("faq_new_q", None)
    context.user_data.pop("faq_new_a", None)
    context.user_data.pop("faq_edit_id", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(faq_add_start, pattern=r"^adm:faq_add$"),
            CallbackQueryHandler(faq_edit_start, pattern=r"^adm:faq_e:\d+$"),
        ],
        states={
            ADD_Q: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, faq_add_receive_q
                )
            ],
            ADD_A: [
                MessageHandler(filters.Document.ALL, faq_add_receive_a_doc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, faq_add_receive_a),
            ],
            ADD_FILE: [
                MessageHandler(
                    (filters.TEXT | filters.Document.ALL), faq_add_receive_file
                )
            ],
            EDIT_Q: [
                MessageHandler(
                    filters.TEXT, faq_edit_receive_q
                )
            ],
            EDIT_A: [
                MessageHandler(filters.Document.ALL, faq_edit_receive_a_doc),
                MessageHandler(filters.TEXT, faq_edit_receive_a),
            ],
            EDIT_FILE: [
                MessageHandler(
                    (filters.TEXT | filters.Document.ALL), faq_edit_receive_file
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", faq_cancel)],
        name="faq_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(CallbackQueryHandler(faq_menu_cb, pattern=r"^adm:faq$"))
    app.add_handler(CallbackQueryHandler(faq_delete_cb, pattern=r"^adm:faq_d:\d+$"))
    app.add_handler(conv)
