"""Текстові кнопки reply-меню адміна (паралельно до inline)."""

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from admin_keyboards import admin_reply_router_text_regex
from config import ADMIN_IDS
from i18n import t

from admin_handlers.broadcast import news_manage_from_message
from admin_handlers.faq_mgmt import faq_menu_from_message
from admin_handlers.messages import show_messages_cmd
from admin_handlers.retakes_mgmt import retakes_menu_from_message
from admin_handlers.schedule_mgmt import (
    changes_panel_from_message,
    schedule_panel_from_message,
)
from admin_handlers.stats import stats_cmd


def _is_admin(update: Update) -> bool:
    u = update.effective_user
    return u is not None and u.id in ADMIN_IDS


async def admin_reply_menu_router(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message or not update.message.text or not _is_admin(update):
        return
    txt = update.message.text.strip()
    if txt == t("admin.messages"):
        await show_messages_cmd(update, context)
    elif txt == t("admin.stats"):
        await stats_cmd(update, context)
    elif txt == t("admin.news_manage"):
        await news_manage_from_message(update, context)
    elif txt == t("admin.faq"):
        await faq_menu_from_message(update, context)
    elif txt == t("admin.schedule"):
        await schedule_panel_from_message(update, context)
    elif txt == t("admin.schedule_changes"):
        await changes_panel_from_message(update, context)
    elif txt == t("admin.retakes"):
        await retakes_menu_from_message(update, context)


def register(app) -> None:
    rx = admin_reply_router_text_regex()
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(rx),
            admin_reply_menu_router,
        )
    )
