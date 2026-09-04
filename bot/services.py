"""Shared operations used by both handlers and scheduled jobs."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from typing import Any

from telegram import Bot, InlineKeyboardMarkup, Message
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError, TimedOut
from telegram.ext import ContextTypes

from . import keyboards, texts
from .config import Settings
from .db import SLOT_EVENING, SLOT_MORNING, Database
from .workdays import WorkdayCalendar

log = logging.getLogger(__name__)

DATE_PATTERNS = (
    re.compile(r"^(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})[.\-/](?P<y>\d{4})$"),
    re.compile(r"^(?P<y>\d{4})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})$"),
    re.compile(r"^(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})[.\-/](?P<y2>\d{2})$"),
    re.compile(r"^(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})$"),
)

MAX_TEXT_LEN = 300
MAX_NAME_LEN = 120


# ------------------------------------------------------------------ dependencies


class Deps:
    """Bundle of the shared singletons, stashed in ``application.bot_data``."""

    KEY = "deps"

    def __init__(self, db: Database, settings: Settings, cal: WorkdayCalendar) -> None:
        self.db = db
        self.settings = settings
        self.cal = cal


def deps(context: ContextTypes.DEFAULT_TYPE) -> Deps:
    value = context.bot_data.get(Deps.KEY)
    if not isinstance(value, Deps):  # pragma: no cover - wiring error
        raise RuntimeError("Deps missing from bot_data; check main.py wiring")
    return value


# ------------------------------------------------------------------- messaging


async def safe_send(
    bot: Bot,
    db: Database,
    chat_id: int,
    text: str,
    *,
    reply_markup: Any = None,
    parse_mode: str | None = ParseMode.HTML,
    retries: int = 2,
) -> Message | None:
    """Send a message, surviving the three failures that matter in production.

    * ``Forbidden`` — the user blocked the bot or deleted their account. There
      is no point retrying, ever; mark them inactive so jobs stop trying.
    * ``RetryAfter`` — Telegram flood control. Sleep exactly as long as it asks.
    * ``TimedOut`` — transient network blip; retry a couple of times.
    """
    for attempt in range(retries + 1):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_notification=False,
            )
        except Forbidden:
            log.info("Chat %s blocked the bot; marking inactive", chat_id)
            try:
                await db.set_employee_active(chat_id, False)
            except Exception:  # noqa: BLE001
                log.exception("Could not deactivate %s", chat_id)
            return None
        except RetryAfter as exc:
            wait = float(getattr(exc, "retry_after", 1)) + 0.5
            log.warning("Flood control for %s: sleeping %.1fs", chat_id, wait)
            await asyncio.sleep(wait)
        except TimedOut:
            if attempt >= retries:
                log.warning("Timed out sending to %s, giving up", chat_id)
                return None
            await asyncio.sleep(1.5 * (attempt + 1))
        except BadRequest as exc:
            log.error("BadRequest sending to %s: %s", chat_id, exc)
            return None
        except TelegramError as exc:
            log.error("TelegramError sending to %s: %s", chat_id, exc)
            return None
    return None


async def clear_markup(bot: Bot, chat_id: int | None, message_id: int | None) -> None:
    """Remove buttons from an old prompt so it cannot be answered twice."""
    if not chat_id or not message_id:
        return
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id, message_id=message_id, reply_markup=None
        )
    except (BadRequest, Forbidden, TelegramError):
        pass  # already edited, deleted, or too old — harmless


async def notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    d = deps(context)
    targets: list[int] = list(d.settings.admin_ids)
    if d.settings.hr_chat_id and d.settings.hr_chat_id not in targets:
        targets.append(d.settings.hr_chat_id)
    for chat_id in targets:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError as exc:
            log.warning("Could not notify admin %s: %s", chat_id, exc)


async def send_long(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, lines: list[str], header: str = ""
) -> None:
    """Telegram caps a message at 4096 characters; chunk long reports."""
    chunk: list[str] = [header] if header else []
    size = len(header)
    for line in lines:
        if size + len(line) + 1 > 3500:
            await context.bot.send_message(
                chat_id=chat_id, text="\n".join(chunk), parse_mode=ParseMode.HTML
            )
            chunk, size = [], 0
        chunk.append(line)
        size += len(line) + 1
    if chunk:
        await context.bot.send_message(
            chat_id=chat_id, text="\n".join(chunk), parse_mode=ParseMode.HTML
        )


# ------------------------------------------------------------------------ dates


def parse_date(raw: str, *, today: dt.date) -> dt.date | None:
    text = (raw or "").strip()
    for pattern in DATE_PATTERNS:
        match = pattern.match(text)
        if not match:
            continue
        parts = match.groupdict()
        day, month = int(parts["d"]), int(parts["m"])
        if parts.get("y"):
            year = int(parts["y"])
        elif parts.get("y2"):
            year = 2000 + int(parts["y2"])
        else:
            year = today.year
        try:
            candidate = dt.date(year, month, day)
        except ValueError:
            return None
        # A bare "15.09" late in December almost certainly means next year.
        if not parts.get("y") and not parts.get("y2") and (today - candidate).days > 180:
            try:
                candidate = dt.date(year + 1, month, day)
            except ValueError:
                return None
        return candidate
    return None


def validate_date(
    day: dt.date,
    *,
    today: dt.date,
    settings: Settings,
    min_date: dt.date | None = None,
) -> str | None:
    """Return an error string, or ``None`` when the date is acceptable."""
    if (today - day).days > settings.past_date_grace_days:
        return texts.DATE_TOO_FAR_PAST.format(limit=settings.past_date_grace_days)
    if (day - today).days > settings.future_date_horizon_days:
        return texts.DATE_TOO_FAR_FUTURE
    if min_date is not None and day <= min_date:
        return texts.DATE_RETURN_BEFORE_START.format(start=texts.fmt_date(min_date))
    if min_date is not None and (day - min_date).days > settings.max_absence_days:
        return texts.DATE_RANGE_TOO_LONG.format(limit=settings.max_absence_days)
    return None


def clean_text(raw: str | None, *, limit: int = MAX_TEXT_LEN) -> str | None:
    if raw is None:
        return None
    value = " ".join(raw.split())
    return value[:limit] if value else None


# --------------------------------------------------------------------- check-ins


async def send_check_in(
    context: ContextTypes.DEFAULT_TYPE,
    employee: dict[str, Any],
    *,
    slot: str,
    target_date: dt.date,
    asked_on: dt.date,
) -> bool:
    """Create (if needed) and send one check-in prompt. Idempotent."""
    d = deps(context)
    telegram_id = int(employee["telegram_id"])
    row, created = await d.db.ensure_check_in(telegram_id, slot, target_date, asked_on)

    if not created and (row["answer"] is not None or row["message_id"]):
        # Already asked (or already answered) — do not spam a duplicate.
        return False

    if slot == SLOT_MORNING:
        text = texts.ask_today(employee["full_name"], target_date)
    else:
        text = texts.ask_next_day(employee["full_name"], target_date, asked_on)

    message = await safe_send(
        context.bot,
        d.db,
        telegram_id,
        text,
        reply_markup=keyboards.yes_no(int(row["id"])),
    )
    if message is None:
        return False
    await d.db.set_check_in_message(int(row["id"]), message.chat_id, message.message_id)
    return True


def slot_deadline(slot: str, settings: Settings) -> dt.time:
    return settings.morning_deadline if slot == SLOT_MORNING else settings.evening_deadline


def slot_start(slot: str, settings: Settings) -> dt.time:
    return settings.morning_time if slot == SLOT_MORNING else settings.evening_time


ALL_SLOTS = (SLOT_MORNING, SLOT_EVENING)
