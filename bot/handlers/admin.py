"""Administrator commands: approvals, reports, holidays, export, broadcast."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import export, keyboards, malumot, texts
from ..db import (
    SLOT_EVENING,
    SLOT_MORNING,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from ..services import deps, parse_date, safe_send, send_long

log = logging.getLogger(__name__)


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and deps(context).settings.is_admin(user.id)


async def _deny(update: Update) -> None:
    if update.message:
        await update.message.reply_text(texts.ADMIN_ONLY)


# ------------------------------------------------------------------- commands


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message:
        await update.message.reply_text(texts.ADMIN_HELP, parse_mode=ParseMode.HTML)


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)

    pending = await d.db.list_employees(status=STATUS_PENDING)
    if not pending:
        await update.message.reply_text(texts.NO_PENDING)
    for employee in pending[:30]:
        await update.message.reply_text(
            texts.admin_new_registration(
                full_name=employee["full_name"],
                department=employee["department"],
                telegram_id=int(employee["telegram_id"]),
                username=employee.get("username"),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.admin_decision(int(employee["telegram_id"])),
        )

    today = d.cal.today()
    lines: list[str] = []
    for slot, label in ((SLOT_MORNING, "08:00"), (SLOT_EVENING, "17:00")):
        rows = await d.db.unanswered_check_ins(slot, today)
        if rows:
            lines.append(f"\n<b>{label} — javob bermaganlar ({len(rows)}):</b>")
            lines.extend(
                f"{i}. {r['full_name']} — {r['department']}"
                for i, r in enumerate(rows, start=1)
            )
    if not lines:
        lines.append(texts.NOBODY_PENDING_ANSWER)

    # Roster coverage: which DEPARTMENT slots nobody has claimed yet.
    if d.settings.has_roster:
        claimed = await d.db.claimed_departments()
        free = [dept for dept in d.settings.departments if dept not in claimed]
        lines.append("")
        lines.append(
            texts.roster_coverage(
                len(d.settings.departments) - len(free), len(d.settings.departments)
            )
        )
        if free:
            lines.append(texts.ROSTER_FREE_HEADER)
            lines.extend(f"• {dept}" for dept in free)

    await send_long(context, update.message.chat_id, lines)


async def cmd_roster(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The DEPARTMENT/NAME roster and who has claimed each slot."""
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)
    if not d.settings.has_roster:
        await update.message.reply_text(
            texts.ROSTER_NOT_CONFIGURED, parse_mode=ParseMode.HTML
        )
        return

    employees = {e["department"]: e for e in await d.db.list_employees()}
    lines = [
        texts.roster_coverage(
            sum(
                1
                for dept in d.settings.departments
                if dept in employees and employees[dept]["status"] != STATUS_REJECTED
            ),
            len(d.settings.departments),
        ),
        "",
    ]
    marks = {STATUS_APPROVED: "✅", STATUS_PENDING: "⏳", STATUS_REJECTED: "❌"}
    for index, (dept, name) in enumerate(d.settings.roster, start=1):
        employee = employees.get(dept)
        mark = marks.get(employee["status"], "•") if employee else "⬜️"
        lines.append(f"{index}. {mark} <b>{name}</b>\n   {dept}")
    lines.append("")
    lines.append("<i>✅ tasdiqlangan · ⏳ kutilmoqda · ❌ rad etilgan · ⬜️ ro'yxatdan o'tmagan</i>")
    await send_long(context, update.message.chat_id, lines)


def _resolve_date(context: ContextTypes.DEFAULT_TYPE) -> tuple[dt.date | None, bool]:
    """``(date, was_given)`` from the command's arguments, defaulting to today."""
    d = deps(context)
    args = context.args or []
    if not args:
        return d.cal.today(), False
    return parse_date(args[0], today=d.cal.today()), True


async def cmd_absent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/absent 09.09.2026`` — approved employees absent on that date."""
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)

    day, _ = _resolve_date(context)
    if day is None:
        await update.message.reply_text(texts.USAGE_ABSENT, parse_mode=ParseMode.HTML)
        return

    rows = await d.db.absences_on(day)
    if not rows:
        await update.message.reply_text(
            texts.no_absences_on(day), parse_mode=ParseMode.HTML
        )
        return

    rows.sort(
        key=lambda r: (d.settings.department_index(r["department"]), r["full_name"] or "")
    )
    lines = [texts.absent_report_header(day, len(rows))]
    lines.extend(malumot.plain_lines(rows))
    await send_long(context, update.message.chat_id, lines)


async def cmd_malumot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``/malumot 09.09.2026`` — the same list as the official Word document."""
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)

    day, _ = _resolve_date(context)
    if day is None:
        await update.message.reply_text(texts.USAGE_MALUMOT, parse_mode=ParseMode.HTML)
        return

    rows = await d.db.absences_on(day)
    if not rows:
        await update.message.reply_text(
            texts.no_absences_on(day), parse_mode=ParseMode.HTML
        )
        return

    buffer = malumot.build_document(
        rows,
        report_date=day,
        department_order=d.settings.department_index,
    )
    await context.bot.send_document(
        chat_id=update.message.chat_id,
        document=InputFile(buffer, filename=malumot.filename(day)),
        caption=texts.malumot_caption(day, len(rows)),
        parse_mode=ParseMode.HTML,
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)
    today = d.cal.today()

    if not await d.cal.is_working_day(today):
        name = await d.cal.holiday_name(today)
        suffix = f" ({name})" if name else ""
        await update.message.reply_text(f"📅 Bugun ish kuni emas{suffix}.")

    rows = await d.db.absences_on(today)
    if not rows:
        await update.message.reply_text(texts.NO_ABSENCES_TODAY)
        return

    rows.sort(
        key=lambda r: (d.settings.department_index(r["department"]), r["full_name"] or "")
    )
    lines = [texts.absent_report_header(today, len(rows))]
    lines.extend(malumot.plain_lines(rows))
    await send_long(context, update.message.chat_id, lines)


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)
    await update.message.reply_text("⏳ Excel fayl tayyorlanmoqda...")

    employees = await d.db.list_employees()
    absences = await d.db.all_absences()
    check_ins = await d.db.all_check_ins()
    holidays = await d.db.list_holidays()

    buffer = export.build_workbook(
        employees=employees,
        absences=absences,
        check_ins=check_ins,
        holidays=holidays,
        tz=d.settings.timezone,
    )
    await context.bot.send_document(
        chat_id=update.message.chat_id,
        document=InputFile(buffer, filename=export.filename(d.cal.now())),
        caption=(
            f"📊 Xodimlar: {len(employees)} | Yo'qliklar: {len(absences)} | "
            f"Javoblar: {len(check_ins)}"
        ),
    )


async def cmd_holiday(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    d = deps(context)
    args = context.args or []

    if not args or args[0] == "list":
        year = None
        if len(args) > 1 and args[1].isdigit():
            year = int(args[1])
        elif not args or len(args) == 1:
            year = d.cal.today().year
        rows = await d.db.list_holidays(year)
        if not rows:
            await update.message.reply_text("Bayramlar ro'yxati bo'sh.")
            return
        lines = [f"<b>📅 Kalendar ({year or 'barchasi'})</b>\n"]
        lines += [
            f"{'🟢 ish kuni' if r['is_workday'] else '🔴 dam olish'} — "
            f"{texts.fmt_date(r['day'])} — {r['name']}"
            for r in rows
        ]
        await send_long(context, update.message.chat_id, lines)
        return

    action = args[0]
    if action == "del":
        if len(args) < 2:
            await update.message.reply_text("Foydalanish: /holiday del YYYY-MM-DD")
            return
        try:
            day = dt.date.fromisoformat(args[1])
        except ValueError:
            await update.message.reply_text("Sana formati: YYYY-MM-DD")
            return
        ok = await d.db.delete_holiday(day)
        await update.message.reply_text("🗑 O'chirildi." if ok else "Bunday sana topilmadi.")
        return

    if action in {"add", "workday"}:
        if len(args) < 2:
            await update.message.reply_text(
                f"Foydalanish: /holiday {action} YYYY-MM-DD Nomi"
            )
            return
        try:
            day = dt.date.fromisoformat(args[1])
        except ValueError:
            await update.message.reply_text("Sana formati: YYYY-MM-DD")
            return
        name = " ".join(args[2:]) or ("Ko'chirilgan ish kuni" if action == "workday" else "Bayram")
        await d.db.set_holiday(day, name, is_workday=(action == "workday"))
        kind = "🟢 ish kuni" if action == "workday" else "🔴 dam olish kuni"
        await update.message.reply_text(f"✅ {texts.fmt_date(day)} — {name} ({kind})")
        return

    await update.message.reply_text(texts.ADMIN_HELP, parse_mode=ParseMode.HTML)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update, context):
        return await _deny(update)
    if update.message is None:
        return
    text = " ".join(context.args or []).strip()
    if not text:
        await update.message.reply_text("Foydalanish: /broadcast Xabar matni")
        return

    d = deps(context)
    employees = await d.db.list_pollable_employees()
    sent = 0
    for employee in employees:
        message = await safe_send(
            context.bot, d.db, int(employee["telegram_id"]), f"📢 {text}"
        )
        if message is not None:
            sent += 1
        await asyncio.sleep(0.05)  # stay well under Telegram's 30 msg/s ceiling
    await update.message.reply_text(f"✅ {sent}/{len(employees)} xodimga yuborildi.")


# ------------------------------------------------------------------ callbacks


async def on_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    d = deps(context)
    if not d.settings.is_admin(query.from_user.id):
        await query.answer(texts.ADMIN_ONLY, show_alert=True)
        return

    _, action, raw_id = query.data.split(":", 2)
    telegram_id = int(raw_id)
    employee = await d.db.get_employee(telegram_id)
    if employee is None:
        await query.answer("Xodim topilmadi.", show_alert=True)
        return
    if employee["status"] != STATUS_PENDING:
        await query.answer(
            f"Allaqachon hal qilingan: {employee['status']}", show_alert=True
        )
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        return

    await query.answer()
    approve = action == "a"
    await d.db.set_employee_status(
        telegram_id,
        STATUS_APPROVED if approve else STATUS_REJECTED,
        approved_by=query.from_user.id,
    )

    verdict = "✅ Tasdiqlandi" if approve else "❌ Rad etildi"
    try:
        await query.edit_message_text(
            (query.message.text_html if query.message else "") + f"\n\n<b>{verdict}</b> "
            f"({query.from_user.first_name})",
            parse_mode=ParseMode.HTML,
        )
    except Exception:  # noqa: BLE001
        await query.edit_message_reply_markup(reply_markup=None)

    if approve:
        await safe_send(
            context.bot,
            d.db,
            telegram_id,
            texts.APPROVED_NOTICE,
            reply_markup=keyboards.main_menu(),
        )
    else:
        await safe_send(context.bot, d.db, telegram_id, texts.REJECTED_NOTICE)
