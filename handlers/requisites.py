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

REQ_NAV = 1


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _requisites_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(t("menu.welcome"), reply_markup=await main_menu_reply_keyboard())
    return ConversationHandler.END


async def _requisites_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("requisites"):
        return ConversationHandler.END
    msg = update.effective_message
    page = await db.get_info_page("requisites")
    body = str(page.get("text") or "").strip() or t("requisites.empty")
    photo_id = str(page.get("photo_file_id") or "").strip()
    if not msg:
        return ConversationHandler.END
    if photo_id:
        try:
            await msg.reply_photo(photo=photo_id, caption=body)
        except Exception:
            await msg.reply_text(body)
    else:
        await msg.reply_text(body)
    await msg.reply_text(t("requisites.title"), reply_markup=nav_reply_keyboard())
    return REQ_NAV


async def _requisites_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return REQ_NAV
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _requisites_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return REQ_NAV


async def _requisites_cancel(
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
                & filters.Regex(main_menu_text_pattern("menu.requisites")),
                _requisites_open,
            ),
        ],
        states={
            REQ_NAV: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _requisites_nav_text)
            ]
        },
        fallbacks=[CommandHandler("cancel", _requisites_cancel)],
        name="requisites_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
