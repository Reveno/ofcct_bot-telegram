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
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    nav_reply_keyboard,
)

RETAKES_NAV = 1


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _retakes_body() -> str:
    slots = await db.get_all_consultation_slots()
    legacy = await db.get_all_retakes()
    if not slots and not legacy:
        return t("retakes.empty")
    parts: list[str] = []
    if slots:
        parts.append(t("consultations.weekly_header"))
        for s in slots:
            dow = int(s["day_of_week"])
            subj = (s.get("subject") or "").strip() or "—"
            notes = (s.get("notes") or "").strip() or t("retakes.notes_empty")
            parts.append(
                t(
                    "consultations.weekly_slot",
                    day=t(f"days.{dow}"),
                    time=s.get("time", ""),
                    room=s.get("room", ""),
                    teacher=s.get("teacher", ""),
                    subject=subj,
                    notes=notes,
                )
            )
    if legacy:
        parts.append(t("consultations.legacy_header"))
        for r in legacy:
            notes = r.get("notes") or t("retakes.notes_empty")
            parts.append(
                t(
                    "retakes.entry",
                    date=r.get("date", ""),
                    time=r.get("time", ""),
                    room=r.get("room", ""),
                    subject=r.get("subject", ""),
                    teacher=r.get("teacher", ""),
                    notes=notes,
                )
            )
    return "\n\n".join(parts)


async def _retakes_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _retakes_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()

    body = await _retakes_body()
    if update.message:
        await update.message.reply_text(
            body,
            reply_markup=nav_reply_keyboard(),
        )
    elif q and q.message:
        await q.message.reply_text(
            body,
            reply_markup=nav_reply_keyboard(),
        )
    else:
        return ConversationHandler.END
    return RETAKES_NAV


async def _retakes_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return RETAKES_NAV
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _retakes_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return RETAKES_NAV


async def _retakes_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _retakes_main_cb(
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
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_retakes_open, pattern=r"^menu:retakes$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.retakes")),
                _retakes_open,
            ),
        ],
        states={
            RETAKES_NAV: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _retakes_nav_text
                ),
                CallbackQueryHandler(_retakes_main_cb, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _retakes_cancel)],
        name="retakes_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
