from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from i18n import t


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.messages"), callback_data="adm:messages"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.broadcast"), callback_data="adm:broadcast"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.news_manage"), callback_data="adm:news_manage"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.schedule"), callback_data="adm:schedule"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.schedule_changes"),
                    callback_data="adm:changes",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.retakes"), callback_data="adm:retakes"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.stats"), callback_data="adm:stats"
                )
            ],
        ]
    )


def admin_reply_feedback_keyboard(feedback_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("feedback.reply_button"),
                    callback_data=f"adm:reply:{feedback_id}",
                )
            ]
        ]
    )


def confirm_keyboard(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.confirm"), callback_data=yes_data
                ),
                InlineKeyboardButton(text=t("common.abort"), callback_data=no_data),
            ]
        ]
    )


def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return confirm_keyboard("bc:yes", "bc:no")


def schedule_upload_confirm_keyboard() -> InlineKeyboardMarkup:
    return confirm_keyboard("upsched:yes", "upsched:no")


def change_groups_keyboard(groups: list[str], prefix: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for g in groups:
        row.append(
            InlineKeyboardButton(text=g, callback_data=f"{prefix}:g:{g}")
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t("common.back"), callback_data=f"{prefix}:cancel"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def change_days_keyboard(prefix: str, group: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for d in range(1, 7):
        label = t(f"days.short{d}")
        row.append(
            InlineKeyboardButton(
                text=label, callback_data=f"{prefix}:d:{group}:{d}"
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
                text=t("common.back"), callback_data=f"{prefix}:back_g"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def change_lessons_keyboard(prefix: str, group: str, day: int) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for n in range(0, 6):
        label = t(f"lessons.{n}")
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"{prefix}:l:{group}:{day}:{n}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=t("common.back"), callback_data=f"{prefix}:back_d:{group}"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def change_type_keyboard(prefix: str, group: str, day: int, lesson: int) -> InlineKeyboardMarkup:
    base = f"{prefix}:t:{group}:{day}:{lesson}"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.type_cancel"), callback_data=f"{base}:cancel"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.type_replace"), callback_data=f"{base}:replace"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("admin.type_add"), callback_data=f"{base}:add"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data=f"{prefix}:back_l:{group}:{day}"
                )
            ],
        ]
    )


def delete_change_keyboard(change_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.delete_change_button"),
                    callback_data=f"chdel:{change_id}",
                )
            ]
        ]
    )


def retake_delete_keyboard(retake_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("admin.delete_change_button"),
                    callback_data=f"rtdel:{retake_id}",
                )
            ]
        ]
    )


def clearchanges_confirm_keyboard(week_start: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("common.confirm"),
                    callback_data=f"clrch:yes:{week_start}",
                ),
                InlineKeyboardButton(text=t("common.abort"), callback_data="clrch:no"),
            ]
        ]
    )
