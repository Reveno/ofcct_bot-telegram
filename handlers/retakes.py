from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import back_to_menu_keyboard


async def open_retakes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    rows = await db.get_all_retakes()
    if not rows:
        await q.edit_message_text(
            t("retakes.empty"), reply_markup=back_to_menu_keyboard()
        )
        return
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
    text = "\n\n".join(parts)
    await q.edit_message_text(text, reply_markup=back_to_menu_keyboard())


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_retakes, pattern=r"^menu:retakes$"))
