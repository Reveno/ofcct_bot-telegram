import html
import os
import re
import tempfile

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import db
from admin_keyboards import (
    admin_main_reply_keyboard,
    consultations_submenu_actions_text_regex,
    consultations_submenu_reply_keyboard,
)
from config import ADMIN_IDS, admin_only
from i18n import t
from utils.consultations_parser import (
    parse_consultations_docx,
    parse_consultations_xlsx,
)
from utils.consultations_template import build_consultations_template_xlsx

(
    AD_COMMISSION_PICK,
    AD_COMMISSION_NEW,
    AD_TEACHER_PICK,
    AD_TEACHER_NEW,
    AD_PICK_DAY,
    AD_TIME,
    AD_ROOM,
    AD_SUBJECT,
    AD_NOTES,
    AD_CONFIRM,
) = range(10)
ED_TIME, ED_TEACHER, ED_ROOM, ED_SUBJECT, ED_NOTES = range(10, 15)
IMP_WAIT, IMP_CONFIRM = range(20, 22)
_CONS_UPLOAD_DOC = filters.Document.ALL


def _ok(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


def _clear_consultation_dialog_data(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("cons_new", None)
    context.user_data.pop("cons_import_rows", None)
    context.user_data.pop("cons_edit_id", None)
    for k in list(context.user_data.keys()):
        if k.startswith("cons_e_"):
            context.user_data.pop(k, None)


def _day_pick_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for d in range(1, 7):
        row.append(
            InlineKeyboardButton(
                text=t(f"days.short{d}"),
                callback_data=f"cons_pick:{d}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t("common.abort"), callback_data="cons_add:abort"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _commission_pick_keyboard(items: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for c in items:
        rows.append([InlineKeyboardButton(text=c, callback_data=f"cons_c:{c}")])
    rows.append([InlineKeyboardButton(text="➕ Нова ЦК", callback_data="cons_c:new")])
    rows.append([InlineKeyboardButton(text=t("common.abort"), callback_data="cons_add:abort")])
    return InlineKeyboardMarkup(rows)


def _teacher_pick_keyboard(items: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for name in items:
        rows.append([InlineKeyboardButton(text=name, callback_data=f"cons_t:{name}")])
    rows.append([InlineKeyboardButton(text="➕ Новий викладач", callback_data="cons_t:new")])
    rows.append([InlineKeyboardButton(text=t("common.back"), callback_data="cons_t:back")])
    rows.append([InlineKeyboardButton(text=t("common.abort"), callback_data="cons_add:abort")])
    return InlineKeyboardMarkup(rows)


def _slot_block(row: dict) -> str:
    commission = (row.get("commission") or "").strip() or "—"
    day = t(f"days.{int(row['day_of_week'])}")
    subj = (row.get("subject") or "").strip() or "—"
    notes = (row.get("notes") or "").strip() or t("consultations.notes_empty")
    return t(
        "consultations.admin_slot_block",
        commission=commission,
        day=day,
        time=row.get("time", ""),
        teacher=row.get("teacher", ""),
        room=row.get("room", ""),
        subject=subj,
        notes=notes,
    )


def _norm_slot_commission(r: dict) -> str:
    s = (r.get("commission") or "").strip()
    return s if s else "—"


def _norm_slot_teacher(r: dict) -> str:
    s = (r.get("teacher") or "").strip()
    return s if s else "—"


def _distinct_sorted_commissions(rows: list[dict]) -> list[str]:
    return sorted({_norm_slot_commission(r) for r in rows})


def _teachers_for_commission_key(rows: list[dict], commission_key: str) -> list[str]:
    return sorted(
        {
            _norm_slot_teacher(r)
            for r in rows
            if _norm_slot_commission(r) == commission_key
        }
    )


def _btn_label(s: str, max_len: int = 58) -> str:
    s = s.strip() or "—"
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _admin_commission_list_keyboard(commissions: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, c in enumerate(commissions):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_btn_label(c),
                    callback_data=f"adm:lc:c:{i}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin.cons_list_cancel"),
                callback_data="adm:lc:bx",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _admin_teacher_list_keyboard(
    commission_idx: int, teachers: list[str]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ti, name in enumerate(teachers):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_btn_label(name),
                    callback_data=f"adm:lc:t:{commission_idx}:{ti}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin.cons_list_back_cc"),
                callback_data="adm:lc:bc",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _admin_slot_line_compact(r: dict) -> str:
    subj = html.escape((r.get("subject") or "").strip() or "—")
    notes_raw = (r.get("notes") or "").strip() or t("consultations.notes_empty")
    notes = html.escape(notes_raw)
    return t(
        "admin.cons_list_slot_compact",
        id=r["id"],
        day=html.escape(t(f"days.{int(r['day_of_week'])}")),
        time=html.escape(str(r.get("time") or "")),
        room=html.escape(str(r.get("room") or "")),
        subject=subj,
        notes=notes,
    )


def _chunk_admin_slots_text(
    slots: list[dict], header: str, max_len: int = 3800
) -> list[tuple[list[dict], str]]:
    chunks: list[tuple[list[dict], str]] = []
    cur_slots: list[dict] = []
    cur = header.rstrip() + "\n\n"
    for s in slots:
        line = _admin_slot_line_compact(s) + "\n\n"
        if cur_slots and len(cur) + len(line) > max_len:
            chunks.append((cur_slots, cur.rstrip()))
            cur_slots = []
            cur = header.rstrip() + "\n\n"
        cur_slots.append(s)
        cur += line
    if cur_slots:
        chunks.append((cur_slots, cur.rstrip()))
    return chunks


def _admin_slots_chunk_keyboard(
    slot_ids: list[int], commission_idx: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for sid in slot_ids:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️",
                    callback_data=f"adm:cons_e:{sid}",
                ),
                InlineKeyboardButton(
                    text="🗑",
                    callback_data=f"consdel:{sid}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin.cons_list_back_teachers"),
                callback_data=f"adm:lc:b:{commission_idx}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


@admin_only
async def consultations_menu_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    await q.answer()
    await q.edit_message_text(
        t("admin.consultations") + "\n\n" + t("admin.consultations_panel_hint"),
        reply_markup=None,
    )
    await q.message.reply_text(
        t("admin.cons_reply_menu_note"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )


@admin_only
async def consultations_menu_from_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        t("admin.consultations")
        + "\n\n"
        + t("admin.consultations_panel_hint"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )


@admin_only
async def consultations_template_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    if not q or not q.message:
        return
    await q.answer()
    buf = build_consultations_template_xlsx()
    await q.message.reply_document(
        document=InputFile(buf, filename="shablon_konsultatsiy.xlsx"),
        caption=t("admin.cons_template_caption"),
    )
    await q.message.reply_text(
        t("admin.cons_reply_menu_note"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )


async def consultations_submenu_extras_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Шаблон / список / назад з reply-підменю (коли діалог консультацій неактивний)."""
    if not update.message or not update.message.text:
        return
    user = update.effective_user
    if not _ok(user.id if user else None):
        return
    txt = update.message.text.strip()
    if txt == t("admin.cons_template_btn"):
        buf = build_consultations_template_xlsx()
        await update.message.reply_document(
            document=InputFile(buf, filename="shablon_konsultatsiy.xlsx"),
            caption=t("admin.cons_template_caption"),
        )
    elif txt == t("admin.cons_list_btn"):
        await _send_consultations_list(update, context, edit=False)
    elif txt == t("admin.cons_back_btn"):
        await update.message.reply_text(
            t("admin.reply_menu_visible"),
            reply_markup=admin_main_reply_keyboard(),
        )


@admin_only
async def list_consultations_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _send_consultations_list(update, context, edit=False)


async def list_consultations_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        q = update.callback_query
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    q = update.callback_query
    await q.answer()
    await _send_consultations_list(update, context, edit=True, query=q)


async def _send_consultations_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    edit: bool,
    query=None,
) -> None:
    rows = await db.get_all_consultation_slots()
    if not rows:
        text = t("admin.cons_list_empty")
        if edit and query:
            await query.edit_message_text(text)
            await query.message.reply_text(
                t("admin.cons_reply_menu_note"),
                reply_markup=consultations_submenu_reply_keyboard(),
            )
        elif update.message:
            await update.message.reply_text(
                text, reply_markup=consultations_submenu_reply_keyboard()
            )
        return

    commissions = _distinct_sorted_commissions(rows)
    kb = _admin_commission_list_keyboard(commissions)
    title = t("admin.cons_list_pick_commission")
    if edit and query and query.message:
        await query.edit_message_text(title, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(title, reply_markup=kb)


async def admin_cons_list_pick_commission_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not user or user.id not in ADMIN_IDS:
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:lc:c:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await q.answer()
    ci = int(m.group(1))
    rows = await db.get_all_consultation_slots()
    commissions = _distinct_sorted_commissions(rows)
    if ci >= len(commissions):
        return
    com = commissions[ci]
    teachers = _teachers_for_commission_key(rows, com)
    if not teachers:
        await q.edit_message_text(
            t("admin.cons_list_none_for_teacher"),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=t("admin.cons_list_back_cc"),
                            callback_data="adm:lc:bc",
                        )
                    ]
                ]
            ),
        )
        return
    await q.edit_message_text(
        t("admin.cons_list_pick_teacher", commission=com),
        reply_markup=_admin_teacher_list_keyboard(ci, teachers),
    )


async def admin_cons_list_pick_teacher_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not q.message or not user or user.id not in ADMIN_IDS:
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:lc:t:(\d+):(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await q.answer()
    ci, ti = int(m.group(1)), int(m.group(2))
    rows = await db.get_all_consultation_slots()
    commissions = _distinct_sorted_commissions(rows)
    if ci >= len(commissions):
        return
    com = commissions[ci]
    teachers = _teachers_for_commission_key(rows, com)
    if ti >= len(teachers):
        return
    teach = teachers[ti]
    slots = [
        r
        for r in rows
        if _norm_slot_commission(r) == com and _norm_slot_teacher(r) == teach
    ]
    if not slots:
        await q.edit_message_text(
            t("admin.cons_list_none_for_teacher"),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=t("admin.cons_list_back_teachers"),
                            callback_data=f"adm:lc:b:{ci}",
                        )
                    ]
                ]
            ),
        )
        return

    header_html = t(
        "admin.cons_list_slots_header",
        commission=html.escape(com),
        teacher=html.escape(teach),
    )
    chunks = _chunk_admin_slots_text(slots, header_html)
    chat_id = q.message.chat_id
    first_ids = [int(s["id"]) for s in chunks[0][0]]
    await q.edit_message_text(
        chunks[0][1],
        reply_markup=_admin_slots_chunk_keyboard(first_ids, ci),
        parse_mode=ParseMode.HTML,
    )
    for chunk_slots, chunk_text in chunks[1:]:
        ids = [int(s["id"]) for s in chunk_slots]
        await context.bot.send_message(
            chat_id=chat_id,
            text=chunk_text,
            reply_markup=_admin_slots_chunk_keyboard(ids, ci),
            parse_mode=ParseMode.HTML,
        )


async def admin_cons_list_back_commissions_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not user or user.id not in ADMIN_IDS:
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    await q.answer()
    rows = await db.get_all_consultation_slots()
    if not rows:
        await q.edit_message_text(t("admin.cons_list_empty"))
        return
    commissions = _distinct_sorted_commissions(rows)
    await q.edit_message_text(
        t("admin.cons_list_pick_commission"),
        reply_markup=_admin_commission_list_keyboard(commissions),
    )


async def admin_cons_list_back_teachers_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not user or user.id not in ADMIN_IDS:
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    m = re.match(r"^adm:lc:b:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return
    await q.answer()
    ci = int(m.group(1))
    rows = await db.get_all_consultation_slots()
    commissions = _distinct_sorted_commissions(rows)
    if ci >= len(commissions):
        return
    com = commissions[ci]
    teachers = _teachers_for_commission_key(rows, com)
    await q.edit_message_text(
        t("admin.cons_list_pick_teacher", commission=com),
        reply_markup=_admin_teacher_list_keyboard(ci, teachers),
    )


async def admin_cons_list_cancel_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    q = update.callback_query
    user = update.effective_user
    if not q or not q.message or not user or user.id not in ADMIN_IDS:
        if q:
            await q.answer(t("admin.access_denied_short"), show_alert=True)
        return
    await q.answer()
    await q.edit_message_text(t("admin.change_cancelled"))
    await q.message.reply_text(
        t("admin.cons_reply_menu_note"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )


async def delete_consultation_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or user.id not in ADMIN_IDS:
        if update.callback_query:
            await update.callback_query.answer(
                t("admin.access_denied_short"), show_alert=True
            )
        return
    q = update.callback_query
    await q.answer()
    m = re.match(r"^consdel:(\d+)$", q.data or "")
    if not m:
        return
    await db.delete_consultation_slot(int(m.group(1)))
    await q.edit_message_text(t("admin.cons_deleted"))


# --- import consultations ---


async def cons_import_start(
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
    await q.edit_message_text(t("admin.cons_import_prompt"))
    return IMP_WAIT


async def cons_import_start_from_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not update.message or not _ok(user.id if user else None):
        return ConversationHandler.END
    await update.message.reply_text(t("admin.cons_import_prompt"))
    return IMP_WAIT


async def cons_import_remind_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message and update.message.text:
        await update.message.reply_text(t("admin.cons_import_expect_file"))
    return IMP_WAIT


async def cons_import_receive_doc(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.document:
        return IMP_WAIT
    doc = update.message.document
    fn = (doc.file_name or "").lower()
    if not (fn.endswith(".xlsx") or fn.endswith(".docx")):
        await update.message.reply_text(t("admin.cons_import_wrong_ext"))
        return IMP_WAIT
    tg_file = await doc.get_file()
    ext = ".xlsx" if fn.endswith(".xlsx") else ".docx"
    tmp = os.path.join(
        tempfile.gettempdir(), f"consultations_{update.message.message_id}{ext}"
    )
    try:
        await tg_file.download_to_drive(custom_path=tmp)
    except Exception:
        await update.message.reply_text(t("errors.download_failed"))
        return IMP_WAIT

    try:
        parsed = (
            parse_consultations_xlsx(tmp)
            if ext == ".xlsx"
            else parse_consultations_docx(tmp)
        )
    except Exception:
        if os.path.isfile(tmp):
            os.remove(tmp)
        await update.message.reply_text(t("errors.parse_failed"))
        return IMP_WAIT
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)

    if not parsed:
        await update.message.reply_text(t("admin.cons_import_no_rows"))
        return IMP_WAIT

    context.user_data["cons_import_rows"] = parsed
    await update.message.reply_text(
        t("admin.cons_import_found", count=len(parsed)),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(text=t("common.confirm"), callback_data="cons_imp:yes"),
                    InlineKeyboardButton(text=t("common.abort"), callback_data="cons_imp:no"),
                ]
            ]
        ),
    )
    return IMP_CONFIRM


async def cons_import_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    await q.answer()
    if (q.data or "").endswith(":no"):
        context.user_data.pop("cons_import_rows", None)
        await q.edit_message_text(t("admin.change_cancelled"))
        await q.message.reply_text(
            t("admin.cons_reply_menu_note"),
            reply_markup=consultations_submenu_reply_keyboard(),
        )
        return ConversationHandler.END
    rows = context.user_data.pop("cons_import_rows", []) or []
    if not rows:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END
    inserted = 0
    for row in rows:
        row["sort_order"] = await db.get_next_consultation_order_index()
        await db.insert_consultation_slot(row)
        inserted += 1
    await q.edit_message_text(
        t("admin.cons_import_done", inserted=inserted),
    )
    await q.message.reply_text(
        t("admin.cons_reply_menu_note"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )
    return ConversationHandler.END


# --- add conversation ---


async def cons_add_start(
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
    context.user_data.pop("cons_new", None)
    commissions = await db.get_distinct_consultation_commissions()
    await q.edit_message_text(
        "Оберіть ЦК для консультації:",
        reply_markup=_commission_pick_keyboard(commissions),
    )
    return AD_COMMISSION_PICK


async def cons_add_start_from_reply(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not update.message or not _ok(user.id if user else None):
        return ConversationHandler.END
    context.user_data.pop("cons_new", None)
    commissions = await db.get_distinct_consultation_commissions()
    await update.message.reply_text(
        "Оберіть ЦК для консультації:",
        reply_markup=_commission_pick_keyboard(commissions),
    )
    return AD_COMMISSION_PICK


async def cons_pick_commission(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q:
        return ConversationHandler.END
    if not _ok(user.id if user else None):
        await q.answer(t("admin.access_denied_short"), show_alert=True)
        return ConversationHandler.END
    if (q.data or "") == "cons_add:abort":
        await q.answer()
        context.user_data.pop("cons_new", None)
        await q.edit_message_text(t("admin.change_cancelled"))
        await q.message.reply_text(
            t("admin.cons_reply_menu_note"),
            reply_markup=consultations_submenu_reply_keyboard(),
        )
        return ConversationHandler.END
    data = q.data or ""
    if data == "cons_c:new":
        await q.edit_message_text("Введіть назву ЦК:")
        return AD_COMMISSION_NEW
    m = re.match(r"^cons_c:(.+)$", data)
    if not m:
        await q.answer()
        return AD_COMMISSION_PICK
    commission = m.group(1).strip()
    context.user_data["cons_new"] = {"commission": commission}
    teachers = await db.get_teachers_by_consultation_commission(commission)
    await q.edit_message_text(
        f"Оберіть викладача з ЦК «{commission}»:",
        reply_markup=_teacher_pick_keyboard(teachers),
    )
    return AD_TEACHER_PICK


async def cons_new_commission_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_COMMISSION_NEW
    commission = update.message.text.strip()
    if not commission:
        return AD_COMMISSION_NEW
    context.user_data["cons_new"] = {"commission": commission}
    await update.message.reply_text("Введіть ПІБ викладача:")
    return AD_TEACHER_NEW


async def cons_pick_teacher(
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
    data = q.data or ""
    if data == "cons_t:back":
        commissions = await db.get_distinct_consultation_commissions()
        await q.edit_message_text(
            "Оберіть ЦК для консультації:",
            reply_markup=_commission_pick_keyboard(commissions),
        )
        return AD_COMMISSION_PICK
    if data == "cons_t:new":
        await q.edit_message_text("Введіть ПІБ викладача:")
        return AD_TEACHER_NEW
    m = re.match(r"^cons_t:(.+)$", data)
    if not m:
        return AD_TEACHER_PICK
    context.user_data.setdefault("cons_new", {})["teacher"] = m.group(1).strip()
    await q.message.reply_text(
        t("admin.cons_pick_day"),
        reply_markup=_day_pick_keyboard(),
    )
    return AD_PICK_DAY


async def cons_new_teacher_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_TEACHER_NEW
    context.user_data.setdefault("cons_new", {})["teacher"] = update.message.text.strip()
    await update.message.reply_text(
        t("admin.cons_pick_day"),
        reply_markup=_day_pick_keyboard(),
    )
    return AD_PICK_DAY


async def cons_pick_day(
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
    m = re.match(r"^cons_pick:(\d+)$", q.data or "")
    if not m:
        return AD_PICK_DAY
    day = int(m.group(1))
    context.user_data.setdefault("cons_new", {})["day_of_week"] = day
    await q.message.reply_text(t("admin.cons_time"))
    return AD_TIME


async def cons_add_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_TIME
    context.user_data.setdefault("cons_new", {})["time"] = update.message.text.strip()
    await update.message.reply_text(t("admin.cons_room"))
    return AD_ROOM


async def cons_add_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_ROOM
    context.user_data["cons_new"]["room"] = update.message.text.strip()
    await update.message.reply_text(t("admin.cons_subject_skip"))
    return AD_SUBJECT


async def cons_add_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_SUBJECT
    raw = update.message.text.strip()
    context.user_data["cons_new"]["subject"] = "" if raw.lower() == "/skip" else raw
    await update.message.reply_text(t("admin.cons_notes_skip"))
    return AD_NOTES


async def cons_add_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return AD_NOTES
    raw = update.message.text.strip()
    notes = None if raw.lower() == "/skip" else raw
    context.user_data["cons_new"]["notes"] = notes
    data = context.user_data["cons_new"]
    block = _slot_block(
        {
            "commission": data.get("commission", ""),
            "day_of_week": data["day_of_week"],
            "time": data["time"],
            "teacher": data["teacher"],
            "room": data["room"],
            "subject": data.get("subject", ""),
            "notes": notes or "",
        }
    )
    await update.message.reply_text(
        t("admin.cons_preview", block=block),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=t("common.confirm"), callback_data="cons_save:yes"
                    ),
                    InlineKeyboardButton(
                        text=t("common.abort"), callback_data="cons_save:no"
                    ),
                ]
            ]
        ),
    )
    return AD_CONFIRM


async def cons_add_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q or not _ok(user.id if user else None):
        return ConversationHandler.END
    await q.answer()
    if (q.data or "").endswith(":no"):
        await q.edit_message_text(t("admin.change_cancelled"))
        context.user_data.pop("cons_new", None)
        await q.message.reply_text(
            t("admin.cons_reply_menu_note"),
            reply_markup=consultations_submenu_reply_keyboard(),
        )
        return ConversationHandler.END
    data = context.user_data.get("cons_new") or {}
    if not data:
        await q.edit_message_text(t("errors.generic"))
        return ConversationHandler.END
    data["sort_order"] = await db.get_next_consultation_order_index()
    await db.insert_consultation_slot(data)
    context.user_data.pop("cons_new", None)
    await q.edit_message_text(t("admin.cons_saved"))
    await q.message.reply_text(
        t("admin.cons_reply_menu_note"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )
    return ConversationHandler.END


# --- edit conversation ---


async def cons_edit_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    q = update.callback_query
    if not q or not _ok(user.id if user else None):
        return ConversationHandler.END
    m = re.match(r"^adm:cons_e:(\d+)$", q.data or "")
    if not m:
        await q.answer()
        return ConversationHandler.END
    sid = int(m.group(1))
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await q.answer()
        return ConversationHandler.END
    await q.answer()
    context.user_data["cons_edit_id"] = sid
    await q.message.reply_text(
        t("admin.cons_edit_time", time=row.get("time", ""))
    )
    return ED_TIME


async def cons_edit_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_TIME
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_time"] = txt
    else:
        context.user_data.pop("cons_e_time", None)
    await update.message.reply_text(
        t("admin.cons_edit_teacher", teacher=row.get("teacher", ""))
    )
    return ED_TEACHER


async def cons_edit_teacher(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_TEACHER
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_teacher"] = txt
    else:
        context.user_data.pop("cons_e_teacher", None)
    await update.message.reply_text(
        t("admin.cons_edit_room", room=row.get("room", ""))
    )
    return ED_ROOM


async def cons_edit_room(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_ROOM
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_room"] = txt
    else:
        context.user_data.pop("cons_e_room", None)
    await update.message.reply_text(
        t("admin.cons_edit_subject", subject=row.get("subject", "") or "—")
    )
    return ED_SUBJECT


async def cons_edit_subject(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_SUBJECT
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END
    if txt.lower() != "/skip":
        context.user_data["cons_e_subject"] = txt
    else:
        context.user_data.pop("cons_e_subject", None)
    await update.message.reply_text(
        t("admin.cons_edit_notes", notes=row.get("notes") or "—")
    )
    return ED_NOTES


async def cons_edit_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return ED_NOTES
    txt = update.message.text.strip()
    sid = int(context.user_data.get("cons_edit_id") or 0)
    row = await db.get_consultation_slot_by_id(sid)
    if not row:
        await update.message.reply_text(t("errors.generic"))
        return ConversationHandler.END

    time_v = context.user_data.get("cons_e_time", row.get("time", ""))
    teacher_v = context.user_data.get("cons_e_teacher", row.get("teacher", ""))
    room_v = context.user_data.get("cons_e_room", row.get("room", ""))
    if "cons_e_subject" in context.user_data:
        subj_v = context.user_data["cons_e_subject"]
    else:
        subj_v = row.get("subject") or ""

    if txt.lower() != "/skip":
        notes_v: str | None = txt
    else:
        notes_v = row.get("notes")
        if notes_v is not None:
            notes_v = str(notes_v)

    await db.update_consultation_slot(
        sid,
        commission=str(row.get("commission") or ""),
        day_of_week=int(row["day_of_week"]),
        time=str(time_v),
        teacher=str(teacher_v),
        room=str(room_v),
        subject=str(subj_v),
        notes=notes_v,
    )
    context.user_data.pop("cons_edit_id", None)
    for k in list(context.user_data.keys()):
        if k.startswith("cons_e_"):
            context.user_data.pop(k, None)
    await update.message.reply_text(
        t("admin.cons_saved"),
        reply_markup=consultations_submenu_reply_keyboard(),
    )
    return ConversationHandler.END


async def cons_conv_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_consultation_dialog_data(context)
    if update.message:
        await update.message.reply_text(
            t("admin.conversation_cancelled"),
            reply_markup=consultations_submenu_reply_keyboard(),
        )
    return ConversationHandler.END


async def cons_reply_back_fallback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_consultation_dialog_data(context)
    if update.message:
        await update.message.reply_text(
            t("admin.reply_menu_visible"),
            reply_markup=admin_main_reply_keyboard(),
        )
    return ConversationHandler.END


def register(app) -> None:
    back_tx = filters.Regex("^" + re.escape(t("admin.cons_back_btn")) + "$")
    add_tx = filters.Regex("^" + re.escape(t("admin.cons_add_btn")) + "$")
    imp_tx = filters.Regex("^" + re.escape(t("admin.cons_import_btn")) + "$")
    extras_f = filters.Regex(consultations_submenu_actions_text_regex())
    text_no_cmd = filters.TEXT & ~filters.COMMAND

    app.add_handler(
        CallbackQueryHandler(
            consultations_template_cb, pattern=r"^adm:cons_template$"
        )
    )
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(cons_add_start, pattern=r"^adm:cons_add$"),
            MessageHandler(
                filters.ChatType.PRIVATE & text_no_cmd & add_tx,
                cons_add_start_from_reply,
            ),
            CallbackQueryHandler(cons_edit_start, pattern=r"^adm:cons_e:\d+$"),
            CallbackQueryHandler(cons_import_start, pattern=r"^adm:cons_import$"),
            MessageHandler(
                filters.ChatType.PRIVATE & text_no_cmd & imp_tx,
                cons_import_start_from_reply,
            ),
        ],
        states={
            AD_COMMISSION_PICK: [
                CallbackQueryHandler(cons_pick_commission, pattern=r"^cons_c:.*$"),
                CallbackQueryHandler(cons_pick_commission, pattern=r"^cons_add:abort$"),
            ],
            AD_COMMISSION_NEW: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_new_commission_text),
            ],
            AD_TEACHER_PICK: [
                CallbackQueryHandler(cons_pick_teacher, pattern=r"^cons_t:.*$"),
                CallbackQueryHandler(cons_pick_teacher, pattern=r"^cons_add:abort$"),
            ],
            AD_TEACHER_NEW: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_new_teacher_text),
            ],
            AD_PICK_DAY: [
                CallbackQueryHandler(cons_pick_day, pattern=r"^cons_pick:\d+$"),
                CallbackQueryHandler(cons_pick_day, pattern=r"^cons_add:abort$"),
            ],
            AD_TIME: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_add_time),
            ],
            AD_ROOM: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_add_room),
            ],
            AD_SUBJECT: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_add_subject),
            ],
            AD_NOTES: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_add_notes),
            ],
            AD_CONFIRM: [
                CallbackQueryHandler(
                    cons_add_confirm, pattern=r"^cons_save:(yes|no)$"
                )
            ],
            ED_TIME: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_edit_time),
            ],
            ED_TEACHER: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_edit_teacher),
            ],
            ED_ROOM: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_edit_room),
            ],
            ED_SUBJECT: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_edit_subject),
            ],
            ED_NOTES: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(text_no_cmd, cons_edit_notes),
            ],
            IMP_WAIT: [
                MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
                MessageHandler(_CONS_UPLOAD_DOC, cons_import_receive_doc),
                MessageHandler(text_no_cmd, cons_import_remind_file),
            ],
            IMP_CONFIRM: [
                CallbackQueryHandler(cons_import_confirm, pattern=r"^cons_imp:(yes|no)$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cons_conv_cancel),
            MessageHandler(filters.ChatType.PRIVATE & text_no_cmd & back_tx, cons_reply_back_fallback),
        ],
        name="consultation_mgmt_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
    app.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & text_no_cmd & extras_f,
            consultations_submenu_extras_handler,
        )
    )
    app.add_handler(
        CallbackQueryHandler(consultations_menu_cb, pattern=r"^adm:consultations$")
    )
    app.add_handler(
        CallbackQueryHandler(consultations_menu_cb, pattern=r"^adm:retakes$")
    )
    app.add_handler(
        CallbackQueryHandler(list_consultations_cb, pattern=r"^adm:cons_list$")
    )
    app.add_handler(
        CallbackQueryHandler(
            admin_cons_list_pick_commission_cb, pattern=r"^adm:lc:c:\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            admin_cons_list_pick_teacher_cb, pattern=r"^adm:lc:t:\d+:\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            admin_cons_list_back_teachers_cb, pattern=r"^adm:lc:b:\d+$"
        )
    )
    app.add_handler(
        CallbackQueryHandler(admin_cons_list_back_commissions_cb, pattern=r"^adm:lc:bc$")
    )
    app.add_handler(
        CallbackQueryHandler(admin_cons_list_cancel_cb, pattern=r"^adm:lc:bx$")
    )
    app.add_handler(
        CommandHandler("listconsultations", list_consultations_cmd)
    )
    app.add_handler(
        CommandHandler("listretakes", list_consultations_cmd)
    )
    app.add_handler(
        CallbackQueryHandler(delete_consultation_cb, pattern=r"^consdel:\d+$")
    )
