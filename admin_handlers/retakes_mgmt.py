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
from admin_keyboards import admin_main_keyboard, retake_delete_keyboard
from config import ADMIN_IDS, admin_only
from i18n import t

R_TEACHER, R_SUBJECT, R_DATE, R_TIME, R_ROOM, R_NOTES, R_CONFIRM = range(7)


def _retake_block(data: dict) -> str:
    notes = data.get("notes") or t("retakes.notes_empty")
    return t(
        "retakes.entry",
        date=data.get("date", ""),
        time=data.get("time", ""),
        room=data.get("room", ""),
        subject=data.get("subject", ""),
        teacher=data.get("teacher", ""),
        notes=notes,
    )


@admin_only
async def retakes_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.retake_add_btn"), callback_data="adm:rta"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.retake_list_btn"), callback_data="adm:rtl"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await q.edit_message_text(
        t("admin.retakes") + ":", reply_markup=kb
    )


@admin_only
async def retakes_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.retake_add_btn"), callback_data="adm:rta"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.retake_list_btn"), callback_data="adm:rtl"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await update.message.reply_text(t("admin.retakes") + ":", reply_markup=kb)


@admin_only
async def list_retakes_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _send_retakes_list(update, context, edit=False)


@admin_only
async def list_retakes_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    await _send_retakes_list(update, context, edit=True, query=q)


async def _send_retakes_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> None:
    rows = await db.get_all_retakes()
    if not rows:
        text = t("admin.retake_list_empty")
        if edit and query:
            await query.edit_message_text(
                text, reply_markup=admin_main_keyboard()
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=admin_main_keyboard()
            )
        return

    def line_for(r: dict) -> str:
        block = _retake_block(r)
        return t("admin.retake_list_line", id=r["id"], block=block)

    if edit and query:
        r0 = rows[0]
        await query.edit_message_text(
            line_for(r0), reply_markup=retake_delete_keyboard(int(r0["id"]))
        )
        cid = query.message.chat_id
        for r in rows[1:]:
            await context.bot.send_message(
                chat_id=cid,
                text=line_for(r),
                reply_markup=retake_delete_keyboard(int(r["id"])),
            )
        return

    if update.message:
        for i, r in enumerate(rows):
            markup = retake_delete_keyboard(int(r["id"]))
            txt = line_for(r)
            if i == 0:
                await update.message.reply_text(txt, reply_markup=markup)
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=txt,
                    reply_markup=markup,
                )


@admin_only
async def delete_retake_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    args = context.args or []
    if not args:
        return
    try:
        rid = int(args[0])
    except ValueError:
        return
    await db.delete_retake(rid)
    await update.message.reply_text(t("admin.retake_deleted"))


async def delete_retake_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    rid_s = (q.data or "").split(":")[-1]
    try:
        rid = int(rid_s)
    except ValueError:
        return
    await db.delete_retake(rid)
    await q.edit_message_text(t("admin.retake_deleted"))


async def addretake_entry_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    await update.message.reply_text(t("admin.retake_teacher"))
    return R_TEACHER


async def addretake_entry_cb(
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
    await q.edit_message_text(t("admin.retake_teacher"))
    return R_TEACHER


async def r_teacher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data["rt"] = {"teacher": update.message.text.strip()}
    await update.message.reply_text(t("admin.retake_subject"))
    return R_SUBJECT


async def r_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data["rt"]["subject"] = update.message.text.strip()
    await update.message.reply_text(t("admin.retake_date"))
    return R_DATE


async def r_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data["rt"]["date"] = update.message.text.strip()
    await update.message.reply_text(t("admin.retake_time"))
    return R_TIME


async def r_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data["rt"]["time"] = update.message.text.strip()
    await update.message.reply_text(t("admin.retake_room"))
    return R_ROOM


async def r_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data["rt"]["room"] = update.message.text.strip()
    await update.message.reply_text(t("admin.retake_notes"))
    return R_NOTES


async def r_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    notes = "" if raw == "-" else raw
    context.user_data["rt"]["notes"] = notes
    block = _retake_block(context.user_data["rt"])
    await update.message.reply_text(
        t("admin.retake_preview", block=block),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=t("common.confirm"), callback_data="rtadd:yes"
                    ),
                    InlineKeyboardButton(
                        text=t("common.abort"), callback_data="rtadd:no"
                    ),
                ]
            ]
        ),
    )
    return R_CONFIRM


async def r_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    if (q.data or "").endswith(":no"):
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        context.user_data.pop("rt", None)
        return ConversationHandler.END
    data = context.user_data.get("rt") or {}
    await db.insert_retake(data)
    await q.edit_message_text(
        t("admin.retake_saved"), reply_markup=admin_main_keyboard()
    )
    context.user_data.pop("rt", None)
    return ConversationHandler.END


async def r_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _is_admin(update):
        return ConversationHandler.END
    context.user_data.pop("rt", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def _is_admin(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.id in ADMIN_IDS)


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("addretake", addretake_entry_cmd),
            CallbackQueryHandler(addretake_entry_cb, pattern=r"^adm:rta$"),
        ],
        states={
            R_TEACHER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, r_teacher)
            ],
            R_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, r_subject)
            ],
            R_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, r_date)],
            R_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, r_time)],
            R_ROOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, r_room)],
            R_NOTES: [MessageHandler(filters.TEXT & ~filters.COMMAND, r_notes)],
            R_CONFIRM: [
                CallbackQueryHandler(r_confirm, pattern=r"^rtadd:(yes|no)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", r_cancel)],
        name="retake_add_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(
        CallbackQueryHandler(retakes_menu_cb, pattern=r"^adm:retakes$")
    )
    app.add_handler(CommandHandler("listretakes", list_retakes_cmd))
    app.add_handler(CallbackQueryHandler(list_retakes_cb, pattern=r"^adm:rtl$"))
    app.add_handler(CommandHandler("deleteretake", delete_retake_cmd))
    app.add_handler(CallbackQueryHandler(delete_retake_cb, pattern=r"^rtdel:\d+$"))
