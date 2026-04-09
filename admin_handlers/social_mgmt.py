import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

ADD_SOC_T, ADD_SOC_U, EDIT_SOC_T, EDIT_SOC_U = range(4)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


async def _social_menu_payload() -> tuple[str, InlineKeyboardMarkup]:
    rows = await db.get_all_social_links()
    lines = [t("admin.social_menu_title")]
    kb_rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=t("admin.social_add_btn"), callback_data="adm:soc_add"
            )
        ]
    ]
    for r in rows:
        lid = int(r["id"])
        title = (r.get("title") or "").strip()
        short = title if len(title) <= 28 else title[:25] + "…"
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"✏️ {short}",
                    callback_data=f"adm:soc_e:{lid}",
                ),
                InlineKeyboardButton(
                    text="🗑", callback_data=f"adm:soc_d:{lid}"
                ),
            ]
        )
    kb_rows.append(
        [
            InlineKeyboardButton(
                text=t("common.back"), callback_data="adm:home"
            )
        ]
    )
    return "\n\n".join(lines), InlineKeyboardMarkup(kb_rows)


async def _render_social_panel(q) -> None:
    text, kb = await _social_menu_payload()
    await q.edit_message_text(text, reply_markup=kb)


async def social_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not update.message or not _ok(user.id if user else None):
        if update.message and user and user.id not in ADMIN_IDS:
            await update.message.reply_text(t("admin.access_denied"))
        return
    text, kb = await _social_menu_payload()
    await update.message.reply_text(text, reply_markup=kb)


async def social_menu_cb(
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
    await _render_social_panel(q)
    return ConversationHandler.END


async def soc_add_start(
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
    await q.edit_message_text(t("admin.social_add_title"))
    return ADD_SOC_T


async def soc_add_receive_title(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ADD_SOC_T
    context.user_data["soc_new_title"] = update.message.text.strip()
    await update.message.reply_text(t("admin.social_add_url"))
    return ADD_SOC_U


async def soc_add_receive_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ADD_SOC_U
    title = (context.user_data.get("soc_new_title") or "").strip()
    url = update.message.text.strip()
    if not title or not url:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    oi = await db.get_next_social_order_index()
    await db.insert_social_link(title, url, oi)
    context.user_data.pop("soc_new_title", None)
    await update.message.reply_text(
        t("admin.social_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def soc_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    m = re.match(r"^adm:soc_e:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return ConversationHandler.END
    lid = int(m.group(1))
    row = await db.get_social_link_by_id(lid)
    if not row:
        await q.answer()
        return ConversationHandler.END
    await q.answer()
    context.user_data["soc_edit_id"] = lid
    await q.edit_message_text(
        t("admin.social_edit_title", title=row.get("title", ""))
    )
    return EDIT_SOC_T


async def soc_edit_receive_title(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return EDIT_SOC_T
    txt = update.message.text.strip()
    if txt.lower() != "/skip":
        context.user_data["soc_new_title"] = txt
    else:
        context.user_data.pop("soc_new_title", None)
    lid = int(context.user_data.get("soc_edit_id") or 0)
    row = await db.get_social_link_by_id(lid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    await update.message.reply_text(
        t("admin.social_edit_url", url=row.get("url", ""))
    )
    return EDIT_SOC_U


async def soc_edit_receive_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return EDIT_SOC_U
    txt = update.message.text.strip()
    lid = int(context.user_data.get("soc_edit_id") or 0)
    row = await db.get_social_link_by_id(lid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    new_title = (
        context.user_data["soc_new_title"]
        if "soc_new_title" in context.user_data
        else row.get("title")
    )
    if txt.lower() != "/skip":
        new_url = txt
    else:
        new_url = row.get("url")
    await db.update_social_link(lid, title=str(new_title or ""), url=str(new_url or ""))
    context.user_data.pop("soc_edit_id", None)
    context.user_data.pop("soc_new_title", None)
    await update.message.reply_text(
        t("admin.social_saved"), reply_markup=admin_main_keyboard()
    )
    return ConversationHandler.END


async def soc_delete_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:soc_d:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await q.answer()
    await db.delete_social_link(int(m.group(1)))
    await _render_social_panel(q)


async def soc_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("soc_new_title", None)
    context.user_data.pop("soc_edit_id", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(soc_add_start, pattern=r"^adm:soc_add$"),
            CallbackQueryHandler(soc_edit_start, pattern=r"^adm:soc_e:\d+$"),
        ],
        states={
            ADD_SOC_T: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, soc_add_receive_title
                )
            ],
            ADD_SOC_U: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, soc_add_receive_url
                )
            ],
            EDIT_SOC_T: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, soc_edit_receive_title
                )
            ],
            EDIT_SOC_U: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, soc_edit_receive_url
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", soc_cancel)],
        name="social_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(CallbackQueryHandler(social_menu_cb, pattern=r"^adm:social$"))
    app.add_handler(CallbackQueryHandler(soc_delete_cb, pattern=r"^adm:soc_d:\d+$"))
    app.add_handler(conv)
