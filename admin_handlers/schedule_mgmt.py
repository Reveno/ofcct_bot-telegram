import os
import tempfile
from datetime import date, timedelta

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
from admin_keyboards import (
    change_days_keyboard,
    change_groups_keyboard,
    change_lessons_keyboard,
    change_type_keyboard,
    clearchanges_confirm_keyboard,
    delete_change_keyboard,
    admin_main_keyboard,
    schedule_upload_confirm_keyboard,
)
from config import ADMIN_IDS
from handlers.schedule import get_week_start
from i18n import t
from utils.schedule_parser import parse_schedule_async

UP_WAIT, UP_CONFIRM = range(2)

# Одне повідомлення: файл .xlsx + підпис /uploadschedule (зручно для груп)
_UPLOAD_DOC_WITH_CAPTION = filters.Document.ALL & filters.CaptionRegex(
    r"^/uploadschedule(@\w+)?(\s|$)"
)
DS_GROUP, DS_DAY, DS_LESSON, DS_CONFIRM = range(10, 14)
C_GROUP, C_DAY, C_LESSON, C_TYPE = range(20, 24)
C_SUBJECT, C_TEACHER, C_ROOM, C_NOTE, C_NOTE_CANCEL, C_CONFIRM = range(30, 36)


def _admin_ok(update: Update) -> bool:
    u = update.effective_user
    return bool(u and u.id in ADMIN_IDS)


def _lesson_label(n: int) -> str:
    return t(f"lessons.{n}")


def _format_change_line(ch: dict) -> str:
    g = ch["group_name"]
    day = t(f"days.{ch['day_of_week']}")
    les = _lesson_label(int(ch["lesson_number"]))
    ct = ch["change_type"]
    if ct == "cancel":
        note = (ch.get("note") or "").strip()
        if note:
            return t(
                "admin.change_line_cancel",
                group=g,
                day=day,
                lesson=les,
                note=note,
            )
        return t(
            "admin.change_line_cancel_nonote",
            group=g,
            day=day,
            lesson=les,
        )
    if ct == "replace":
        return t(
            "admin.change_line_replace",
            group=g,
            day=day,
            lesson=les,
            subject=ch.get("subject") or "",
            teacher=ch.get("teacher") or "",
            room=ch.get("room") or "",
        )
    return t(
        "admin.change_line_add",
        group=g,
        day=day,
        lesson=les,
        subject=ch.get("subject") or "",
        teacher=ch.get("teacher") or "",
        room=ch.get("room") or "",
    )


# --- menus ---


async def schedule_panel_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_uploadschedule"),
                    callback_data="adm:upsched",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_listgroups"),
                    callback_data="adm:listgroups",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_deleteschedule"),
                    callback_data="adm:delsched",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await q.edit_message_text(t("admin.schedule_panel"), reply_markup=kb)


async def changes_panel_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_addchange"),
                    callback_data="adm:chadd",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_listchanges"),
                    callback_data="adm:chlist",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.cmd_clearchanges"),
                    callback_data="adm:chclr",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="adm:home"
                )
            ],
        ]
    )
    await q.edit_message_text(t("admin.changes_panel"), reply_markup=kb)


# --- upload ---


async def upload_entry_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    await update.message.reply_text(t("admin.upload_expect_xlsx"))
    return UP_WAIT


async def upload_entry_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(t("admin.upload_expect_xlsx"))
    return UP_WAIT


async def upload_receive_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    doc = update.message.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(
        ".xlsx"
    ):
        await update.message.reply_text(t("errors.invalid_file"))
        return UP_WAIT
    tg_file = await doc.get_file()
    tmp = os.path.join(
        tempfile.gettempdir(), f"schedule_{update.message.message_id}.xlsx"
    )
    try:
        await tg_file.download_to_drive(custom_path=tmp)
    except Exception:
        await update.message.reply_text(t("errors.download_failed"))
        return UP_WAIT
    try:
        parsed = await parse_schedule_async(tmp)
    except Exception:
        if os.path.isfile(tmp):
            os.remove(tmp)
        await update.message.reply_text(t("errors.parse_failed"))
        return UP_WAIT
    context.user_data["up_path"] = tmp
    context.user_data["up_parsed"] = parsed
    groups = sorted({x["group"] for x in parsed})
    preview = t(
        "admin.upload_parsed",
        lessons=len(parsed),
        groups_count=len(groups),
        group_list=", ".join(groups),
    )
    await update.message.reply_text(
        preview, reply_markup=schedule_upload_confirm_keyboard()
    )
    return UP_CONFIRM


async def upload_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    path = context.user_data.get("up_path")
    parsed = context.user_data.get("up_parsed") or []
    if q.data == "upsched:no":
        if path and os.path.isfile(path):
            os.remove(path)
        context.user_data.pop("up_path", None)
        context.user_data.pop("up_parsed", None)
        await q.edit_message_text(
            t("admin.upload_cancelled"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    entries = [
        {
            "group_name": e["group"],
            "day_of_week": e["day_of_week"],
            "lesson_number": e["lesson_number"],
            "subject": e.get("subject"),
            "teacher": e.get("teacher"),
            "room": e.get("room"),
        }
        for e in parsed
    ]
    await db.delete_all_schedule()
    await db.insert_schedule_bulk(entries)
    if path and os.path.isfile(path):
        os.remove(path)
    groups = sorted({x["group"] for x in parsed})
    context.user_data.pop("up_path", None)
    context.user_data.pop("up_parsed", None)
    await q.edit_message_text(
        t(
            "admin.upload_done",
            lessons=len(parsed),
            groups_count=len(groups),
        ),
        reply_markup=admin_main_keyboard(),
    )
    return ConversationHandler.END


async def upload_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    path = context.user_data.pop("up_path", None)
    context.user_data.pop("up_parsed", None)
    if path and os.path.isfile(path):
        os.remove(path)
    if _admin_ok(update) and update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


# --- listgroups ---


async def listgroups_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return
    groups = await db.get_all_groups()
    if not groups:
        await update.message.reply_text(t("admin.groups_empty"))
        return
    await update.message.reply_text(
        t("admin.groups_list", list="\n".join(groups)),
        reply_markup=admin_main_keyboard(),
    )


async def listgroups_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    groups = await db.get_all_groups()
    if not groups:
        await q.edit_message_text(
            t("admin.groups_empty"), reply_markup=admin_main_keyboard()
        )
        return
    await q.edit_message_text(
        t("admin.groups_list", list="\n".join(groups)),
        reply_markup=admin_main_keyboard(),
    )


# --- delete schedule row ---


async def delsched_entry_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    groups = await db.get_all_groups()
    if not groups:
        await update.message.reply_text(
            t("admin.groups_empty"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    await update.message.reply_text(
        t("admin.delete_schedule_start"),
        reply_markup=change_groups_keyboard(groups, "dls"),
    )
    return DS_GROUP


async def delsched_entry_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    groups = await db.get_all_groups()
    if not groups:
        await q.edit_message_text(
            t("admin.groups_empty"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    await q.edit_message_text(
        t("admin.delete_schedule_start"),
        reply_markup=change_groups_keyboard(groups, "dls"),
    )
    return DS_GROUP


async def dls_pick_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    if q.data == "dls:cancel":
        await q.edit_message_text(
            t("admin.upload_cancelled"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    group = (q.data or "").split(":", 2)[2]
    context.user_data["dls_group"] = group
    await q.edit_message_text(
        t("admin.delete_schedule_pick_day"),
        reply_markup=change_days_keyboard("dls", group),
    )
    return DS_DAY


async def dls_back_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    groups = await db.get_all_groups()
    await q.edit_message_text(
        t("admin.delete_schedule_start"),
        reply_markup=change_groups_keyboard(groups, "dls"),
    )
    return DS_GROUP


async def dls_pick_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    context.user_data["dls_group"] = group
    context.user_data["dls_day"] = day
    await q.edit_message_text(
        t("admin.delete_schedule_pick_lesson"),
        reply_markup=change_lessons_keyboard("dls", group, day),
    )
    return DS_LESSON


async def dls_back_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    group = (q.data or "").split(":", 2)[2]
    await q.edit_message_text(
        t("admin.delete_schedule_pick_day"),
        reply_markup=change_days_keyboard("dls", group),
    )
    return DS_DAY


async def dls_pick_lesson(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    lesson = int(parts[4])
    context.user_data["dls_group"] = group
    context.user_data["dls_day"] = day
    context.user_data["dls_lesson"] = lesson
    day_name = t(f"days.{day}")
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.confirm"), callback_data="dls:cf:yes"
                ),
                InlineKeyboardButton(
                    text=t("common.abort"), callback_data="dls:cf:no"
                ),
            ]
        ]
    )
    await q.edit_message_text(
        t(
            "admin.delete_schedule_confirm",
            group=group,
            day=day_name,
            lesson=_lesson_label(lesson),
        ),
        reply_markup=kb,
    )
    return DS_CONFIRM


async def dls_back_lesson(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    await q.edit_message_text(
        t("admin.delete_schedule_pick_lesson"),
        reply_markup=change_lessons_keyboard("dls", group, day),
    )
    return DS_LESSON


async def dls_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    if q.data == "dls:cf:no":
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END
    group = context.user_data.get("dls_group")
    day = context.user_data.get("dls_day")
    lesson = context.user_data.get("dls_lesson")
    if group is None or day is None or lesson is None:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END
    await db.delete_schedule_lesson(str(group), int(day), int(lesson))
    await q.edit_message_text(
        t("admin.delete_schedule_done"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def delsched_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if _admin_ok(update) and update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


# --- add change ---


async def chg_start_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    return await _chg_start_groups(update, context, edit=False)


async def chg_start_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    return await _chg_start_groups(update, context, edit=True, query=q)


async def _chg_start_groups(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> int:
    groups = await db.get_all_groups()
    if not groups:
        text = t("admin.groups_empty")
        if edit and query:
            await query.edit_message_text(
                text, reply_markup=admin_main_keyboard()
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=admin_main_keyboard()
            )
        return ConversationHandler.END
    kb = change_groups_keyboard(groups, "chg")
    text = t("admin.change_group")
    if edit and query:
        await query.edit_message_text(text, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb)
    return C_GROUP


async def chg_abort(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
    )
    context.user_data.pop("chg", None)
    return ConversationHandler.END


async def chg_pick_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "chg:cancel":
        return await chg_abort(update, context)
    group = data.split(":", 2)[2]
    context.user_data["chg"] = {"group_name": group}
    await q.edit_message_text(
        t("admin.change_day"),
        reply_markup=change_days_keyboard("chg", group),
    )
    return C_DAY


async def chg_back_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    groups = await db.get_all_groups()
    await q.edit_message_text(
        t("admin.change_group"),
        reply_markup=change_groups_keyboard(groups, "chg"),
    )
    return C_GROUP


async def chg_pick_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    context.user_data.setdefault("chg", {})["group_name"] = group
    context.user_data["chg"]["day_of_week"] = day
    await q.edit_message_text(
        t("admin.change_lesson"),
        reply_markup=change_lessons_keyboard("chg", group, day),
    )
    return C_LESSON


async def chg_back_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    group = (q.data or "").split(":", 2)[2]
    await q.edit_message_text(
        t("admin.change_day"),
        reply_markup=change_days_keyboard("chg", group),
    )
    return C_DAY


async def chg_pick_lesson(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    lesson = int(parts[4])
    ch = context.user_data.setdefault("chg", {})
    ch["group_name"] = group
    ch["day_of_week"] = day
    ch["lesson_number"] = lesson
    await q.edit_message_text(
        t("admin.change_type"),
        reply_markup=change_type_keyboard("chg", group, day, lesson),
    )
    return C_TYPE


async def chg_back_lesson(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    await q.edit_message_text(
        t("admin.change_lesson"),
        reply_markup=change_lessons_keyboard("chg", group, day),
    )
    return C_LESSON


async def chg_pick_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2]
    day = int(parts[3])
    lesson = int(parts[4])
    ctype = parts[5]
    ch = context.user_data.setdefault("chg", {})
    ch["group_name"] = group
    ch["day_of_week"] = day
    ch["lesson_number"] = lesson
    ch["change_type"] = ctype
    if ctype == "cancel":
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(
                t("admin.ask_note_cancel")
            )
        return C_NOTE_CANCEL
    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.reply_text(t("admin.ask_subject"))
    return C_SUBJECT


async def chg_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    context.user_data.setdefault("chg", {})["subject"] = update.message.text.strip()
    await update.message.reply_text(t("admin.ask_teacher"))
    return C_TEACHER


async def chg_teacher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    context.user_data.setdefault("chg", {})["teacher"] = update.message.text.strip()
    await update.message.reply_text(t("admin.ask_room"))
    return C_ROOM


async def chg_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    context.user_data.setdefault("chg", {})["room"] = update.message.text.strip()
    await update.message.reply_text(t("admin.ask_note"))
    return C_NOTE


async def chg_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    note = "" if raw == "-" else raw
    context.user_data.setdefault("chg", {})["note"] = note
    return await _chg_send_preview(update, context)


async def chg_note_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    raw = update.message.text.strip()
    note = "" if raw == "-" else raw
    ch = context.user_data.setdefault("chg", {})
    ch["note"] = note
    ch.setdefault("subject", None)
    ch.setdefault("teacher", None)
    ch.setdefault("room", None)
    return await _chg_send_preview(update, context)


async def _chg_send_preview(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    ch = context.user_data.get("chg") or {}
    preview = _format_change_line(
        {
            "group_name": ch.get("group_name"),
            "day_of_week": ch.get("day_of_week"),
            "lesson_number": ch.get("lesson_number"),
            "change_type": ch.get("change_type"),
            "subject": ch.get("subject"),
            "teacher": ch.get("teacher"),
            "room": ch.get("room"),
            "note": ch.get("note"),
        }
    )
    await update.message.reply_text(
        t("admin.change_preview", preview=preview),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=t("common.confirm"), callback_data="chg:cf:yes"
                    ),
                    InlineKeyboardButton(
                        text=t("common.abort"), callback_data="chg:cf:no"
                    ),
                ]
            ]
        ),
    )
    return C_CONFIRM


async def chg_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not _admin_ok(update):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    if q.data == "chg:cf:no":
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        context.user_data.pop("chg", None)
        return ConversationHandler.END
    ch = context.user_data.get("chg") or {}
    user = update.effective_user
    data = {
        "group_name": ch.get("group_name"),
        "day_of_week": int(ch.get("day_of_week")),
        "lesson_number": int(ch.get("lesson_number")),
        "change_type": ch.get("change_type"),
        "subject": ch.get("subject"),
        "teacher": ch.get("teacher"),
        "room": ch.get("room"),
        "note": ch.get("note"),
        "week_start": get_week_start(date.today()),
        "created_by": user.id if user else None,
    }
    await db.insert_change(data)
    await q.edit_message_text(
        t("admin.change_saved"), reply_markup=admin_main_keyboard()
    )
    context.user_data.pop("chg", None)
    return ConversationHandler.END


async def chg_conv_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("chg", None)
    if _admin_ok(update) and update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


# --- list / delete / clear changes ---


async def listchanges_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return
    await _send_listchanges(context, update.effective_chat.id, update.message)


async def listchanges_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    ws = get_week_start(date.today())
    rows = await db.get_all_changes_for_week(ws)
    if not rows:
        await q.edit_message_text(
            t("admin.list_changes_empty"), reply_markup=admin_main_keyboard()
        )
        return
    mon = date.fromisoformat(ws)
    sat = mon + timedelta(days=5)
    header = t(
        "admin.list_changes_header",
        start=mon.strftime("%d.%m"),
        end=sat.strftime("%d.%m"),
    )
    first_line = header + "\n\n" + _format_change_line(rows[0])
    await q.edit_message_text(
        first_line, reply_markup=delete_change_keyboard(int(rows[0]["id"]))
    )
    for r in rows[1:]:
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=_format_change_line(r),
            reply_markup=delete_change_keyboard(int(r["id"])),
        )


async def _send_listchanges(context, chat_id, message) -> None:
    ws = get_week_start(date.today())
    rows = await db.get_all_changes_for_week(ws)
    if not rows:
        await message.reply_text(
            t("admin.list_changes_empty"), reply_markup=admin_main_keyboard()
        )
        return
    mon = date.fromisoformat(ws)
    sat = mon + timedelta(days=5)
    header = t(
        "admin.list_changes_header",
        start=mon.strftime("%d.%m"),
        end=sat.strftime("%d.%m"),
    )
    first = header + "\n\n" + _format_change_line(rows[0])
    await message.reply_text(
        first, reply_markup=delete_change_keyboard(int(rows[0]["id"]))
    )
    for r in rows[1:]:
        await context.bot.send_message(
            chat_id=chat_id,
            text=_format_change_line(r),
            reply_markup=delete_change_keyboard(int(r["id"])),
        )


async def delete_change_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    cid = int((q.data or "").split(":")[1])
    await db.delete_change(cid)
    await q.edit_message_text(t("admin.delete_schedule_done"))


async def deletechange_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        await update.message.reply_text(t("admin.access_denied"))
        return
    args = context.args or []
    if not args:
        return
    try:
        cid = int(args[0])
    except ValueError:
        return
    await db.delete_change(cid)
    await update.message.reply_text(t("admin.delete_schedule_done"))


async def clearchanges_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        await update.message.reply_text(t("admin.access_denied"))
        return
    ws = get_week_start(date.today())
    await update.message.reply_text(
        t("admin.clearchanges_confirm", week=ws),
        reply_markup=clearchanges_confirm_keyboard(ws),
    )


async def clearchanges_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    ws = get_week_start(date.today())
    await q.edit_message_text(
        t("admin.clearchanges_confirm", week=ws),
        reply_markup=clearchanges_confirm_keyboard(ws),
    )


async def clearchanges_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not _admin_ok(update):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "clrch:no":
        await q.edit_message_text(
            t("admin.change_cancelled"), reply_markup=admin_main_keyboard()
        )
        return
    parts = data.split(":")
    ws = parts[2] if len(parts) > 2 else get_week_start(date.today())
    await db.delete_all_changes_for_week(ws)
    await q.edit_message_text(
        t("admin.clearchanges_done"), reply_markup=admin_main_keyboard()
    )


def register(app) -> None:
    up_conv = ConversationHandler(
        entry_points=[
            CommandHandler("uploadschedule", upload_entry_cmd),
            CallbackQueryHandler(upload_entry_cb, pattern=r"^adm:upsched$"),
            MessageHandler(_UPLOAD_DOC_WITH_CAPTION, upload_receive_doc),
        ],
        states={
            UP_WAIT: [
                MessageHandler(filters.Document.ALL, upload_receive_doc),
            ],
            UP_CONFIRM: [
                CallbackQueryHandler(upload_confirm, pattern=r"^upsched:(yes|no)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", upload_cancel)],
        name="upload_schedule",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )

    del_conv = ConversationHandler(
        entry_points=[
            CommandHandler("deleteschedule", delsched_entry_cmd),
            CallbackQueryHandler(delsched_entry_cb, pattern=r"^adm:delsched$"),
        ],
        states={
            DS_GROUP: [
                CallbackQueryHandler(
                    dls_pick_group, pattern=r"^dls:(g:.+|cancel)$"
                ),
            ],
            DS_DAY: [
                CallbackQueryHandler(dls_pick_day, pattern=r"^dls:d:.+"),
                CallbackQueryHandler(dls_back_group, pattern=r"^dls:back_g$"),
            ],
            DS_LESSON: [
                CallbackQueryHandler(dls_pick_lesson, pattern=r"^dls:l:.+"),
                CallbackQueryHandler(dls_back_day, pattern=r"^dls:back_d:.+"),
            ],
            DS_CONFIRM: [
                CallbackQueryHandler(dls_confirm, pattern=r"^dls:cf:(yes|no)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", delsched_cancel)],
        name="delete_schedule",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )

    chg_conv = ConversationHandler(
        entry_points=[
            CommandHandler("addchange", chg_start_cmd),
            CallbackQueryHandler(chg_start_cb, pattern=r"^adm:chadd$"),
        ],
        states={
            C_GROUP: [
                CallbackQueryHandler(chg_pick_group, pattern=r"^chg:g:.+"),
                CallbackQueryHandler(chg_pick_group, pattern=r"^chg:cancel$"),
            ],
            C_DAY: [
                CallbackQueryHandler(chg_pick_day, pattern=r"^chg:d:.+"),
                CallbackQueryHandler(chg_back_group, pattern=r"^chg:back_g$"),
            ],
            C_LESSON: [
                CallbackQueryHandler(chg_pick_lesson, pattern=r"^chg:l:.+"),
                CallbackQueryHandler(chg_back_day, pattern=r"^chg:back_d:.+"),
            ],
            C_TYPE: [
                CallbackQueryHandler(chg_pick_type, pattern=r"^chg:t:.+"),
                CallbackQueryHandler(chg_back_lesson, pattern=r"^chg:back_l:.+"),
            ],
            C_SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chg_subject)
            ],
            C_TEACHER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chg_teacher)
            ],
            C_ROOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, chg_room)],
            C_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, chg_note)],
            C_NOTE_CANCEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, chg_note_cancel)
            ],
            C_CONFIRM: [
                CallbackQueryHandler(chg_confirm, pattern=r"^chg:cf:(yes|no)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", chg_conv_cancel)],
        name="add_change",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )

    app.add_handler(up_conv)
    app.add_handler(del_conv)
    app.add_handler(chg_conv)

    app.add_handler(
        CallbackQueryHandler(schedule_panel_cb, pattern=r"^adm:schedule$")
    )
    app.add_handler(
        CallbackQueryHandler(changes_panel_cb, pattern=r"^adm:changes$")
    )
    app.add_handler(CommandHandler("listgroups", listgroups_cmd))
    app.add_handler(
        CallbackQueryHandler(listgroups_cb, pattern=r"^adm:listgroups$")
    )
    app.add_handler(CommandHandler("listchanges", listchanges_cmd))
    app.add_handler(
        CallbackQueryHandler(listchanges_cb, pattern=r"^adm:chlist$")
    )
    app.add_handler(CommandHandler("deletechange", deletechange_cmd))
    app.add_handler(CallbackQueryHandler(delete_change_cb, pattern=r"^chdel:\d+$"))
    app.add_handler(CommandHandler("clearchanges", clearchanges_cmd))
    app.add_handler(
        CallbackQueryHandler(clearchanges_cb, pattern=r"^adm:chclr$")
    )
    app.add_handler(
        CallbackQueryHandler(clearchanges_confirm, pattern=r"^clrch:(yes|no).*$")
    )
