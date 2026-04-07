from datetime import datetime

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
from config import ADMIN_IDS, admin_only
from i18n import t

WAITING_REPLY = 1


def _fmt_short_dt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d.%m %H:%M")
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00")).strftime(
            "%d.%m %H:%M"
        )
    except ValueError:
        return str(val)[:11]


def _username_from_row(r: dict) -> str:
    u = r.get("username")
    if u:
        return f"@{u}"
    return str(r.get("user_id", ""))


@admin_only
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        t("admin.menu_welcome"), reply_markup=admin_main_keyboard()
    )


@admin_only
async def show_messages_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _send_unanswered_list(update, context, edit=False)


@admin_only
async def show_messages_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    await _send_unanswered_list(update, context, edit=True, query=q)


async def _send_unanswered_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> None:
    rows = await db.get_unanswered_feedback()
    if not rows:
        text = t("admin.no_unanswered")
        if edit and query:
            await query.edit_message_text(
                text, reply_markup=admin_main_keyboard()
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=admin_main_keyboard()
            )
        return

    chunks: list[tuple[str, list[list[InlineKeyboardButton]]]] = []
    current_text: list[str] = []
    current_kb: list[list[InlineKeyboardButton]] = []
    size = 0

    for r in rows:
        body = r.get("text") or ""
        short_body = body[:100] + ("…" if len(body) > 100 else "")
        block = f"#{r['id']} | {_username_from_row(r)} | {_fmt_short_dt(r.get('created_at'))}\n{short_body}"
        row_len = len(block) + 2
        if size + row_len > 3800 and current_text:
            chunks.append(("\n\n".join(current_text), current_kb))
            current_text = []
            current_kb = []
            size = 0
        current_text.append(block)
        current_kb.append(
            [
                InlineKeyboardButton(
                    text=f"{t('feedback.reply_button')} [{r['id']}]",
                    callback_data=f"adm:reply:{r['id']}",
                )
            ]
        )
        size += row_len

    if current_text:
        chunks.append(("\n\n".join(current_text), current_kb))

    first = True
    for text, kb_rows in chunks:
        markup = InlineKeyboardMarkup(kb_rows + [[InlineKeyboardButton(text=t("common.back"), callback_data="adm:home")]])
        if first:
            if edit and query:
                await query.edit_message_text(text, reply_markup=markup)
            elif update.message:
                await update.message.reply_text(text, reply_markup=markup)
            first = False
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text=text, reply_markup=markup
            )


@admin_only
async def adm_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        t("admin.menu_welcome"), reply_markup=admin_main_keyboard()
    )


async def begin_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    fid_s = (q.data or "").split(":")[-1]
    try:
        fid = int(fid_s)
    except ValueError:
        return ConversationHandler.END
    context.user_data["reply_fid"] = fid
    await q.edit_message_text(t("admin.reply_start", id=fid))
    return WAITING_REPLY


async def submit_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, student_app
) -> int:
    if not update.message or not update.message.text:
        return WAITING_REPLY
    text = update.message.text.strip()
    fid = context.user_data.get("reply_fid")
    if fid is None:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    row = await db.get_feedback_by_id(int(fid))
    if not row:
        await update.message.reply_text(t("faq.not_found"))
        context.user_data.pop("reply_fid", None)
        return ConversationHandler.END
    uid = int(row["user_id"])
    out = t("reply_to_student.prefix", text=text)
    try:
        await student_app.bot.send_message(chat_id=uid, text=out)
    except Exception:
        await update.message.reply_text(t("errors.generic"))
        context.user_data.pop("reply_fid", None)
        return ConversationHandler.END
    await db.mark_feedback_answered(int(fid))
    await update.message.reply_text(
        t("admin.reply_sent"), reply_markup=admin_main_keyboard()
    )
    context.user_data.pop("reply_fid", None)
    return ConversationHandler.END


async def cancel_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        return ConversationHandler.END
    context.user_data.pop("reply_fid", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


@admin_only
async def cmd_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE, student_app
) -> None:
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(t("admin.reply_cmd_usage"))
        return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_text(t("admin.reply_cmd_usage"))
        return
    body = " ".join(args[1:])
    out = t("reply_to_student.prefix", text=body)
    try:
        await student_app.bot.send_message(chat_id=uid, text=out)
    except Exception:
        await update.message.reply_text(t("errors.generic"))
        return
    await update.message.reply_text(t("admin.reply_sent"))


def register(app, student_app) -> None:
    async def submit_reply_wrap(u, c):
        eu = u.effective_user
        if not eu or eu.id not in ADMIN_IDS:
            return ConversationHandler.END
        return await submit_reply(u, c, student_app)

    async def cmd_reply_wrap(u, c):
        return await cmd_reply(u, c, student_app)

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(begin_reply, pattern=r"^adm:reply:\d+$")
        ],
        states={
            WAITING_REPLY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, submit_reply_wrap
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_reply)],
        name="admin_reply_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", admin_start))
    app.add_handler(CommandHandler("messages", show_messages_cmd))
    app.add_handler(CallbackQueryHandler(show_messages_cb, pattern=r"^adm:messages$"))
    app.add_handler(CallbackQueryHandler(adm_home, pattern=r"^adm:home$"))
    app.add_handler(conv)
    app.add_handler(CommandHandler("reply", cmd_reply_wrap))
