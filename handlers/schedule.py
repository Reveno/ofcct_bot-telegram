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
from config import LESSON_TIMES
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    schedule_courses_keyboard,
    schedule_days_keyboard,
    schedule_groups_keyboard,
)

SELECT_COURSE, SELECT_GROUP, SELECT_DAY = range(3)


def get_week_start(d: date | None = None) -> str:
    d = d or date.today()
    return (d - timedelta(days=d.weekday())).isoformat()


async def build_schedule_message(group: str, day: int) -> str:
    week_start = get_week_start()
    base = await db.get_schedule(group, day)
    changes = await db.get_changes(group, day, week_start)
    change_map: dict[int, dict] = {c["lesson_number"]: c for c in changes}

    all_lessons = {r["lesson_number"] for r in base}
    for c in changes:
        if c["change_type"] == "add":
            all_lessons.add(c["lesson_number"])

    if not all_lessons:
        return t("schedule.empty")

    day_name = t(f"days.{day}")
    header = t("schedule.header", group=group, day=day_name)
    lines: list[str] = [header, ""]

    for lesson_num in sorted(all_lessons):
        time_s, time_e = LESSON_TIMES.get(lesson_num, ("?", "?"))
        base_row = next((r for r in base if r["lesson_number"] == lesson_num), None)
        change = change_map.get(lesson_num)

        if change:
            if change["change_type"] == "cancel":
                note_suffix = (
                    f" ({change['note']})" if change.get("note") else ""
                )
                line = t(
                    "schedule.cancelled",
                    n=lesson_num,
                    start=time_s,
                    end=time_e,
                    note_suffix=note_suffix,
                )
                lines.append(line)
                orig = ""
                if base_row and base_row.get("subject"):
                    orig = base_row["subject"]
                if orig:
                    lines.append(t("schedule.was_subject", subject=orig))

            elif change["change_type"] == "replace":
                note_suffix = (
                    t("schedule.note_line", note=change["note"])
                    if change.get("note")
                    else ""
                )
                lines.append(
                    t(
                        "schedule.replace_block",
                        n=lesson_num,
                        start=time_s,
                        end=time_e,
                        subject=change.get("subject") or "",
                        teacher=change.get("teacher") or "",
                        room=change.get("room") or "",
                        note_suffix=note_suffix,
                    )
                )

            elif change["change_type"] == "add":
                note_suffix = (
                    t("schedule.note_line", note=change["note"])
                    if change.get("note")
                    else ""
                )
                lines.append(
                    t(
                        "schedule.add_block",
                        n=lesson_num,
                        start=time_s,
                        end=time_e,
                        subject=change.get("subject") or "",
                        teacher=change.get("teacher") or "",
                        room=change.get("room") or "",
                        note_suffix=note_suffix,
                    )
                )

        elif base_row:
            lines.append(
                t(
                    "schedule.lesson_block",
                    n=lesson_num,
                    start=time_s,
                    end=time_e,
                    subject=base_row.get("subject") or "",
                    teacher=base_row.get("teacher") or "",
                    room=base_row.get("room") or "",
                )
            )

        lines.append("")

    return "\n".join(lines).strip()


def _main_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="menu:main"
                ),
                InlineKeyboardButton(
                    text=t("schedule.to_main_menu"), callback_data="menu:main"
                ),
            ]
        ]
    )


async def _start_schedule(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()
    elif not update.message:
        return ConversationHandler.END

    ui_courses = await db.get_ui_course_buttons()
    if ui_courses is not None and len(ui_courses) == 0:
        text = t("schedule.no_groups")
        if q:
            await q.edit_message_text(text, reply_markup=_main_only_kb())
        elif update.message:
            await update.message.reply_text(text, reply_markup=_main_only_kb())
        return ConversationHandler.END

    if ui_courses is not None:
        cohort_mode = await db.is_cohort_ui_mode()
        text = (
            t("schedule.choose_cohort")
            if cohort_mode
            else t("schedule.choose_course")
        )
        kb = schedule_courses_keyboard(ui_courses, cohort_mode=cohort_mode)
        if q:
            await q.edit_message_text(text, reply_markup=kb)
        elif update.message:
            await update.message.reply_text(text, reply_markup=kb)
        context.user_data.pop("sch_course", None)
        context.user_data.pop("sch_group", None)
        return SELECT_COURSE

    groups = await db.get_all_groups()
    if not groups:
        text = t("schedule.no_groups")
        if q:
            await q.edit_message_text(text, reply_markup=_main_only_kb())
        elif update.message:
            await update.message.reply_text(text, reply_markup=_main_only_kb())
        return ConversationHandler.END

    text = t("schedule.choose_group")
    kb = schedule_groups_keyboard(groups, course=None)
    if q:
        await q.edit_message_text(text, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(text, reply_markup=kb)
    context.user_data.pop("sch_course", None)
    context.user_data.pop("sch_group", None)
    return SELECT_GROUP


async def _pick_course(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    await q.answer()
    try:
        course = int((q.data or "").split(":")[2])
    except (ValueError, IndexError):
        return ConversationHandler.END
    context.user_data["sch_course"] = course
    groups = await db.get_groups_for_course_selection(course)
    if not groups:
        await q.edit_message_text(
            t("schedule.no_groups"), reply_markup=_main_only_kb()
        )
        return ConversationHandler.END
    await q.edit_message_text(
        t("schedule.choose_group"),
        reply_markup=schedule_groups_keyboard(groups, course=course),
    )
    return SELECT_GROUP


async def _show_courses_again(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    ui = await db.get_ui_course_buttons()
    if ui is None or not ui:
        await q.edit_message_text(
            t("schedule.no_groups"), reply_markup=_main_only_kb()
        )
        return ConversationHandler.END
    cohort_mode = await db.is_cohort_ui_mode()
    text = (
        t("schedule.choose_cohort")
        if cohort_mode
        else t("schedule.choose_course")
    )
    await q.edit_message_text(
        text,
        reply_markup=schedule_courses_keyboard(ui, cohort_mode=cohort_mode),
    )
    return SELECT_COURSE


async def _pick_group(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    await q.answer()
    data = (q.data or "").split(":", 2)
    group = data[2] if len(data) > 2 else ""
    context.user_data["sch_group"] = group
    await q.edit_message_text(
        t("schedule.choose_day"),
        reply_markup=schedule_days_keyboard(group),
    )
    return SELECT_DAY


async def _back_to_group_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    await q.answer()
    course = context.user_data.get("sch_course")
    if course is not None:
        groups = await db.get_groups_for_course_selection(int(course))
        if not groups:
            await q.edit_message_text(
                t("schedule.no_groups"), reply_markup=_main_only_kb()
            )
            return ConversationHandler.END
        await q.edit_message_text(
            t("schedule.choose_group"),
            reply_markup=schedule_groups_keyboard(groups, course=int(course)),
        )
        return SELECT_GROUP
    groups = await db.get_all_groups()
    if not groups:
        await q.edit_message_text(
            t("schedule.no_groups"), reply_markup=_main_only_kb()
        )
        return ConversationHandler.END
    await q.edit_message_text(
        t("schedule.choose_group"),
        reply_markup=schedule_groups_keyboard(groups, course=None),
    )
    return SELECT_GROUP


async def _pick_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2] if len(parts) > 2 else ""
    day = int(parts[3]) if len(parts) > 3 else 1
    context.user_data["sch_group"] = group
    body = await build_schedule_message(group, day)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.back"),
                    callback_data=f"sch:bd:{group}",
                ),
                InlineKeyboardButton(
                    text=t("schedule.to_main_menu"),
                    callback_data="menu:main",
                ),
            ]
        ]
    )
    await q.edit_message_text(body, reply_markup=kb)
    return SELECT_DAY


async def _back_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    parts = (q.data or "").split(":")
    group = parts[2] if len(parts) > 2 else context.user_data.get("sch_group", "")
    await q.edit_message_text(
        t("schedule.choose_day"), reply_markup=schedule_days_keyboard(group)
    )
    return SELECT_DAY


async def _cancel_conv(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    return ConversationHandler.END


async def _cancel_conv_via_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q and q.message:
        await q.answer()
        try:
            await q.edit_message_text(t("menu.welcome"))
        except Exception:
            pass
    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_start_schedule, pattern=r"^menu:schedule$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.schedule")),
                _start_schedule,
            ),
        ],
        states={
            SELECT_COURSE: [
                CallbackQueryHandler(_pick_course, pattern=r"^sch:c:\d+$"),
                CallbackQueryHandler(
                    _cancel_conv_via_main, pattern=r"^menu:main$"
                ),
            ],
            SELECT_GROUP: [
                CallbackQueryHandler(_pick_group, pattern=r"^sch:g:.+"),
                CallbackQueryHandler(
                    _show_courses_again, pattern=r"^sch:back_courses$"
                ),
                CallbackQueryHandler(
                    _cancel_conv_via_main, pattern=r"^menu:main$"
                ),
            ],
            SELECT_DAY: [
                CallbackQueryHandler(_pick_day, pattern=r"^sch:d:.+"),
                CallbackQueryHandler(
                    _back_to_group_list, pattern=r"^sch:back_groups$"
                ),
                CallbackQueryHandler(_back_days, pattern=r"^sch:bd:.+"),
                CallbackQueryHandler(
                    _cancel_conv_via_main, pattern=r"^menu:main$"
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel_conv)],
        name="schedule_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
