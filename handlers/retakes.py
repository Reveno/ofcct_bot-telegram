from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import back_to_menu_keyboard


async def _retakes_body_and_kb() -> tuple[str, object]:
    rows = await db.get_all_retakes()
    if not rows:
        return t("retakes.empty"), back_to_menu_keyboard()
    parts: list[str] = []
    for r in rows:
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
    return "\n\n".join(parts), back_to_menu_keyboard()


async def open_retakes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    text, kb = await _retakes_body_and_kb()
    await q.edit_message_text(text, reply_markup=kb)


async def open_retakes_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    text, kb = await _retakes_body_and_kb()
    await update.message.reply_text(text, reply_markup=kb)


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_retakes, pattern=r"^menu:retakes$"))
