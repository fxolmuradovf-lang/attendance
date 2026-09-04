"""The scheduler.

Design note — why a one-minute tick instead of cron jobs
--------------------------------------------------------
Everything is driven by a single ``run_repeating`` tick, and every action it
takes is derived from state in Postgres rather than from having fired at an
exact instant. That buys three things that matter on a platform where the
container is redeployed whenever you push:

* **No missed runs.** If the container was restarting at 08:00, the next tick
  notices there are employees without a prompt and sends them.
* **No duplicates.** ``employees_without_check_in`` and the UNIQUE constraint
  on ``check_ins`` mean a prompt can only be created once per person per slot
  per day, no matter how many times the tick runs.
* **No timezone surprises.** All comparisons happen against
  ``datetime.now(ZoneInfo("Asia/Tashkent"))``, so it does not matter that the
  container's clock is UTC.

The cost is that a prompt can be up to ``TICK_SECONDS`` late. At 08:00 sharp
nobody notices a 40-second delay.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from telegram.ext import ContextTypes

from . import keyboards, texts
from .db import SLOT_EVENING, SLOT_MORNING
from .services import (
    deps,
    notify_admins,
    safe_send,
    send_check_in,
    slot_deadline,
    slot_start,
)

log = logging.getLogger(__name__)

SEND_PAUSE_SECONDS = 0.05  # ~20 messages/second, well under Telegram's limit
SLOT_HUMAN = {SLOT_MORNING: "08:00", SLOT_EVENING: "17:00"}


async def tick(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Runs every minute. Cheap when there is nothing to do (two SELECTs)."""
    d = deps(context)
    now = d.cal.now()
    today = now.date()

    try:
        await _housekeeping(context, now)
    except Exception:  # noqa: BLE001
        log.exception("Housekeeping failed")

    if not await d.cal.is_working_day(today):
        return

    try:
        await _run_slot(context, SLOT_MORNING, now=now, today=today, target_date=today)
    except Exception:  # noqa: BLE001
        log.exception("Morning slot failed")

    try:
        next_working = await d.cal.next_working_day(today)
        if next_working is not None:
            await _run_slot(
                context, SLOT_EVENING, now=now, today=today, target_date=next_working
            )
    except Exception:  # noqa: BLE001
        log.exception("Evening slot failed")


async def _run_slot(
    context: ContextTypes.DEFAULT_TYPE,
    slot: str,
    *,
    now: dt.datetime,
    today: dt.date,
    target_date: dt.date,
) -> None:
    d = deps(context)
    start = slot_start(slot, d.settings)
    deadline = slot_deadline(slot, d.settings)
    clock = now.time()

    if clock < start:
        return

    if clock >= deadline:
        # One digest per slot per day, guaranteed by the bot_meta marker.
        if await d.db.try_mark(f"digest:{slot}:{today.isoformat()}"):
            await _send_digest(context, slot, today=today, target_date=target_date)
        return

    # 1. Ask everyone who has not been asked yet (initial send + catch-up).
    missing = await d.db.employees_without_check_in(slot, target_date)
    if missing:
        log.info("Slot %s: sending %d prompt(s) for %s", slot, len(missing), target_date)
    for employee in missing:
        if not d.settings.ask_during_known_absence:
            covering = await d.db.absence_covering(int(employee["telegram_id"]), target_date)
            if covering:
                continue
        await send_check_in(
            context, employee, slot=slot, target_date=target_date, asked_on=today
        )
        await asyncio.sleep(SEND_PAUSE_SECONDS)

    # 2. Nudge whoever is still silent and whose next reminder is due.
    pending = await d.db.pending_check_ins(
        slot, today, d.settings.max_reminders, d.settings.reminder_every_minutes
    )
    if pending:
        log.info("Slot %s: nudging %d employee(s)", slot, len(pending))
    for check_in in pending:
        await _nudge(context, check_in, deadline)
        await asyncio.sleep(SEND_PAUSE_SECONDS)


async def _nudge(
    context: ContextTypes.DEFAULT_TYPE, check_in: dict, deadline: dt.time
) -> None:
    d = deps(context)
    check_in_id = int(check_in["id"])
    telegram_id = int(check_in["telegram_id"])

    # Bump first: a permanently failing chat must not be retried every tick.
    await d.db.bump_reminder(check_in_id)

    message = await safe_send(
        context.bot,
        d.db,
        telegram_id,
        texts.reminder_text(int(check_in["reminders"]), deadline),
        reply_markup=keyboards.yes_no(check_in_id),
    )
    if message is not None:
        await d.db.set_check_in_message(check_in_id, message.chat_id, message.message_id)


async def _send_digest(
    context: ContextTypes.DEFAULT_TYPE,
    slot: str,
    *,
    today: dt.date,
    target_date: dt.date,
) -> None:
    """After the deadline, tell the admins what the day looks like."""
    d = deps(context)
    if not (d.settings.admin_ids or d.settings.hr_chat_id):
        return

    silent = await d.db.unanswered_check_ins(slot, today)
    absences = await d.db.absences_on(target_date)

    lines = [
        f"📊 <b>{SLOT_HUMAN.get(slot, slot)} yakuni — {texts.fmt_date_long(target_date)}</b>",
        "",
    ]

    if absences:
        lines.append(f"<b>Ishda bo'lmaydiganlar ({len(absences)}):</b>")
        for number, row in enumerate(absences, start=1):
            tail = f" — 📍 {row['destination']}" if row["destination"] else ""
            lines.append(
                f"{number}. {row['full_name']} — {row['department']}\n"
                f"    {texts.KIND_LABELS.get(row['kind'], row['kind'])} "
                f"{texts.fmt_date(row['start_date'])} → {texts.fmt_date(row['return_date'])}{tail}"
            )
    else:
        lines.append("<b>Hamma ishda.</b> 🎉")

    # Non-responders: the people HR has to chase after the deadline.
    if silent:
        lines += ["", f"<b>⚠️ Hech qanday javob bermaganlar ({len(silent)}):</b>"]
        lines += [
            f"{number}. {row['full_name']} — {row['department']}"
            for number, row in enumerate(silent, start=1)
        ]
    else:
        lines += ["", "✅ Hamma javob berdi."]

    # And the roster slots nobody has registered for at all.
    if d.settings.has_roster:
        claimed = await d.db.claimed_departments()
        free = [dept for dept in d.settings.departments if dept not in claimed]
        if free:
            lines += ["", f"<b>⬜️ Ro'yxatdan o'tmaganlar ({len(free)}):</b>"]
            lines += [f"• {dept}" for dept in free]

    text = "\n".join(lines)
    # Chunk defensively: 4096 characters is the hard Telegram limit.
    for piece in _chunks(text, 3800):
        await notify_admins(context, piece)


def _chunks(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    current: list[str] = []
    length = 0
    for line in text.split("\n"):
        if length + len(line) + 1 > size and current:
            out.append("\n".join(current))
            current, length = [], 0
        current.append(line)
        length += len(line) + 1
    if current:
        out.append("\n".join(current))
    return out


async def _housekeeping(context: ContextTypes.DEFAULT_TYPE, now: dt.datetime) -> None:
    """Once a day, in the small hours, tidy the marker table."""
    if now.hour != 3:
        return
    d = deps(context)
    if await d.db.try_mark(f"prune:{now.date().isoformat()}"):
        removed = await d.db.prune_meta()
        log.info("Housekeeping: pruned %d old marker rows", removed)


async def on_startup_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """One-off job a few seconds after boot, so admins know a deploy landed."""
    d = deps(context)
    employees = await d.db.list_pollable_employees()
    await notify_admins(
        context,
        "🤖 <b>Bot ishga tushdi.</b>\n"
        f"Vaqt: {d.cal.now().strftime('%d.%m.%Y %H:%M')} ({d.settings.timezone})\n"
        f"Faol xodimlar: {len(employees)}\n"
        f"Savol vaqtlari: {d.settings.morning_time.strftime('%H:%M')} / "
        f"{d.settings.evening_time.strftime('%H:%M')}",
    )
