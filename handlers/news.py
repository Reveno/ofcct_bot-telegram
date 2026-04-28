import html
from datetime import datetime

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
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    news_detail_reply_keyboard,
    news_list_reply_keyboard,
    reply_indexed_label,
)

NEWS_LIST, NEWS_DETAIL = range(2)


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


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


def _news_title(row: dict) -> str:
    title = (row.get("title") or "").strip()
    if title:
        return title
    body = (row.get("text") or "").strip()
    if body:
        line = body.split("\n", 1)[0].strip()
        return line[:80] + ("…" if len(line) > 80 else "")
    return t("news.no_title")


def _format_news_detail_html(row: dict) -> str:
    title = (row.get("title") or "").strip()
    body = (row.get("text") or "").strip()
    link = (row.get("link_url") or "").strip()
    dt = _fmt_dt(row.get("sent_at"))
    parts: list[str] = []
    if title:
        parts.append(f"<b>{html.escape(title)}</b>")
    parts.append(f"📅 {html.escape(dt)}")
    if body:
        parts.append(html.escape(body))
    if link:
        u = link.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        parts.append(
            f'<a href="{html.escape(u)}">{html.escape(t("news.link_label"))}</a>'
        )
    return "\n\n".join(parts)


async def _news_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("news_items", None)
    context.user_data.pop("news_label_to_id", None)
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _news_open_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("news"):
        return ConversationHandler.END
    q = update.callback_query
    if q:
        await q.answer()

    context.user_data.pop("news_items", None)
    context.user_data.pop("news_label_to_id", None)

    rows = await db.get_recent_broadcasts(15)
    if not rows:
        text = t("news.empty")
        if update.message:
            await update.message.reply_text(
                text,
                reply_markup=await main_menu_reply_keyboard(),
            )
        elif q and q.message:
            await q.message.reply_text(
                text,
                reply_markup=await main_menu_reply_keyboard(),
            )
        return ConversationHandler.END

    items = [(int(r["id"]), _news_title(r)) for r in rows]
    context.user_data["news_items"] = items
    context.user_data["news_label_to_id"] = {
        reply_indexed_label(i, title): nid
        for i, (nid, title) in enumerate(items, start=1)
    }

    title_text = t("news.list_title")
    kb = news_list_reply_keyboard(items)
    if update.message:
        await update.message.reply_text(title_text, reply_markup=kb)
    elif q and q.message:
        await q.message.reply_text(title_text, reply_markup=kb)
    else:
        return ConversationHandler.END
    return NEWS_LIST


async def _news_list_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return NEWS_LIST
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _news_end_main(update, context)

    label_to_id = context.user_data.get("news_label_to_id") or {}
    nid = label_to_id.get(text)
    if nid is None:
        await update.message.reply_text(t("schedule.use_keyboard"))
        return NEWS_LIST

    row = await db.get_broadcast_by_id(int(nid))
    if not row:
        await update.message.reply_text(
            t("news.empty"),
            reply_markup=await main_menu_reply_keyboard(),
        )
        return ConversationHandler.END

    body = _format_news_detail_html(row)
    await update.message.reply_text(
        body,
        reply_markup=news_detail_reply_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=False,
    )
    return NEWS_DETAIL


async def _news_detail_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return NEWS_DETAIL
    text = update.message.text.strip()
    if text == t("news.back_to_list"):
        items = context.user_data.get("news_items")
        if not items:
            return await _news_end_main(update, context)
        await update.message.reply_text(
            t("news.list_title"),
            reply_markup=news_list_reply_keyboard(items),
        )
        return NEWS_LIST
    if text in (_back_label(), _menu_label()):
        return await _news_end_main(update, context)

    await update.message.reply_text(t("schedule.use_keyboard"))
    return NEWS_DETAIL


async def _news_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    context.user_data.pop("news_items", None)
    context.user_data.pop("news_label_to_id", None)
    return ConversationHandler.END


async def _news_main_cb(
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
            reply_markup=await main_menu_reply_keyboard(),
        )
    context.user_data.pop("news_items", None)
    context.user_data.pop("news_label_to_id", None)
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                _news_open_list, pattern=r"^(menu:news|news:list)$"
            ),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.news")),
                _news_open_list,
            ),
        ],
        states={
            NEWS_LIST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _news_list_text),
                CallbackQueryHandler(_news_main_cb, pattern=r"^menu:main$"),
            ],
            NEWS_DETAIL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _news_detail_text
                ),
                CallbackQueryHandler(_news_main_cb, pattern=r"^menu:main$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _news_cancel)],
        name="news_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
