from telegram import Update
from telegram.ext import (
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

COURSES_NAV = 1


async def _courses_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(t("menu.welcome"), reply_markup=await main_menu_reply_keyboard())
    return ConversationHandler.END


async def _courses_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("courses"):
        return ConversationHandler.END
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    rows = await db.get_all_paid_courses()
    if not rows:
        body = t("courses.empty")
    else:
        lines = [t("courses.title"), ""]
        for i, r in enumerate(rows, start=1):
            ttl = str(r.get("title") or "").strip()
            desc = str(r.get("description") or "").strip()
            lines.append(f"{i}. {ttl}")
            if desc:
                lines.append(desc)
        body = "\n".join(lines)
    await msg.reply_text(body, reply_markup=nav_reply_keyboard())
    return COURSES_NAV


async def _courses_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return COURSES_NAV
    text = update.message.text.strip()
    if text in (t("common.back"), t("schedule.to_main_menu")):
        return await _courses_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return COURSES_NAV


async def _courses_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.courses")),
                _courses_open,
            ),
        ],
        states={
            COURSES_NAV: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _courses_nav_text)
            ]
        },
        fallbacks=[CommandHandler("cancel", _courses_cancel)],
        name="courses_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
