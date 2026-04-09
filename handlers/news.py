import html
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes

import db
from i18n import t
from keyboards import back_to_menu_keyboard, news_list_keyboard


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


async def _news_list_payload() -> tuple[str, object]:
    rows = await db.get_recent_broadcasts(15)
    if not rows:
        return t("news.empty"), back_to_menu_keyboard()
    items = [(int(r["id"]), _news_title(r)) for r in rows]
    return t("news.list_title"), news_list_keyboard(items)


async def _show_news_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    text, kb = await _news_list_payload()
    await q.edit_message_text(text, reply_markup=kb)


async def open_news(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _show_news_list(update, context)


async def open_news_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    text, kb = await _news_list_payload()
    await update.message.reply_text(text, reply_markup=kb)


async def view_news_item(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    await q.answer()
    try:
        nid = int((q.data or "").split(":")[2])
    except (ValueError, IndexError):
        await q.edit_message_text(
            t("news.empty"), reply_markup=back_to_menu_keyboard()
        )
        return
    row = await db.get_broadcast_by_id(nid)
    if not row:
        await q.edit_message_text(
            t("news.empty"), reply_markup=back_to_menu_keyboard()
        )
        return
    text = _format_news_detail_html(row)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("news.back_to_list"), callback_data="news:list"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="menu:main"
                )
            ],
        ]
    )
    await q.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


def register(app) -> None:
    app.add_handler(
        CallbackQueryHandler(open_news, pattern=r"^(menu:news|news:list)$")
    )
    app.add_handler(
        CallbackQueryHandler(view_news_item, pattern=r"^news:v:\d+$")
    )
