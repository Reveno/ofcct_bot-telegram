import re

from telegram import KeyboardButton, ReplyKeyboardMarkup

from i18n import t

# Ключі i18n для пунктів головного меню (порядок як на reply-клавіатурі)
MAIN_MENU_I18N_KEYS: tuple[str, ...] = (
    "menu.schedule",
    "menu.faq",
    "menu.feedback",
    "menu.social",
    "menu.retakes",
    "menu.subscription",
    "menu.news",
)


def main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    """Головне меню: reply-клавіатура, 2 кнопки в ряд, як у референсі."""
    rows: list[list[KeyboardButton]] = [
        [
            KeyboardButton(t("menu.schedule")),
            KeyboardButton(t("menu.faq")),
        ],
        [
            KeyboardButton(t("menu.feedback")),
            KeyboardButton(t("menu.social")),
        ],
        [
            KeyboardButton(t("menu.retakes")),
            KeyboardButton(t("menu.subscription")),
        ],
        [KeyboardButton(t("menu.news"))],
    ]
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def main_menu_text_pattern(i18n_key: str) -> re.Pattern[str]:
    """Точний збіг тексту кнопки головного меню (для MessageHandler)."""
    return re.compile("^" + re.escape(t(i18n_key)) + "$")


def all_main_menu_button_texts() -> frozenset[str]:
    return frozenset(t(k) for k in MAIN_MENU_I18N_KEYS)


def nav_reply_keyboard() -> ReplyKeyboardMarkup:
    """Останній ряд: назад + головне меню (reply)."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(t("common.back")),
                KeyboardButton(t("schedule.to_main_menu")),
            ]
        ],
        resize_keyboard=True,
    )


def schedule_view_reply_keyboard() -> ReplyKeyboardMarkup:
    """Після перегляду розкладу: до вибору дня + головне меню."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(t("schedule.back_to_weekdays")),
                KeyboardButton(t("schedule.to_main_menu")),
            ]
        ],
        resize_keyboard=True,
    )


def schedule_course_row_label(n: int, *, cohort_mode: bool) -> str:
    if n == 0:
        return (
            t("schedule.cohort_other")
            if cohort_mode
            else t("schedule.course_other")
        )
    if cohort_mode:
        return t("schedule.cohort_label", n=n)
    return t("schedule.course_label", n=n)


def schedule_courses_reply_keyboard(
    course_nums: list[int], *, cohort_mode: bool = False
) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    for c in course_nums:
        rows.append(
            [KeyboardButton(schedule_course_row_label(c, cohort_mode=cohort_mode))]
        )
    rows.append(
        [
            KeyboardButton(t("common.back")),
            KeyboardButton(t("schedule.to_main_menu")),
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def schedule_groups_reply_keyboard(groups: list[str]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for g in groups:
        row.append(KeyboardButton(g))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            KeyboardButton(t("common.back")),
            KeyboardButton(t("schedule.to_main_menu")),
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def schedule_days_reply_keyboard() -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for d in range(1, 7):
        row.append(KeyboardButton(t(f"days.short{d}")))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            KeyboardButton(t("common.back")),
            KeyboardButton(t("schedule.to_main_menu")),
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def _truncate_button_label(s: str, max_len: int = 48) -> str:
    s = s.strip()
    if len(s) <= max_len:
        return s
    return s[:45] + "…"


def reply_indexed_label(i: int, title: str) -> str:
    return f"{i}. {_truncate_button_label(title)}"


def news_list_reply_keyboard(items: list[tuple[int, str]]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    for i, (_nid, title) in enumerate(items, start=1):
        rows.append([KeyboardButton(reply_indexed_label(i, title))])
    rows.append(
        [
            KeyboardButton(t("common.back")),
            KeyboardButton(t("schedule.to_main_menu")),
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def faq_list_reply_keyboard(items: list[tuple[int, str]]) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    for i, (_fid, question) in enumerate(items, start=1):
        rows.append([KeyboardButton(reply_indexed_label(i, question))])
    rows.append(
        [
            KeyboardButton(t("common.back")),
            KeyboardButton(t("schedule.to_main_menu")),
        ]
    )
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def faq_answer_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("faq.back_to_questions"))],
            [
                KeyboardButton(t("common.back")),
                KeyboardButton(t("schedule.to_main_menu")),
            ],
        ],
        resize_keyboard=True,
    )


def news_detail_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("news.back_to_list"))],
            [
                KeyboardButton(t("common.back")),
                KeyboardButton(t("schedule.to_main_menu")),
            ],
        ],
        resize_keyboard=True,
    )


def subscription_reply_keyboard(subscribed: bool) -> ReplyKeyboardMarkup:
    toggle = (
        t("subscription.unsubscribe")
        if subscribed
        else t("subscription.subscribe")
    )
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(toggle)],
            [
                KeyboardButton(t("common.back")),
                KeyboardButton(t("schedule.to_main_menu")),
            ],
        ],
        resize_keyboard=True,
    )
