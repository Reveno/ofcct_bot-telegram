from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from i18n import t

_FAQ_BUTTON_EMOJIS = ("✨", "⚡", "💰", "📊", "📋", "🎓", "❓", "📌")


def main_menu_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t("menu.schedule"), callback_data="menu:schedule"
            )
        ],
        [InlineKeyboardButton(text=t("menu.faq"), callback_data="menu:faq")],
        [
            InlineKeyboardButton(
                text=t("menu.feedback"), callback_data="menu:feedback"
            )
        ],
        [InlineKeyboardButton(text=t("menu.social"), callback_data="menu:social")],
        [
            InlineKeyboardButton(
                text=t("menu.retakes"), callback_data="menu:retakes"
            )
        ],
        [
            InlineKeyboardButton(
                text=t("menu.subscription"), callback_data="menu:subscription"
            )
        ],
        [InlineKeyboardButton(text=t("menu.news"), callback_data="menu:news")],
    ]
    return InlineKeyboardMarkup(rows)


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(text=t("common.back"), callback_data="menu:main")]]
    )


def schedule_courses_keyboard(
    course_nums: list[int], *, cohort_mode: bool = False
) -> InlineKeyboardMarkup:
    rows = []
    for c in course_nums:
        if c == 0:
            label = (
                t("schedule.cohort_other")
                if cohort_mode
                else t("schedule.course_other")
            )
        elif cohort_mode:
            label = t("schedule.cohort_label", n=c)
        else:
            label = t("schedule.course_label", n=c)
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"sch:c:{c}")]
        )
    rows.append(
        [InlineKeyboardButton(text=t("common.back"), callback_data="menu:main")]
    )
    return InlineKeyboardMarkup(rows)


def schedule_groups_keyboard(
    groups: list[str], *, course: int | None = None
) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for g in groups:
        row.append(InlineKeyboardButton(text=g, callback_data=f"sch:g:{g}"))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    back_cb = "sch:back_courses" if course is not None else "menu:main"
    rows.append(
        [InlineKeyboardButton(text=t("common.back"), callback_data=back_cb)]
    )
    return InlineKeyboardMarkup(rows)


def schedule_days_keyboard(group: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for d in range(1, 7):
        label = t(f"days.short{d}")
        row.append(
            InlineKeyboardButton(
                text=label, callback_data=f"sch:d:{group}:{d}"
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
                text=t("common.back"), callback_data="sch:back_groups"
            ),
            InlineKeyboardButton(
                text=t("schedule.to_main_menu"), callback_data="menu:main"
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def faq_reply_keyboard(button_labels: list[str]) -> ReplyKeyboardMarkup:
    """Дві кнопки в рядку + ряд «Головне меню» (як reply-клавіатура)."""
    keyboard: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for label in button_labels:
        row.append(KeyboardButton(label))
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton(t("faq.reply_back_to_menu"))])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def faq_button_label(question: str, index: int) -> str:
    """Емодзі + пробіл + текст (обмеження ~64 байти для Telegram)."""
    emo = _FAQ_BUTTON_EMOJIS[index % len(_FAQ_BUTTON_EMOJIS)]
    q = (question or "").strip()
    prefix = f"{emo} "
    max_bytes = 64
    enc = prefix.encode("utf-8")
    if len(enc) + len(q.encode("utf-8")) <= max_bytes:
        return prefix + q
    room = max_bytes - len(enc) - 1
    cut = q.encode("utf-8")[:room].decode("utf-8", errors="ignore")
    return prefix + cut + "…"


def news_list_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, (nid, title) in enumerate(items, start=1):
        short = title if len(title) <= 48 else title[:45] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{i}. {short}",
                    callback_data=f"news:v:{nid}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=t("common.back"), callback_data="menu:main")]
    )
    return InlineKeyboardMarkup(rows)


def faq_list_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = []
    for i, (fid, question) in enumerate(items, start=1):
        short = question if len(question) <= 48 else question[:45] + "…"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{i}. {short}", callback_data=f"faq:{fid}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text=t("common.back"), callback_data="menu:main")]
    )
    return InlineKeyboardMarkup(rows)


def subscription_keyboard(subscribed: bool) -> InlineKeyboardMarkup:
    toggle = (
        t("subscription.unsubscribe")
        if subscribed
        else t("subscription.subscribe")
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(text=toggle, callback_data="sub:toggle")],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="menu:main"
                )
            ],
        ]
    )


def social_keyboard() -> InlineKeyboardMarkup:
    from config import (
        SOCIAL_FACEBOOK_URL,
        SOCIAL_INSTAGRAM_URL,
        SOCIAL_SITE_URL,
        SOCIAL_TELEGRAM_URL,
    )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    text=t("social.instagram"), url=SOCIAL_INSTAGRAM_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("social.telegram_channel"), url=SOCIAL_TELEGRAM_URL
                )
            ],
            [InlineKeyboardButton(text=t("social.website"), url=SOCIAL_SITE_URL)],
            [
                InlineKeyboardButton(
                    text=t("social.facebook"), url=SOCIAL_FACEBOOK_URL
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("common.back"), callback_data="menu:main"
                )
            ],
        ]
    )
