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
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    nav_reply_keyboard,
)

BELLS_NAV = 1


def _bells_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t("bells.tab_regular"), callback_data="bells:regular"),
                InlineKeyboardButton(t("bells.tab_short"), callback_data="bells:short"),
            ]
        ]
    )


async def _bells_text(kind: str) -> str:
    key = "bells_regular" if kind == "regular" else "bells_short"
    page = await db.get_info_page(key)
    txt = str(page.get("text") or "").strip()
    if txt:
        return txt
    return t("bells.empty")


async def _bells_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(t("menu.welcome"), reply_markup=await main_menu_reply_keyboard())
    return ConversationHandler.END


async def _bells_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("bells"):
        return ConversationHandler.END
    msg = update.effective_message
    if not msg:
        return ConversationHandler.END
    await msg.reply_text(
        t("bells.title") + "\n\n" + await _bells_text("regular"),
        reply_markup=_bells_kb(),
    )
    await msg.reply_text(t("bells.nav_hint"), reply_markup=nav_reply_keyboard())
    return BELLS_NAV


async def _bells_tab_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q:
        return BELLS_NAV
    await q.answer()
    kind = "regular" if (q.data or "") == "bells:regular" else "short"
    await q.edit_message_text(
        t("bells.title") + "\n\n" + await _bells_text(kind),
        reply_markup=_bells_kb(),
    )
    return BELLS_NAV


async def _bells_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return BELLS_NAV
    text = update.message.text.strip()
    if text in (t("common.back"), t("schedule.to_main_menu")):
        return await _bells_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return BELLS_NAV


async def _bells_cancel(
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
                & filters.Regex(main_menu_text_pattern("menu.bells")),
                _bells_open,
            ),
        ],
        states={
            BELLS_NAV: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, _bells_nav_text),
                CallbackQueryHandler(_bells_tab_cb, pattern=r"^bells:(regular|short)$"),
            ]
        },
        fallbacks=[CommandHandler("cancel", _bells_cancel)],
        name="bells_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
