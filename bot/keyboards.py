"""Inline / reply keyboards, including a hand-rolled month calendar.

Callback data is kept deliberately terse: Telegram hard-caps ``callback_data``
at 64 bytes and silently rejects anything longer, which is a classic source of
"the button does nothing" bugs.

Every wizard button carries a short random ``token`` that identifies the flow
it belongs to. If the user taps a button from an abandoned or pre-restart flow
the token no longer matches and we can say so politely instead of writing
garbage to the database.
"""

from __future__ import annotations

import calendar
import datetime as dt
import secrets
import string

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from . import texts
from .db import ALL_KINDS

_ALPHABET = string.ascii_lowercase + string.digits

CAL_NAV_LIMIT_MONTHS = 24


def new_token() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


# ------------------------------------------------------------------- main menu


def main_menu() -> ReplyKeyboardMarkup:
    """The two persistent buttons required by the spec."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(texts.BTN_EDIT_PROFILE)],
            [KeyboardButton(texts.BTN_REPORT_ABSENCE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


# --------------------------------------------------------------- registration


def confirm_registration(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.BTN_CONFIRM, callback_data=f"reg:{token}:ok")],
            [InlineKeyboardButton(texts.BTN_RESTART, callback_data=f"reg:{token}:rs")],
        ]
    )


def departments_keyboard(
    token: str,
    candidates: list[tuple[int, str]],
    *,
    page: int,
    per_page: int,
    taken: set[int],
    searching: bool = False,
) -> InlineKeyboardMarkup:
    """Paginated roster picker.

    ``candidates`` is ``[(absolute index into DEPARTMENT, label), …]`` — the
    absolute index travels in the callback data, so a filtered search result
    still points at the right roster entry.

    Slots somebody already holds are shown with a lock and still tappable: the
    handler explains who has it, which is far more useful than a dead button.
    """
    total_pages = max(1, -(-len(candidates) // per_page))
    page = max(0, min(page, total_pages - 1))
    window = candidates[page * per_page : (page + 1) * per_page]

    rows: list[list[InlineKeyboardButton]] = []
    for index, label in window:
        mark = "🔒 " if index in taken else ""
        rows.append(
            [InlineKeyboardButton(f"{mark}{label}", callback_data=f"dep:{token}:{index}")]
        )

    if total_pages > 1:
        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages
        rows.append(
            [
                InlineKeyboardButton("⬅️", callback_data=f"depp:{token}:{prev_page}"),
                InlineKeyboardButton(
                    f"{page + 1}/{total_pages}", callback_data=f"depp:{token}:{page}"
                ),
                InlineKeyboardButton("➡️", callback_data=f"depp:{token}:{next_page}"),
            ]
        )

    if searching:
        rows.append(
            [InlineKeyboardButton("📋 Butun ro'yxat", callback_data=f"depall:{token}")]
        )

    rows.append([InlineKeyboardButton(texts.BTN_CANCEL, callback_data="pf:x")])
    return InlineKeyboardMarkup(rows)


def profile_fields() -> InlineKeyboardMarkup:
    """F.I.SH. is not editable — it follows the roster slot."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏢 Lavozimni o'zgartirish", callback_data="pf:dept")],
            [InlineKeyboardButton(texts.BTN_CANCEL, callback_data="pf:x")],
        ]
    )


# -------------------------------------------------------------------- check-in


def yes_no(check_in_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.BTN_YES, callback_data=f"ci:{check_in_id}:y"),
                InlineKeyboardButton(texts.BTN_NO, callback_data=f"ci:{check_in_id}:n"),
            ]
        ]
    )


def change_or_not(check_in_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.BTN_NO_CHANGES, callback_data=f"ev:{check_in_id}:same")],
            [InlineKeyboardButton(texts.BTN_HAS_CHANGES, callback_data=f"ev:{check_in_id}:chg")],
        ]
    )


def kinds(token: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(texts.kind_label(kind), callback_data=f"k:{token}:{kind}")]
        for kind in ALL_KINDS
    ]
    rows.append([InlineKeyboardButton(texts.BTN_CANCEL, callback_data=f"cx:{token}")])
    return InlineKeyboardMarkup(rows)


def confirm_absence(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.BTN_CONFIRM, callback_data=f"ok:{token}")],
            [InlineKeyboardButton(texts.BTN_RESTART, callback_data=f"rs:{token}")],
            [InlineKeyboardButton(texts.BTN_CANCEL, callback_data=f"cx:{token}")],
        ]
    )


def skip_or_cancel(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(texts.BTN_SKIP, callback_data=f"sk:{token}")],
            [InlineKeyboardButton(texts.BTN_CANCEL, callback_data=f"cx:{token}")],
        ]
    )


def cancel_only(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(texts.BTN_CANCEL, callback_data=f"cx:{token}")]]
    )


def my_absences(rows: list[dict]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🗑 {texts.fmt_date(r['start_date'])} — bekor qilish",
                    callback_data=f"abs:c:{r['id']}",
                )
            ]
            for r in rows[:20]
        ]
    )


# --------------------------------------------------------------------- calendar


def calendar_keyboard(
    token: str,
    year: int,
    month: int,
    *,
    today: dt.date,
    min_date: dt.date | None = None,
    max_date: dt.date | None = None,
    quick_picks: bool = True,
) -> InlineKeyboardMarkup:
    """A month grid. ``cal:<token>:d:<iso>`` picks, ``cal:<token>:m:<ym>`` navigates."""
    rows: list[list[InlineKeyboardButton]] = []

    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

    rows.append(
        [
            InlineKeyboardButton("◀️", callback_data=f"cal:{token}:m:{prev_year}-{prev_month:02d}"),
            InlineKeyboardButton(
                texts.fmt_month(year, month), callback_data=f"cal:{token}:x:0"
            ),
            InlineKeyboardButton("▶️", callback_data=f"cal:{token}:m:{next_year}-{next_month:02d}"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(name, callback_data=f"cal:{token}:x:0") for name in texts.WEEKDAYS_SHORT]
    )

    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day.month != month:
                row.append(InlineKeyboardButton(" ", callback_data=f"cal:{token}:x:0"))
                continue
            blocked = (min_date is not None and day < min_date) or (
                max_date is not None and day > max_date
            )
            if blocked:
                row.append(InlineKeyboardButton("·", callback_data=f"cal:{token}:x:0"))
                continue
            label = f"[{day.day}]" if day == today else str(day.day)
            row.append(
                InlineKeyboardButton(label, callback_data=f"cal:{token}:d:{day.isoformat()}")
            )
        rows.append(row)

    if quick_picks:
        quick: list[InlineKeyboardButton] = []
        tomorrow = today + dt.timedelta(days=1)
        for label, day in ((texts.BTN_TODAY, today), (texts.BTN_TOMORROW, tomorrow)):
            if (min_date is None or day >= min_date) and (max_date is None or day <= max_date):
                quick.append(
                    InlineKeyboardButton(label, callback_data=f"cal:{token}:d:{day.isoformat()}")
                )
        if quick:
            rows.append(quick)

    rows.append([InlineKeyboardButton(texts.BTN_CANCEL, callback_data=f"cx:{token}")])
    return InlineKeyboardMarkup(rows)


# ------------------------------------------------------------------------ admin


def admin_decision(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(texts.BTN_ADMIN_APPROVE, callback_data=f"ad:a:{telegram_id}"),
                InlineKeyboardButton(texts.BTN_ADMIN_REJECT, callback_data=f"ad:r:{telegram_id}"),
            ]
        ]
    )
