from datetime import date

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

import db
from admin_keyboards import admin_main_keyboard
from config import admin_only
from handlers.schedule import get_week_start
from i18n import t


@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_stats(update, context, edit=False)


@admin_only
async def stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await _send_stats(update, context, edit=True, query=q)


async def _send_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> None:
    users = await db.count_users()
    subs = await db.count_subscribers()
    fb_total = await db.count_feedback()
    fb_open = await db.count_unanswered()
    br = await db.count_broadcasts()
    groups = await db.get_all_groups()
    ws = get_week_start(date.today())
    ch = await db.count_changes_for_week(ws)
    body = t(
        "admin.stats_body",
        users=users,
        subs=subs,
        feedback_total=fb_total,
        feedback_open=fb_open,
        broadcasts=br,
        groups=len(groups),
        changes=ch,
    )
    if edit and query:
        await query.edit_message_text(body, reply_markup=admin_main_keyboard())
    elif update.message:
        await update.message.reply_text(body, reply_markup=admin_main_keyboard())


def register(app) -> None:
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CallbackQueryHandler(stats_cb, pattern=r"^adm:stats$"))
