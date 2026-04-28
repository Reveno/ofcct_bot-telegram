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

EDU_NAV = 1


async def _edu_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(t("menu.welcome"), reply_markup=await main_menu_reply_keyboard())
    return ConversationHandler.END


async def _edu_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("edu_process"):
        return ConversationHandler.END
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    page = await db.get_info_page("edu_process")
    photo_id = str(page.get("photo_file_id") or "").strip()
    caption = str(page.get("text") or "").strip()
    if photo_id:
        try:
            await msg.reply_photo(
                photo=photo_id, caption=caption if caption else t("edu_process.title")
            )
        except Exception:
            await msg.reply_text(t("edu_process.empty"))
    else:
        await msg.reply_text(t("edu_process.empty"))
    await msg.reply_text(t("edu_process.title"), reply_markup=nav_reply_keyboard())
    return EDU_NAV


async def _edu_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return EDU_NAV
    text = update.message.text.strip()
    if text in (t("common.back"), t("schedule.to_main_menu")):
        return await _edu_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return EDU_NAV


async def _edu_cancel(
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
                & filters.Regex(main_menu_text_pattern("menu.edu_process")),
                _edu_open,
            ),
        ],
        states={EDU_NAV: [MessageHandler(filters.TEXT & ~filters.COMMAND, _edu_nav_text)]},
        fallbacks=[CommandHandler("cancel", _edu_cancel)],
        name="edu_process_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
