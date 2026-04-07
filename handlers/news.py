from datetime import datetime

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import back_to_menu_keyboard


def _fmt_dt(val) -> str:
    if val is None:
        return ""
    if isinstance(val, datetime):
        return val.strftime("%d.%m.%Y %H:%M")
    s = str(val)
    if " " in s and len(s) >= 16:
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime(
                "%d.%m.%Y %H:%M"
            )
        except ValueError:
            return s[:16]
    return s


async def open_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    rows = await db.get_recent_broadcasts(5)
    if not rows:
        await q.edit_message_text(
            t("news.empty"), reply_markup=back_to_menu_keyboard()
        )
        return
    has_photo = any(r.get("photo_file_id") for r in rows)
    if not has_photo:
        parts = []
        for r in rows:
            parts.append(
                t(
                    "news.entry",
                    dt=_fmt_dt(r.get("sent_at")),
                    text=r.get("text", ""),
                )
            )
        text = "\n".join(parts)
        await q.edit_message_text(text, reply_markup=back_to_menu_keyboard())
        return

    await q.edit_message_text(
        t("news.header_with_attachments"),
        reply_markup=back_to_menu_keyboard(),
    )
    chat_id = q.message.chat_id
    thread_id = q.message.message_id
    for r in rows:
        dt = _fmt_dt(r.get("sent_at"))
        body = (r.get("text") or "").strip()
        cap = f"📰 {dt}\n{body}" if body else f"📰 {dt}"
        if len(cap) > 1024:
            cap = cap[:1020] + "…"
        pid = r.get("photo_file_id")
        if pid:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=pid,
                caption=cap,
                reply_to_message_id=thread_id,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=cap,
                reply_to_message_id=thread_id,
            )


def register(app) -> None:
    app.add_handler(CallbackQueryHandler(open_news, pattern=r"^menu:news$"))
