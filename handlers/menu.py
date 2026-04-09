from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from i18n import t
from keyboards import (
    ensure_main_menu_reply_keyboard,
    main_menu_reply_keyboard,
    main_menu_text_pattern,
)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    un = user.username or ""
    await db.upsert_user(user.id, un)
    await update.message.reply_text(
        t("menu.welcome"), reply_markup=main_menu_reply_keyboard()
    )


async def main_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    await q.answer()
    try:
        await q.edit_message_text(t("menu.welcome"))
    except Exception:
        pass
    await ensure_main_menu_reply_keyboard(context, q.message.chat_id)


def register(app) -> None:
    app.add_handler(CommandHandler("start", start_cmd))


def register_main_callback(app) -> None:
    """Register after ConversationHandlers so menu:main is not handled too early."""
    app.add_handler(
        CallbackQueryHandler(main_menu_callback, pattern=r"^menu:main$")
    )


def register_main_menu_text_routes(app) -> None:
    """Відкриття розділів текстом кнопок reply-меню (після всіх ConversationHandler)."""
    from handlers import news as news_h
    from handlers import retakes as retakes_h
    from handlers import social as social_h
    from handlers import subscription as sub_h

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(main_menu_text_pattern("menu.social")),
            social_h.open_social_from_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(main_menu_text_pattern("menu.subscription")),
            sub_h.open_subscription_from_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(main_menu_text_pattern("menu.retakes")),
            retakes_h.open_retakes_from_message,
        )
    )
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(main_menu_text_pattern("menu.news")),
            news_h.open_news_from_message,
        )
    )
