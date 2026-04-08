import re

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
from admin_keyboards import admin_main_keyboard, broadcast_confirm_keyboard
from config import ADMIN_IDS
from i18n import t

WAIT_TEXT, CONFIRM = range(2)


async def _edit_broadcast_reply(
    q, text: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Після попереднього перегляду з фото edit_message_text не працює — лише caption."""
    msg = q.message
    if msg and msg.photo:
        cap = text if len(text) <= 1024 else text[:1020] + "…"
        await q.edit_message_caption(caption=cap, reply_markup=reply_markup)
    else:
        await q.edit_message_text(text, reply_markup=reply_markup)


def _admin_only(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


async def broadcast_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not _admin_only(user.id if user else None):
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    context.user_data.pop("bc_text", None)
    context.user_data.pop("bc_photo_file_id", None)
    await q.edit_message_text(t("admin.broadcast_start"))
    return WAIT_TEXT


async def broadcast_cmd_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not _admin_only(user.id if user else None):
        if update.message:
            await update.message.reply_text(t("admin.access_denied"))
        return ConversationHandler.END
    args = context.args or []
    context.user_data.pop("bc_photo_file_id", None)
    if args:
        text = " ".join(args).strip()
        context.user_data["bc_text"] = text
        subs = await db.get_all_subscribers()
        context.user_data["bc_subs"] = subs
        preview = t(
            "admin.broadcast_preview",
            text=text,
            count=len(subs),
        )
        await update.message.reply_text(
            preview, reply_markup=broadcast_confirm_keyboard()
        )
        return CONFIRM
    await update.message.reply_text(t("admin.broadcast_start"))
    return WAIT_TEXT


async def broadcast_receive_content(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not _admin_only(user.id if user else None):
        return ConversationHandler.END
    msg = update.message
    if not msg:
        return WAIT_TEXT

    photo_id: str | None = None
    text_body = ""

    if msg.photo:
        photo_id = msg.photo[-1].file_id
        text_body = (msg.caption or "").strip()
    elif msg.text:
        text_body = msg.text.strip()
    else:
        return WAIT_TEXT

    context.user_data["bc_photo_file_id"] = photo_id
    context.user_data["bc_text"] = text_body
    subs = await db.get_all_subscribers()
    context.user_data["bc_subs"] = subs
    count = len(subs)

    if photo_id:
        cap = t(
            "admin.broadcast_preview_photo",
            text=text_body or t("admin.broadcast_no_caption"),
            count=count,
        )
        if len(cap) > 1024:
            cap = cap[:1020] + "…"
        await msg.reply_photo(
            photo=photo_id,
            caption=cap,
            reply_markup=broadcast_confirm_keyboard(),
        )
    else:
        preview = t(
            "admin.broadcast_preview",
            text=text_body,
            count=count,
        )
        await msg.reply_text(
            preview, reply_markup=broadcast_confirm_keyboard()
        )
    return CONFIRM


async def broadcast_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE, student_app
) -> int:
    user = update.effective_user
    if not _admin_only(user.id if user else None):
        return ConversationHandler.END
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "bc:no":
        await _edit_broadcast_reply(
            q, t("admin.upload_cancelled"), reply_markup=admin_main_keyboard()
        )
        context.user_data.pop("bc_text", None)
        context.user_data.pop("bc_photo_file_id", None)
        context.user_data.pop("bc_subs", None)
        return ConversationHandler.END
    text = context.user_data.get("bc_text") or ""
    photo_id = context.user_data.get("bc_photo_file_id")
    subs = context.user_data.get("bc_subs") or []
    if not text and not photo_id:
        await _edit_broadcast_reply(q, t("errors.generic"))
        return ConversationHandler.END
    if not subs:
        await _edit_broadcast_reply(
            q,
            t("admin.broadcast_empty_subscribers"),
            reply_markup=admin_main_keyboard(),
        )
        context.user_data.pop("bc_text", None)
        context.user_data.pop("bc_photo_file_id", None)
        context.user_data.pop("bc_subs", None)
        return ConversationHandler.END
    ok = 0
    errors = 0
    for row in subs:
        uid = int(row["user_id"])
        try:
            if photo_id:
                await student_app.bot.send_photo(
                    chat_id=uid,
                    photo=photo_id,
                    caption=text or "",
                )
            else:
                await student_app.bot.send_message(chat_id=uid, text=text)
            ok += 1
        except TelegramError:
            errors += 1
    await db.insert_broadcast(text, user.id, photo_file_id=photo_id)
    report = t(
        "admin.broadcast_sent",
        ok=ok,
        total=len(subs),
        errors=errors,
    )
    await _edit_broadcast_reply(
        q, report, reply_markup=admin_main_keyboard()
    )
    context.user_data.pop("bc_text", None)
    context.user_data.pop("bc_photo_file_id", None)
    context.user_data.pop("bc_subs", None)
    return ConversationHandler.END


async def broadcast_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not _admin_only(user.id if user else None):
        return ConversationHandler.END
    context.user_data.pop("bc_text", None)
    context.user_data.pop("bc_photo_file_id", None)
    context.user_data.pop("bc_subs", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def _fmt_news_admin_dt(val) -> str:
    from datetime import datetime

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


async def _render_news_manage_panel(q) -> None:
    rows = await db.get_recent_broadcasts(20)
    if not rows:
        await q.edit_message_text(
            t("admin.news_empty"),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=t("common.back"),
                            callback_data="adm:home",
                        )
                    ]
                ]
            ),
        )
        return
    lines = [t("admin.news_manage_title")]
    kb_rows: list[list[InlineKeyboardButton]] = []
    for r in rows:
        bid = int(r["id"])
        dt = _fmt_news_admin_dt(r.get("sent_at"))
        preview = (r.get("text") or "").strip().replace("\n", " ")
        if len(preview) > 48:
            preview = preview[:45] + "…"
        icon = "📷" if r.get("photo_file_id") else "📄"
        lines.append(f"{icon} #{bid} · {dt}\n   {preview or '—'}")
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=t("admin.news_delete_btn", id=bid),
                    callback_data=f"adm:newsdel:{bid}",
                )
            ]
        )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text=t("common.back"), callback_data="adm:home"
            )
        ]
    )
    await q.edit_message_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup(kb_rows),
    )


async def news_manage_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return
    if not _admin_only(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    await q.answer()
    await _render_news_manage_panel(q)


async def news_delete_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return
    if not _admin_only(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:newsdel:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    bid = int(m.group(1))
    await q.answer()
    await db.delete_broadcast(bid)
    await _render_news_manage_panel(q)


def register(app, student_app) -> None:
    async def confirm_wrap(u, c):
        return await broadcast_confirm(u, c, student_app)

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("broadcast", broadcast_cmd_entry),
            CallbackQueryHandler(broadcast_menu_cb, pattern=r"^adm:broadcast$"),
        ],
        states={
            WAIT_TEXT: [
                MessageHandler(
                    (filters.PHOTO | filters.TEXT) & ~filters.COMMAND,
                    broadcast_receive_content,
                )
            ],
            CONFIRM: [CallbackQueryHandler(confirm_wrap, pattern=r"^bc:(yes|no)$")],
        },
        fallbacks=[CommandHandler("cancel", broadcast_cancel)],
        name="broadcast_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(
        CallbackQueryHandler(news_manage_cb, pattern=r"^adm:news_manage$")
    )
    app.add_handler(
        CallbackQueryHandler(news_delete_cb, pattern=r"^adm:newsdel:\d+$")
    )
