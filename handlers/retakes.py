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
from i18n import t
from keyboards import (
    main_menu_reply_keyboard,
    main_menu_text_pattern,
    nav_reply_keyboard,
)

RETAKES_NAV = 1


def _back_label() -> str:
    return t("common.back")


def _menu_label() -> str:
    return t("schedule.to_main_menu")


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


def _split_telegram_chunks(text: str, max_len: int = 4000) -> list[str]:
    text = text.strip()
    if len(text) <= max_len:
        return [text] if text else []
    parts: list[str] = []
    paras = text.split("\n\n")
    cur = ""
    for p in paras:
        candidate = p if not cur else cur + "\n\n" + p
        if len(candidate) <= max_len:
            cur = candidate
        else:
            if cur:
                parts.append(cur)
            if len(p) > max_len:
                for i in range(0, len(p), max_len):
                    parts.append(p[i : i + max_len])
                cur = ""
            else:
                cur = p
    if cur:
        parts.append(cur)
    return parts


def _student_commission_keyboard(commissions: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, c in enumerate(commissions):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_btn_label(c),
                    callback_data=f"retlc:c:{i}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("consultations.student_show_all"),
                callback_data="retlc:all",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _student_teacher_keyboard(commission_idx: int, teachers: list[str]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for ti, name in enumerate(teachers):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_btn_label(name),
                    callback_data=f"retlc:t:{commission_idx}:{ti}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("admin.cons_list_back_cc"),
                callback_data="retlc:bc",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _student_back_cc_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.cons_list_back_cc"),
                    callback_data="retlc:bc",
                )
            ]
        ]
    )


async def _build_retakes_full_text() -> str:
    slots = await db.get_all_consultation_slots()
    legacy = await db.get_all_retakes()
    if not slots and not legacy:
        return ""
    parts: list[str] = []
    if slots:
        parts.append(t("consultations.weekly_header"))
        for s in slots:
            dow = int(s["day_of_week"])
            subj = (s.get("subject") or "").strip() or "—"
            notes = (s.get("notes") or "").strip() or t("retakes.notes_empty")
            commission = (s.get("commission") or "").strip() or "—"
            parts.append(
                t(
                    "consultations.weekly_slot",
                    commission=commission,
                    day=t(f"days.{dow}"),
                    time=s.get("time", ""),
                    room=s.get("room", ""),
                    teacher=s.get("teacher", ""),
                    subject=subj,
                    notes=notes,
                )
            )
    if legacy:
        parts.append(t("consultations.legacy_header"))
        for r in legacy:
            notes = r.get("notes") or t("retakes.notes_empty")
            parts.append(
                t(
                    "retakes.entry",
                    date=r.get("date", ""),
                    time=r.get("time", ""),
                    room=r.get("room", ""),
                    subject=r.get("subject", ""),
                    teacher=r.get("teacher", ""),
                    notes=notes,
                )
            )
    return "\n\n".join(parts)


async def _retakes_end_main(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.effective_message
    if msg:
        await msg.reply_text(
            t("menu.welcome"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _retakes_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not await db.is_menu_section_visible("retakes"):
        return ConversationHandler.END
    q = update.callback_query
    if q:
        await q.answer()

    slots = await db.get_all_consultation_slots()
    legacy = await db.get_all_retakes()

    if not slots and not legacy:
        body = t("retakes.empty")
        if update.message:
            await update.message.reply_text(
                body,
                reply_markup=nav_reply_keyboard(),
            )
        elif q and q.message:
            await q.message.reply_text(
                body,
                reply_markup=nav_reply_keyboard(),
            )
        return RETAKES_NAV

    if not slots and legacy:
        parts: list[str] = [t("consultations.legacy_header")]
        for r in legacy:
            notes = r.get("notes") or t("retakes.notes_empty")
            parts.append(
                t(
                    "retakes.entry",
                    date=r.get("date", ""),
                    time=r.get("time", ""),
                    room=r.get("room", ""),
                    subject=r.get("subject", ""),
                    teacher=r.get("teacher", ""),
                    notes=notes,
                )
            )
        text = "\n\n".join(parts)
        chunks = _split_telegram_chunks(text, 4000)
        if not chunks:
            return RETAKES_NAV
        total = len(chunks)
        if q and q.message:
            chat_id = q.message.chat_id
            for i, ch in enumerate(chunks):
                suf = (
                    "\n\n"
                    + t("consultations.student_part", n=i + 1, total=total)
                    if total > 1
                    else ""
                )
                kb = _student_back_cc_keyboard() if i == total - 1 else None
                if i == 0:
                    try:
                        await q.edit_message_text(ch + suf, reply_markup=kb)
                    except Exception:
                        await q.message.reply_text(ch + suf, reply_markup=kb)
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=ch + suf,
                        reply_markup=kb,
                    )
        elif update.message:
            for i, ch in enumerate(chunks):
                suf = (
                    "\n\n"
                    + t("consultations.student_part", n=i + 1, total=total)
                    if total > 1
                    else ""
                )
                kb = _student_back_cc_keyboard() if i == total - 1 else None
                await update.message.reply_text(ch + suf, reply_markup=kb)
        return RETAKES_NAV

    commissions = _distinct_sorted_commissions(slots)
    title = t("consultations.student_pick_cc")
    kb = _student_commission_keyboard(commissions)

    if update.message:
        await update.message.reply_text(title, reply_markup=kb)
    elif q and q.message:
        try:
            await q.edit_message_text(title, reply_markup=kb)
        except Exception:
            await q.message.reply_text(title, reply_markup=kb)
    return RETAKES_NAV


async def _retakes_pick_commission_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q:
        return RETAKES_NAV
    await q.answer()
    m = re.match(r"^retlc:c:(\d+)$", q.data or "")
    if not m:
        return RETAKES_NAV
    ci = int(m.group(1))
    slots = await db.get_all_consultation_slots()
    commissions = _distinct_sorted_commissions(slots)
    if ci >= len(commissions):
        return RETAKES_NAV
    com = commissions[ci]
    teachers = _teachers_for_commission_key(slots, com)
    if not teachers:
        await q.edit_message_text(
            t("retakes.empty"),
            reply_markup=_student_back_cc_keyboard(),
        )
        return RETAKES_NAV
    await q.edit_message_text(
        t("consultations.student_pick_teacher", commission=com),
        reply_markup=_student_teacher_keyboard(ci, teachers),
    )
    return RETAKES_NAV


async def _retakes_pick_teacher_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q or not q.message:
        return RETAKES_NAV
    await q.answer()
    m = re.match(r"^retlc:t:(\d+):(\d+)$", q.data or "")
    if not m:
        return RETAKES_NAV
    ci, ti = int(m.group(1)), int(m.group(2))
    slots = await db.get_all_consultation_slots()
    commissions = _distinct_sorted_commissions(slots)
    if ci >= len(commissions):
        return RETAKES_NAV
    com = commissions[ci]
    teachers = _teachers_for_commission_key(slots, com)
    if ti >= len(teachers):
        return RETAKES_NAV
    teach = teachers[ti]
    chosen = [
        s
        for s in slots
        if _norm_slot_commission(s) == com and _norm_slot_teacher(s) == teach
    ]
    header = t("consultations.student_slots_header", commission=com, teacher=teach)
    blocks: list[str] = []
    for s in chosen:
        dow = int(s["day_of_week"])
        subj = (s.get("subject") or "").strip() or "—"
        notes = (s.get("notes") or "").strip() or t("retakes.notes_empty")
        blocks.append(
            t(
                "consultations.weekly_slot",
                commission=com,
                day=t(f"days.{dow}"),
                time=s.get("time", ""),
                room=s.get("room", ""),
                teacher=teach,
                subject=subj,
                notes=notes,
            )
        )
    body = "\n\n".join(blocks)
    chunks = _split_telegram_chunks(body, 3800)
    chat_id = q.message.chat_id
    if not chunks:
        await q.edit_message_text(
            t("retakes.empty"),
            reply_markup=_student_teacher_keyboard(ci, teachers),
        )
        return RETAKES_NAV
    total = len(chunks)
    for i, ch in enumerate(chunks):
        suffix = (
            "\n\n" + t("consultations.student_part", n=i + 1, total=total)
            if total > 1
            else ""
        )
        block = (header + "\n\n" + ch + suffix) if i == 0 else (ch + suffix)
        kb = (
            _student_teacher_keyboard(ci, teachers)
            if i == total - 1
            else None
        )
        if i == 0:
            await q.edit_message_text(block, reply_markup=kb)
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=block,
                reply_markup=kb,
            )
    return RETAKES_NAV


async def _retakes_back_commissions_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q:
        return RETAKES_NAV
    await q.answer()
    slots = await db.get_all_consultation_slots()
    if not slots:
        return await _retakes_open(update, context)
    commissions = _distinct_sorted_commissions(slots)
    await q.edit_message_text(
        t("consultations.student_pick_cc"),
        reply_markup=_student_commission_keyboard(commissions),
    )
    return RETAKES_NAV


async def _retakes_show_all_cb(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    q = update.callback_query
    if not q or not q.message:
        return RETAKES_NAV
    await q.answer()
    full = await _build_retakes_full_text()
    if not full.strip():
        await q.edit_message_text(
            t("retakes.empty"),
            reply_markup=_student_back_cc_keyboard(),
        )
        return RETAKES_NAV
    chunks = _split_telegram_chunks(full, 4000)
    if not chunks:
        return RETAKES_NAV
    chat_id = q.message.chat_id
    total = len(chunks)
    for i, ch in enumerate(chunks):
        suf = (
            "\n\n" + t("consultations.student_part", n=i + 1, total=total)
            if total > 1
            else ""
        )
        kb = _student_back_cc_keyboard() if i == total - 1 else None
        if i == 0:
            await q.edit_message_text(ch + suf, reply_markup=kb)
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=ch + suf,
                reply_markup=kb,
            )
    return RETAKES_NAV


async def _retakes_nav_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if not update.message or not update.message.text:
        return RETAKES_NAV
    text = update.message.text.strip()
    if text in (_back_label(), _menu_label()):
        return await _retakes_end_main(update, context)
    await update.message.reply_text(t("schedule.use_keyboard"))
    return RETAKES_NAV


async def _retakes_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message:
        await update.message.reply_text(
            t("common.conversation_cancelled"),
            reply_markup=await main_menu_reply_keyboard(),
        )
    return ConversationHandler.END


async def _retakes_main_cb(
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
    return ConversationHandler.END


def register(app) -> None:
    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(_retakes_open, pattern=r"^menu:retakes$"),
            MessageHandler(
                filters.TEXT
                & ~filters.COMMAND
                & filters.Regex(main_menu_text_pattern("menu.retakes")),
                _retakes_open,
            ),
        ],
        states={
            RETAKES_NAV: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _retakes_nav_text
                ),
                CallbackQueryHandler(_retakes_main_cb, pattern=r"^menu:main$"),
                CallbackQueryHandler(_retakes_pick_commission_cb, pattern=r"^retlc:c:\d+$"),
                CallbackQueryHandler(
                    _retakes_pick_teacher_cb, pattern=r"^retlc:t:\d+:\d+$"
                ),
                CallbackQueryHandler(_retakes_back_commissions_cb, pattern=r"^retlc:bc$"),
                CallbackQueryHandler(_retakes_show_all_cb, pattern=r"^retlc:all$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", _retakes_cancel)],
        name="retakes_conv",
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(conv)
