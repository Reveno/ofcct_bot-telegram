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
from config import ADMIN_IDS, admin_only
from i18n import t

AD_PICK, AD_TIME, AD_TEACHER, AD_ROOM, AD_SUBJECT, AD_NOTES, AD_CONFIRM = range(7)
ED_TIME, ED_TEACHER, ED_ROOM, ED_SUBJECT, ED_NOTES = range(7, 12)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def _day_pick_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for d in range(1, 7):
        row.append(
            InlineKeyboardButton(
                text=t(f"days.short{d}"),
                callback_data=f"cons_pick:{d}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t("common.abort"), callback_data="cons_add:abort"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _slot_block(row: dict) -> str:
    day = t(f"days.{int(row['day_of_week'])}")
    subj = (row.get("subject") or "").strip() or "—"
    notes = (row.get("notes") or "").strip() or t("consultations.notes_empty")
    return t(
        "consultations.admin_slot_block",
        day=day,
        time=row.get("time", ""),
        teacher=row.get("teacher", ""),
        room=row.get("room", ""),
        subject=subj,
        notes=notes,
    )


def _consultation_row_keyboard(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text="✏️",
                    callback_data=f"adm:cons_e:{sid}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"consdel:{sid}",
                ),
            ]
        ]
    )


@admin_only
async def consultations_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.cons_add_btn"), callback_data="adm:cons_add"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cons_list_btn"), callback_data="adm:cons_list"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await q.edit_message_text(t("admin.consultations") + ":", reply_markup=kb)


@admin_only
async def consultations_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.cons_add_btn"), callback_data="adm:cons_add"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cons_list_btn"), callback_data="adm:cons_list"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await update.message.reply_text(
        t("admin.consultations") + ":", reply_markup=kb
    )


@admin_only
async def list_consultations_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _send_consultations_list(update, context, edit=False)


async def list_consultations_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        q = update.callback_query
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    q = update.callback_query
    await q.answer()
    await _send_consultations_list(update, context, edit=True, query=q)


async def _send_consultations_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> None:
    rows = await db.get_all_consultation_slots()
    if not rows:
        text = t("admin.cons_list_empty")
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
        return t(
            "admin.cons_list_line",
            id=r["id"],
            block=_slot_block(r),
        )

    if edit and query:
        r0 = rows[0]
        await query.edit_message_text(
            line_for(r0),
            reply_markup=_consultation_row_keyboard(int(r0["id"])),
        )
        cid = query.message.chat_id
        for r in rows[1:]:
            await context.bot.send_message(
                chat_id=cid,
                text=line_for(r),
                reply_markup=_consultation_row_keyboard(int(r["id"])),
            )
        return

    if update.message:
        for i, r in enumerate(rows):
            markup = _consultation_row_keyboard(int(r["id"]))
            txt = line_for(r)
            if i == 0:
                await update.message.reply_text(txt, reply_markup=markup)
            else:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=txt,
                    reply_markup=markup,
                )


async def delete_consultation_cb(
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
    m = re.match(r"^consdel:(\d+)$", q.data or "")
    if not m:
        return
    await db.delete_consultation_slot(int(m.group(1)))
    await q.edit_message_text(t("admin.cons_deleted"))


# --- add conversation ---


async def cons_add_start(
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
    context.user_data.pop("cons_new", None)
    await q.edit_message_text(
        t("admin.cons_pick_day"),
        reply_markup=_day_pick_keyboard(),
    )
    return AD_PICK


async def cons_pick_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    if (q.data or "") == "cons_add:abort":
        await q.answer()
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    m = re.match(r"^cons_pick:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return AD_PICK
    day = int(m.group(1))
    if day < 1 or day > 6:
        await q.answer()
        return AD_PICK
    await q.answer()
    context.user_data["cons_new"] = {"day_of_week": day}
    await q.message.reply_text(t("admin.cons_time"))
    return AD_TIME


async def cons_add_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_TIME
    context.user_data["cons_new"]["time"] = update.message.text.strip()
    await update.message.reply_text(t("admin.cons_teacher"))
    return AD_TEACHER


async def cons_add_teacher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_TEACHER
    context.user_data["cons_new"]["teacher"] = update.message.text.strip()
    await update.message.reply_text(t("admin.cons_room"))
    return AD_ROOM


async def cons_add_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_ROOM
    context.user_data["cons_new"]["room"] = update.message.text.strip()
    await update.message.reply_text(t("admin.cons_subject_skip"))
    return AD_SUBJECT


async def cons_add_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_SUBJECT
    raw = update.message.text.strip()
    context.user_data["cons_new"]["subject"] = "" if raw.lower() == "/skip" else raw
    await update.message.reply_text(t("admin.cons_notes_skip"))
    return AD_NOTES


async def cons_add_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_NOTES
    raw = update.message.text.strip()
    notes = None if raw.lower() == "/skip" else raw
    context.user_data["cons_new"]["notes"] = notes
    data = context.user_data["cons_new"]
    block = _slot_block(
        {
            "day_of_week": data["day_of_week"],
            "time": data["time"],
            "teacher": data["teacher"],
            "room": data["room"],
            "subject": data.get("subject", ""),
            "notes": notes or "",
        }
    )
    await update.message.reply_text(
        t("admin.cons_preview", block=block),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=t("common.confirm"), callback_data="cons_save:yes"
                    ),
                    InlineKeyboardButton(
                        text=t("common.abort"), callback_data="cons_save:no"
                    ),
                ]
            ]
        ),
    )
    return AD_CONFIRM


async def cons_add_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q or not _ok(user.id if user else None):
        return ConversationHandler.END
    await q.answer()
    if (q.data or "").endswith(":no"):
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        context.user_data.pop("cons_new", None)
        return ConversationHandler.END
    data = context.user_data.get("cons_new") or {}
    if not data:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END
    data["sort_order"] = await db.get_next_consultation_order_index()
    await db.insert_consultation_slot(data)
    context.user_data.pop("cons_new", None)
    await q.edit_message_text(
        t("admin.cons_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


# --- edit conversation ---


async def cons_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q or not _ok(user.id if user else None):
        return ConversationHandler.END
    m = re.match(r"^adm:cons_e:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return ConversationHandler.END
    sid = int(m.group(1))
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await q.answer()
        return ConversationHandler.END
    await q.answer()
    context.user_data["cons_edit_id"] = sid
    await q.message.reply_text(
        t("admin.cons_edit_time", time=row.get("time", ""))
    )
    return ED_TIME


async def cons_edit_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_TIME
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_time"] = txt
    else:
        context.user_data.pop("cons_e_time", None)
    await update.message.reply_text(
        t("admin.cons_edit_teacher", teacher=row.get("teacher", ""))
    )
    return ED_TEACHER


async def cons_edit_teacher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_TEACHER
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_teacher"] = txt
    else:
        context.user_data.pop("cons_e_teacher", None)
    await update.message.reply_text(
        t("admin.cons_edit_room", room=row.get("room", ""))
    )
    return ED_ROOM


async def cons_edit_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_ROOM
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_room"] = txt
    else:
        context.user_data.pop("cons_e_room", None)
    await update.message.reply_text(
        t("admin.cons_edit_subject", subject=row.get("subject", "") or "—")
    )
    return ED_SUBJECT


async def cons_edit_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_SUBJECT
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_subject"] = txt
    else:
        context.user_data.pop("cons_e_subject", None)
    await update.message.reply_text(
        t("admin.cons_edit_notes", notes=row.get("notes") or "—")
    )
    return ED_NOTES


async def cons_edit_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_NOTES
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END

    time_v = context.user_data.get("cons_e_time", row.get("time", ""))
    teacher_v = context.user_data.get("cons_e_teacher", row.get("teacher", ""))
    room_v = context.user_data.get("cons_e_room", row.get("room", ""))
    if "cons_e_subject" in context.user_data:
        subj_v = context.user_data["cons_e_subject"]
    else:
        subj_v = row.get("subject") or ""

    if txt.lower() != "/skip":
        notes_v: str | None = txt
    else:
        notes_v = row.get("notes")
        if notes_v is not None:
            notes_v = str(notes_v)

    await db.update_consultation_slot(
        sid,
        day_of_week=int(row["day_of_week"]),
        time=str(time_v),
        teacher=str(teacher_v),
        room=str(room_v),
        subject=str(subj_v),
        notes=notes_v,
    )
    context.user_data.pop("cons_edit_id", None)
    for k in list(context.user_data.keys()):
        if k.startswith("cons_e_"):
            context.user_data.pop(k, None)
    await update.message.reply_text(
        t("admin.cons_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def cons_conv_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("cons_new", None)
    context.user_data.pop("cons_edit_id", None)
    for k in list(context.user_data.keys()):
        if k.startswith("cons_e_"):
            context.user_data.pop(k, None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cons_add_start, pattern=r"^adm:cons_add$"),
            CallbackQueryHandler(cons_edit_start, pattern=r"^adm:cons_e:\d+$"),
        ],
        states={
            AD_PICK: [
                CallbackQueryHandler(cons_pick_day, pattern=r"^cons_pick:\d+$"),
                CallbackQueryHandler(cons_pick_day, pattern=r"^cons_add:abort$"),
            ],
            AD_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_add_time)
            ],
            AD_TEACHER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_add_teacher)
            ],
            AD_ROOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_add_room)
            ],
            AD_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_add_subject)
            ],
            AD_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_add_notes)
            ],
            AD_CONFIRM: [
                CallbackQueryHandler(
                    cons_add_confirm, pattern=r"^cons_save:(yes|no)$"
                )
            ],
            ED_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_edit_time)
            ],
            ED_TEACHER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_edit_teacher)
            ],
            ED_ROOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_edit_room)
            ],
            ED_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_edit_subject)
            ],
            ED_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, cons_edit_notes)
            ],
        },
        fallbacks=[CommandHandler("cancel", cons_conv_cancel)],
        name="consultation_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(
        CallbackQueryHandler(consultations_menu_cb, pattern=r"^adm:consultations$")
    )
    app.add_handler(
        CallbackQueryHandler(consultations_menu_cb, pattern=r"^adm:retakes$")
    )
    app.add_handler(
        CallbackQueryHandler(list_consultations_cb, pattern=r"^adm:cons_list$")
    )
    app.add_handler(
        CommandHandler("listconsultations", list_consultations_cmd)
    )
    app.add_handler(
        CommandHandler("listretakes", list_consultations_cmd)
    )
    app.add_handler(
        CallbackQueryHandler(delete_consultation_cb, pattern=r"^consdel:\d+$")
    )
