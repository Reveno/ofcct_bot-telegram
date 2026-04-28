from io import BytesIO
import re

from telegram import (
    Bot,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
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
from config import ADMIN_IDS, BOT_TOKEN
from i18n import t

REQ_TEXT, REQ_PHOTO, BELLS_REG, BELLS_SHORT, COURSE_TITLE, COURSE_DESC, EDU_PHOTO = range(7)


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


async def _adapt_photo_for_student_bot(photo, preferred_chat_id: int | None) -> str:
    orig_file_id = photo.file_id
    try:
        tg_file = await photo.get_file()
        data = await tg_file.download_as_bytearray()
        student_bot = Bot(BOT_TOKEN)
        targets: list[int] = []
        if preferred_chat_id:
            targets.append(preferred_chat_id)
        for admin_id in ADMIN_IDS:
            if admin_id not in targets:
                targets.append(admin_id)
        for chat_id in targets:
            try:
                sent = await student_bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(BytesIO(data), filename="section_photo.jpg"),
                    caption="section cache",
                )
                try:
                    await student_bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
                except Exception:
                    pass
                if sent.photo:
                    return sent.photo[-1].file_id
            except Exception:
                continue
    except Exception:
        pass
    return orig_file_id


async def _panel_payload() -> tuple[str, InlineKeyboardMarkup]:
    vis = await db.get_menu_visibility_map()
    courses = await db.get_all_paid_courses()
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(t("admin.requisites_set_text"), callback_data="adm:sec:req_txt")],
        [InlineKeyboardButton(t("admin.requisites_set_photo"), callback_data="adm:sec:req_photo")],
        [InlineKeyboardButton(t("admin.bells_set_regular"), callback_data="adm:sec:bells_reg")],
        [InlineKeyboardButton(t("admin.bells_set_short"), callback_data="adm:sec:bells_short")],
        [InlineKeyboardButton(t("admin.courses_add"), callback_data="adm:sec:course_add")],
        [InlineKeyboardButton(t("admin.edu_set_photo"), callback_data="adm:sec:edu_photo")],
        [InlineKeyboardButton(text=t("admin.admissions_manage"), callback_data="adm:admissions")],
    ]
    for c in courses:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {str(c.get('title') or '')[:28]}",
                    callback_data=f"adm:sec:course_del:{int(c['id'])}",
                )
            ]
        )
    rows.append([InlineKeyboardButton("— Видимість розділів —", callback_data="adm:sec:noop")])
    sections = (
        ("schedule", "menu.schedule"),
        ("faq", "menu.faq"),
        ("feedback", "menu.feedback"),
        ("social", "menu.social"),
        ("retakes", "menu.retakes"),
        ("subscription", "menu.subscription"),
        ("news", "menu.news"),
        ("requisites", "menu.requisites"),
        ("bells", "menu.bells"),
        ("courses", "menu.courses"),
        ("edu_process", "menu.edu_process"),
        ("admissions", "menu.admissions"),
    )
    for key, label_key in sections:
        st = "✅" if vis.get(key, True) else "🚫"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{st} {t(label_key)}",
                    callback_data=f"adm:vis:{key}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=t("common.back"), callback_data="adm:home")])
    return t("admin.sections_panel_title"), InlineKeyboardMarkup(rows)


async def _render_panel(q) -> None:
    text, kb = await _panel_payload()
    await q.edit_message_text(text, reply_markup=kb)


async def sections_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    user = update.effective_user
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    await q.answer()
    await _render_panel(q)
    return ConversationHandler.END


async def sections_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not update.message or not _ok(user.id if user else None):
        if update.message and user and user.id not in ADMIN_IDS:
            await update.message.reply_text(t("admin.access_denied"))
        return
    text, kb = await _panel_payload()
    await update.message.reply_text(text, reply_markup=kb)


async def section_action_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()
    data = q.data or ""
    if data == "adm:sec:req_txt":
        await q.edit_message_text(t("admin.requisites_ask_text"))
        return REQ_TEXT
    if data == "adm:sec:req_photo":
        await q.edit_message_text(t("admin.requisites_ask_photo"))
        return REQ_PHOTO
    if data == "adm:sec:bells_reg":
        await q.edit_message_text(t("admin.bells_ask_regular"))
        return BELLS_REG
    if data == "adm:sec:bells_short":
        await q.edit_message_text(t("admin.bells_ask_short"))
        return BELLS_SHORT
    if data == "adm:sec:course_add":
        await q.edit_message_text(t("admin.courses_ask_title"))
        return COURSE_TITLE
    if data == "adm:sec:edu_photo":
        await q.edit_message_text(t("admin.edu_ask_photo"))
        return EDU_PHOTO
    return ConversationHandler.END


async def save_requisites_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return REQ_TEXT
    await db.upsert_info_page("requisites", text=update.message.text.strip())
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def save_requisites_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.photo:
        return REQ_PHOTO
    file_id = await _adapt_photo_for_student_bot(
        update.message.photo[-1],
        update.effective_user.id if update.effective_user else None,
    )
    await db.upsert_info_page("requisites", photo_file_id=file_id)
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def save_bells_regular(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return BELLS_REG
    await db.upsert_info_page("bells_regular", text=update.message.text.strip())
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def save_bells_short(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return BELLS_SHORT
    await db.upsert_info_page("bells_short", text=update.message.text.strip())
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def course_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return COURSE_TITLE
    context.user_data["course_title"] = update.message.text.strip()
    await update.message.reply_text(t("admin.courses_ask_desc"))
    return COURSE_DESC


async def course_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return COURSE_DESC
    title = str(context.user_data.get("course_title") or "").strip()
    desc = update.message.text.strip()
    if not title:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    oi = await db.get_next_paid_course_order_index()
    await db.insert_paid_course(title, desc, oi)
    context.user_data.pop("course_title", None)
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def save_edu_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.photo:
        return EDU_PHOTO
    file_id = await _adapt_photo_for_student_bot(
        update.message.photo[-1],
        update.effective_user.id if update.effective_user else None,
    )
    caption = (update.message.caption or "").strip()
    await db.upsert_info_page("edu_process", photo_file_id=file_id, text=caption)
    await update.message.reply_text(t("admin.social_saved"), reply_markup=admin_main_keyboard())
    return ConversationHandler.END


async def toggle_visibility_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    m = re.match(r"^adm:vis:([a-z_]+)$", q.data or "")
    if not m:
        await q.answer()
        return
    key = m.group(1)
    now = await db.is_menu_section_visible(key)
    await db.set_menu_section_visibility(key, not now)
    await q.answer(t("admin.social_saved"))
    await _render_panel(q)


async def delete_course_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q:
        return
    m = re.match(r"^adm:sec:course_del:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await db.delete_paid_course(int(m.group(1)))
    await q.answer(t("admin.faq_deleted"))
    await _render_panel(q)


async def noop_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if q:
        await q.answer()


async def sec_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("course_title", None)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"), reply_markup=admin_main_keyboard()
        )
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(
                section_action_start,
                pattern=r"^adm:sec:(req_txt|req_photo|bells_reg|bells_short|course_add|edu_photo)$",
            )
        ],
        states={
            REQ_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_requisites_text)],
            REQ_PHOTO: [MessageHandler(filters.PHOTO, save_requisites_photo)],
            BELLS_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_bells_regular)],
            BELLS_SHORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_bells_short)],
            COURSE_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_title)],
            COURSE_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, course_desc)],
            EDU_PHOTO: [MessageHandler(filters.PHOTO, save_edu_photo)],
        },
        fallbacks=[CommandHandler("cancel", sec_cancel)],
        name="sections_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(CallbackQueryHandler(sections_menu_cb, pattern=r"^adm:sections$"))
    app.add_handler(CallbackQueryHandler(toggle_visibility_cb, pattern=r"^adm:vis:[a-z_]+$"))
    app.add_handler(
        CallbackQueryHandler(delete_course_cb, pattern=r"^adm:sec:course_del:\d+$")
    )
    app.add_handler(CallbackQueryHandler(noop_cb, pattern=r"^adm:sec:noop$"))
    app.add_handler(conv)
