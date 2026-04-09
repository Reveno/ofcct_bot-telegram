import html
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from admin_keyboards import admin_main_keyboard
from config import ADMIN_IDS
from i18n import t

N_TITLE, N_BODY, N_LINK, N_CONFIRM = range(4)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def _format_news_html(title: str, body: str, link_url: str | None) -> str:
    parts: list[str] = []
    if title.strip():
        parts.append(f"<b>{html.escape(title.strip())}</b>")
    parts.append(html.escape(body.strip()))
    if link_url and link_url.strip():
        u = link_url.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        parts.append(
            f'<a href="{html.escape(u)}">{html.escape(t("news.link_label"))}</a>'
        )
    return "\n\n".join(parts)


def _news_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.confirm"), callback_data="nc:yes"
                ),
                InlineKeyboardButton(text=t("common.abort"), callback_data="nc:no"),
            ]
        ]
    )


async def news_compose_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await q.edit_message_text(t("admin.news_compose_title"))
    return N_TITLE


async def news_receive_title(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return N_TITLE
    context.user_data["nc_title"] = update.message.text.strip()
    await update.message.reply_text(t("admin.news_compose_body"))
    return N_BODY


async def news_receive_body(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return N_BODY
    context.user_data["nc_body"] = update.message.text.strip()
    await update.message.reply_text(t("admin.news_compose_link"))
    return N_LINK


async def news_receive_link(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return N_LINK
    raw = update.message.text.strip()
    link: str | None = None
    if raw.lower() != "/skip":
        u = raw
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        p = urlparse(u)
        if not p.netloc:
            await update.message.reply_text(t("errors.generic"))
            return N_LINK
        link = raw.strip()
    context.user_data["nc_link"] = link
    subs = await db.get_all_subscribers()
    context.user_data["nc_subs"] = subs
    title = context.user_data.get("nc_title") or ""
    body = context.user_data.get("nc_body") or ""
    title_line = html.escape(title) if title.strip() else "—"
    body_line = html.escape(body) if body.strip() else "—"
    if link:
        u = link.strip()
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        link_line = (
            f'<a href="{html.escape(u)}">'
            f'{html.escape(t("news.link_label"))}</a>'
        )
    else:
        link_line = "—"
    preview = t(
        "admin.news_compose_preview",
        title=title_line,
        body=body_line,
        link_line=link_line,
        count=len(subs),
    )
    await update.message.reply_text(
        preview,
        parse_mode="HTML",
        reply_markup=_news_confirm_kb(),
    )
    return N_CONFIRM


async def news_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE, student_app
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        return ConversationHandler.END
    await q.answer()
    if (q.data or "") == "nc:no":
        context.user_data.pop("nc_title", None)
        context.user_data.pop("nc_body", None)
        context.user_data.pop("nc_link", None)
        context.user_data.pop("nc_subs", None)
        await q.edit_message_text(
            t("admin.upload_cancelled"), reply_markup=admin_main_keyboard()
        )
        return ConversationHandler.END

    title = (context.user_data.get("nc_title") or "").strip()
    body = (context.user_data.get("nc_body") or "").strip()
    link = context.user_data.get("nc_link")
    subs = context.user_data.get("nc_subs") or []
    if not body:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END

    inner = _format_news_html(title, body, link)
    html_msg = f"{t('news.push_heading')}\n\n{inner}"
    admin_chat_id = q.message.chat_id if q.message else None
    admin_message_id = q.message.message_id if q.message else None

    await q.edit_message_text(
        t("admin.broadcast_sending", total=len(subs)),
        reply_markup=admin_main_keyboard(),
    )

    async def _run() -> None:
        ok = 0
        err = 0
        for row in subs:
            uid = int(row["user_id"])
            try:
                await student_app.bot.send_message(
                    chat_id=uid,
                    text=html_msg,
                    parse_mode="HTML",
                )
                ok += 1
            except TelegramError:
                err += 1
            except Exception:
                err += 1
        try:
            await db.insert_broadcast(
                body,
                user.id,
                photo_file_id=None,
                title=title or None,
                link_url=link,
            )
        except Exception:
            pass
        rep = t(
            "admin.broadcast_sent",
            ok=ok,
            total=len(subs),
            errors=err,
        )
        try:
            if admin_chat_id and admin_message_id:
                await context.bot.edit_message_text(
                    chat_id=admin_chat_id,
                    message_id=admin_message_id,
                    text=rep,
                    reply_markup=admin_main_keyboard(),
                )
        except Exception:
            pass

    context.application.create_task(_run())
    context.user_data.pop("nc_title", None)
    context.user_data.pop("nc_body", None)
    context.user_data.pop("nc_link", None)
    context.user_data.pop("nc_subs", None)
    return ConversationHandler.END


async def news_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("nc_title", None)
    context.user_data.pop("nc_body", None)
    context.user_data.pop("nc_link", None)
    context.user_data.pop("nc_subs", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app, student_app) -> None:
    async def confirm_wrap(u, c):
        return await news_confirm(u, c, student_app)

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(news_compose_start, pattern=r"^adm:news_compose$")
        ],
        states={
            N_TITLE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, news_receive_title
                )
            ],
            N_BODY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, news_receive_body)
            ],
            N_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, news_receive_link)
            ],
            N_CONFIRM: [
                CallbackQueryHandler(confirm_wrap, pattern=r"^nc:(yes|no)$")
            ],
        },
        fallbacks=[CommandHandler("cancel", news_cancel)],
        name="news_compose_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
