import html

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
from config import (
    SOCIAL_FACEBOOK_URL,
    SOCIAL_INSTAGRAM_URL,
    SOCIAL_SITE_URL,
    SOCIAL_TELEGRAM_URL,
)
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    nav_reply_keyboard,
)

SOCIAL_NAV = 1


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


async def _social_message_html() -> str:
    lines = [html.escape(t("social.title")), ""]
    rows = await db.get_all_social_links()
    if rows:
        for r in rows:
            u = (r.get("url") or "").strip()
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            title = html.escape(str(r.get("title") or "link"))
            lines.append(f'<a href="{html.escape(u)}">{title}</a>')
        return "\n".join(lines)
    lines.extend(
        [
            f'<a href="{html.escape(SOCIAL_INSTAGRAM_URL)}">'
            f"{html.escape(t('social.instagram'))}</a>",
            f'<a href="{html.escape(SOCIAL_TELEGRAM_URL)}">'
            f"{html.escape(t('social.telegram_channel'))}</a>",
            f'<a href="{html.escape(SOCIAL_SITE_URL)}">'
            f"{html.escape(t('social.website'))}</a>",
            f'<a href="{html.escape(SOCIAL_FACEBOOK_URL)}">'
            f"{html.escape(t('social.facebook'))}</a>",
        ]
    )
    return "\n".join(lines)


async def _social_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _social_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if q:
        await q.answer()

    body = await _social_message_html()
    if update.message:
        await update.message.reply_text(
            body,
            reply_markup=nav_reply_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    elif q and q.message:
        await q.message.reply_text(
            body,
            reply_markup=nav_reply_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        return ConversationHandler.END
    return SOCIAL_NAV


async def _social_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return SOCIAL_NAV
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _social_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return SOCIAL_NAV


async def _social_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _social_main_cb(
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
            CallbackQueryHandler(_social_open, pattern=r"^menu:social$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.social")),
                _social_open,
            ),
        ],
        states={
            SOCIAL_NAV: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _social_nav_text
                ),
                CallbackQueryHandler(_social_main_cb, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _social_cancel)],
        name="social_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
