from datetime import date, timedelta

from telegram import Update
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
    schedule_course_row_label,
    schedule_courses_reply_keyboard,
    schedule_days_reply_keyboard,
    schedule_groups_reply_keyboard,
    schedule_view_reply_keyboard,
)

SELECT_COURSE, SELECT_GROUP, SELECT_DAY, VIEW_SCHEDULE = range(4)


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


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _end_main_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    context.user_data.pop("sch_label_to_course", None)
    context.user_data.pop("sch_groups_list", None)
    context.user_data.pop("sch_cohort_mode", None)
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _start_schedule(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()

    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    context.user_data.pop("sch_label_to_course", None)
    context.user_data.pop("sch_groups_list", None)
    context.user_data.pop("sch_cohort_mode", None)

    if not update.effective_chat:
        return ConversationHandler.END

    async def send(text: str, reply_markup) -> None:
        if update.message:
            await update.message.reply_text(text, reply_markup=reply_markup)
        elif q and q.message:
            await q.message.reply_text(text, reply_markup=reply_markup)

    ui_courses = await db.get_ui_course_buttons()
    if ui_courses is not None and len(ui_courses) == 0:
        await send(t("schedule.no_groups"), main_menu_reply_keyboard())
        return ConversationHandler.END

    if ui_courses is not None:
        cohort_mode = await db.is_cohort_ui_mode()
        context.user_data["sch_cohort_mode"] = cohort_mode
        label_to_course = {
            schedule_course_row_label(c, cohort_mode=cohort_mode): c
            for c in ui_courses
        }
        context.user_data["sch_label_to_course"] = label_to_course
        title = (
            t("schedule.choose_cohort")
            if cohort_mode
            else t("schedule.choose_course")
        )
        await send(
            title,
            schedule_courses_reply_keyboard(ui_courses, cohort_mode=cohort_mode),
        )
        return SELECT_COURSE

    groups = await db.get_all_groups()
    if not groups:
        await send(t("schedule.no_groups"), main_menu_reply_keyboard())
        return ConversationHandler.END

    context.user_data["sch_groups_list"] = list(groups)
    await send(
        t("schedule.choose_group"),
        schedule_groups_reply_keyboard(groups),
    )
    return SELECT_GROUP


async def _course_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SELECT_COURSE
    text = update.message.text.strip()
    if text == _menu_label():
        return await _end_main_menu(update, context)
    if text == _back_label():
        return await _end_main_menu(update, context)

    label_map = context.user_data.get("sch_label_to_course") or {}
    course = label_map.get(text)
    if course is None:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SELECT_COURSE

    context.user_data["sch_course"] = int(course)
    groups = await db.get_groups_for_course_selection(int(course))
    if not groups:
        await update.message.reply_text(
            t("schedule.no_groups"),
            reply_markup=main_menu_reply_keyboard(),
        )
        return ConversationHandler.END
    context.user_data["sch_groups_list"] = list(groups)
    await update.message.reply_text(
        t("schedule.choose_group"),
        reply_markup=schedule_groups_reply_keyboard(groups),
    )
    return SELECT_GROUP


async def _group_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SELECT_GROUP
    text = update.message.text.strip()
    if text == _menu_label():
        return await _end_main_menu(update, context)
    if text == _back_label():
        course = context.user_data.get("sch_course")
        if course is not None:
            context.user_data.pop("sch_group", None)
            ui = await db.get_ui_course_buttons()
            if ui is None or not ui:
                await update.message.reply_text(
                    t("schedule.no_groups"),
                    reply_markup=main_menu_reply_keyboard(),
                )
                return ConversationHandler.END
            cohort_mode = await db.is_cohort_ui_mode()
            context.user_data["sch_cohort_mode"] = cohort_mode
            label_to_course = {
                schedule_course_row_label(c, cohort_mode=cohort_mode): c
                for c in ui
            }
            context.user_data["sch_label_to_course"] = label_to_course
            context.user_data.pop("sch_course", None)
            title = (
                t("schedule.choose_cohort")
                if cohort_mode
                else t("schedule.choose_course")
            )
            await update.message.reply_text(
                title,
                reply_markup=schedule_courses_reply_keyboard(
                    ui, cohort_mode=cohort_mode
                ),
            )
            return SELECT_COURSE
        return await _end_main_menu(update, context)

    groups = context.user_data.get("sch_groups_list") or []
    if text not in groups:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SELECT_GROUP

    context.user_data["sch_group"] = text
    await update.message.reply_text(
        t("schedule.choose_day"),
        reply_markup=schedule_days_reply_keyboard(),
    )
    return SELECT_DAY


async def _day_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SELECT_DAY
    text = update.message.text.strip()
    if text == _menu_label():
        return await _end_main_menu(update, context)
    if text == _back_label():
        groups = context.user_data.get("sch_groups_list") or []
        if not groups:
            return await _end_main_menu(update, context)
        await update.message.reply_text(
            t("schedule.choose_group"),
            reply_markup=schedule_groups_reply_keyboard(groups),
        )
        return SELECT_GROUP

    day = None
    for d in range(1, 7):
        if text == t(f"days.short{d}"):
            day = d
            break
    if day is None:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return SELECT_DAY

    group = context.user_data.get("sch_group") or ""
    if not group:
        return await _end_main_menu(update, context)

    body = await build_schedule_message(group, day)
    await update.message.reply_text(
        body,
        reply_markup=schedule_view_reply_keyboard(),
    )
    return VIEW_SCHEDULE


async def _view_schedule_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return VIEW_SCHEDULE
    text = update.message.text.strip()
    if text == _menu_label():
        return await _end_main_menu(update, context)
    if text == t("schedule.back_to_weekdays"):
        group = context.user_data.get("sch_group") or ""
        if not group:
            return await _end_main_menu(update, context)
        await update.message.reply_text(
            t("schedule.choose_day"),
            reply_markup=schedule_days_reply_keyboard(),
        )
        return SELECT_DAY

    await update.message.reply_text(t("schedule.use_keyboard"))
    return VIEW_SCHEDULE


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
    context.user_data.pop("sch_label_to_course", None)
    context.user_data.pop("sch_groups_list", None)
    context.user_data.pop("sch_cohort_mode", None)
    return ConversationHandler.END


async def _cancel_conv_via_main_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q and q.message:
        await q.answer()
        try:
            await q.edit_message_text(t("menu.welcome"))
        except Exception:
            pass
        await q.message.reply_text(
            t("menu.reply_menu_visible"),
            reply_markup=main_menu_reply_keyboard(),
        )
    context.user_data.pop("sch_group", None)
    context.user_data.pop("sch_course", None)
    context.user_data.pop("sch_label_to_course", None)
    context.user_data.pop("sch_groups_list", None)
    context.user_data.pop("sch_cohort_mode", None)
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
                MessageHandler(filters.TEXT & ~filters.COMMAND, _course_text),
                CallbackQueryHandler(
                    _cancel_conv_via_main_cb, pattern=r"^menu:main$"
                ),
            ],
            SELECT_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _group_text),
                CallbackQueryHandler(
                    _cancel_conv_via_main_cb, pattern=r"^menu:main$"
                ),
            ],
            SELECT_DAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _day_text),
                CallbackQueryHandler(
                    _cancel_conv_via_main_cb, pattern=r"^menu:main$"
                ),
            ],
            VIEW_SCHEDULE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _view_schedule_text
                ),
                CallbackQueryHandler(
                    _cancel_conv_via_main_cb, pattern=r"^menu:main$"
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
