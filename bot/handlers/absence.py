"""Check-in answers and the four absence wizards."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import flows, keyboards, texts
from ..db import ALL_KINDS, KIND_SICK, STATUS_APPROVED
from ..services import (
    clean_text,
    clear_markup,
    deps,
    notify_admins,
    parse_date,
    validate_date,
)

log = logging.getLogger(__name__)


# --------------------------------------------------------------------- guards


async def _require_approved(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    d = deps(context)
    user = update.effective_user
    if user is None:
        return None
    employee = await d.db.get_employee(user.id)
    reply = update.message.reply_text if update.message else None
    if employee is None:
        if reply:
            await reply(texts.NOT_REGISTERED)
        return None
    if employee["status"] != STATUS_APPROVED:
        if reply:
            await reply(texts.NOT_APPROVED_YET)
        return None
    return employee


# ------------------------------------------------------------------ step engine


def _step_sequence(flow: flows.AbsenceFlow, allow_attachment: bool) -> list[str]:
    seq = [flows.STEP_KIND, flows.STEP_START, flows.STEP_RETURN]
    if flow.needs_destination():
        seq.append(flows.STEP_DESTINATION)
    if flow.needs_comment():
        seq.append(flows.STEP_COMMENT)
    if flow.kind == KIND_SICK and allow_attachment:
        seq.append(flows.STEP_ATTACHMENT)
    seq.append(flows.STEP_CONFIRM)
    return seq


async def _ask_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.AbsenceFlow
) -> None:
    d = deps(context)
    chat = update.effective_chat
    if chat is None:
        return
    today = d.cal.today()

    async def send(text: str, markup=None) -> None:
        await context.bot.send_message(
            chat_id=chat.id, text=text, parse_mode=ParseMode.HTML, reply_markup=markup
        )

    if flow.step == flows.STEP_KIND:
        await send(texts.ASK_KIND, keyboards.kinds(flow.token))

    elif flow.step == flows.STEP_START:
        anchor = flow.target_date or today
        flow.cal_year, flow.cal_month = anchor.year, anchor.month
        await send(
            texts.ASK_START_DATE,
            keyboards.calendar_keyboard(
                flow.token,
                anchor.year,
                anchor.month,
                today=today,
                min_date=today - dt.timedelta(days=d.settings.past_date_grace_days),
                max_date=today + dt.timedelta(days=d.settings.future_date_horizon_days),
            ),
        )

    elif flow.step == flows.STEP_RETURN:
        anchor = flow.start_date or today
        min_date = anchor + dt.timedelta(days=1)
        flow.cal_year, flow.cal_month = min_date.year, min_date.month
        await send(
            texts.ASK_RETURN_DATE,
            keyboards.calendar_keyboard(
                flow.token,
                min_date.year,
                min_date.month,
                today=today,
                min_date=min_date,
                max_date=anchor + dt.timedelta(days=d.settings.max_absence_days),
            ),
        )

    elif flow.step == flows.STEP_DESTINATION:
        await send(texts.ASK_DESTINATION, keyboards.cancel_only(flow.token))

    elif flow.step == flows.STEP_COMMENT:
        await send(texts.ASK_COMMENT, keyboards.cancel_only(flow.token))

    elif flow.step == flows.STEP_ATTACHMENT:
        await send(texts.ASK_ATTACHMENT, keyboards.skip_or_cancel(flow.token))

    elif flow.step == flows.STEP_CONFIRM:
        assert flow.start_date and flow.return_date and flow.kind
        days = await d.cal.working_days_between(flow.start_date, flow.return_date)
        await send(
            texts.absence_summary(
                kind=flow.kind,
                start_date=flow.start_date,
                return_date=flow.return_date,
                destination=flow.destination,
                comment=flow.comment,
                has_file=bool(flow.file_id),
                days=days,
            ),
            keyboards.confirm_absence(flow.token),
        )

    flows.set_absence(context, flow)


async def _advance(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.AbsenceFlow
) -> None:
    d = deps(context)
    seq = _step_sequence(flow, d.settings.allow_sick_leave_attachment)
    try:
        index = seq.index(flow.step)
    except ValueError:
        index = 0
    flow.step = seq[min(index + 1, len(seq) - 1)]
    await _ask_step(update, context, flow)


async def _start_absence_flow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    source: str,
    check_in_id: int | None,
    target_date: dt.date | None,
) -> None:
    flows.clear_all(context)
    flow = flows.AbsenceFlow(
        source=source,
        check_in_id=check_in_id,
        target_date=target_date,
        step=flows.STEP_KIND,
    )
    flows.set_absence(context, flow)
    await _ask_step(update, context, flow)


# ---------------------------------------------------------------- entry points


async def on_report_absence_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Second persistent button: report an absence at any time."""
    employee = await _require_approved(update, context)
    if employee is None:
        return
    await _start_absence_flow(
        update, context, source="manual", check_in_id=None, target_date=None
    )


async def on_check_in_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, raw_id, answer = query.data.split(":", 2)
    d = deps(context)

    check_in = await d.db.get_check_in(int(raw_id))
    if check_in is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    if int(check_in["telegram_id"]) != query.from_user.id:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    if check_in["answer"] is not None:
        await query.answer(texts.ALREADY_ANSWERED, show_alert=True)
        await clear_markup(context.bot, check_in["chat_id"], check_in["message_id"])
        return

    await query.answer()
    target_date: dt.date = check_in["target_date"]

    if answer == "y":
        await d.db.answer_check_in(int(check_in["id"]), True)
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=texts.PRESENT_RECORDED,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.main_menu(),
        )
        # Answering "yes" while an absence record still covers that day almost
        # always means an early return. Don't silently rewrite HR's data — flag it.
        covering = await d.db.absence_covering(int(check_in["telegram_id"]), target_date)
        if covering:
            employee = await d.db.get_employee(int(check_in["telegram_id"]))
            await notify_admins(
                context,
                "⚠️ <b>Nomuvofiqlik</b>\n\n"
                f"👤 {employee['full_name'] if employee else check_in['telegram_id']}\n"
                f"{texts.fmt_date(target_date)} kuni ishda bo'lishini bildirdi, "
                f"lekin faol yozuv bor:\n"
                f"{texts.kind_label(covering['kind'])} "
                f"{texts.fmt_date(covering['start_date'])} → "
                f"{texts.fmt_date(covering['return_date'])}\n\n"
                "<i>Ehtimol muddatidan oldin ishga qaytdi.</i>",
            )
        return

    # answer == "n"
    await query.edit_message_reply_markup(reply_markup=None)

    previous = await d.db.previous_answered_check_in(
        int(check_in["telegram_id"]), int(check_in["id"])
    )
    if previous and previous["answer"] is False and previous["absence_id"]:
        absence = await d.db.get_absence(int(previous["absence_id"]))
        if absence and not absence["is_cancelled"]:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=texts.previous_details(
                    kind=absence["kind"],
                    start_date=absence["start_date"],
                    return_date=absence["return_date"],
                    destination=absence["destination"],
                    comment=absence["comment"],
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=keyboards.change_or_not(int(check_in["id"])),
            )
            return

    await _start_absence_flow(
        update,
        context,
        source=check_in["slot"],
        check_in_id=int(check_in["id"]),
        target_date=target_date,
    )


async def on_change_or_not(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, raw_id, action = query.data.split(":", 2)
    d = deps(context)

    check_in = await d.db.get_check_in(int(raw_id))
    if check_in is None or int(check_in["telegram_id"]) != query.from_user.id:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    if check_in["answer"] is not None:
        await query.answer(texts.ALREADY_ANSWERED, show_alert=True)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    if action == "chg":
        await _start_absence_flow(
            update,
            context,
            source=check_in["slot"],
            check_in_id=int(check_in["id"]),
            target_date=check_in["target_date"],
        )
        return

    # No change: reuse the same absence record instead of duplicating it.
    previous = await d.db.previous_answered_check_in(
        int(check_in["telegram_id"]), int(check_in["id"])
    )
    absence_id = int(previous["absence_id"]) if previous and previous["absence_id"] else None
    await d.db.answer_check_in(int(check_in["id"]), False, absence_id)
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=texts.NO_CHANGES_RECORDED + "\n\n" + texts.DELIVERED,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.main_menu(),
    )


# -------------------------------------------------------------- wizard buttons


async def on_kind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token, kind = query.data.split(":", 2)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    if kind not in ALL_KINDS:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    flow.kind = kind
    flow.step = flows.STEP_KIND
    await query.edit_message_text(f"✅ {texts.kind_label(kind)}", parse_mode=ParseMode.HTML)
    await _advance(update, context, flow)


async def on_calendar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token, action, payload = query.data.split(":", 3)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return

    d = deps(context)
    today = d.cal.today()

    if action == "x":
        await query.answer()
        return

    if action == "m":
        year_s, month_s = payload.split("-", 1)
        year, month = int(year_s), int(month_s)
        # Keep navigation inside a sane range so nobody scrolls to 2043.
        anchor = flow.start_date if flow.step == flows.STEP_RETURN else today
        lower = (anchor or today) - dt.timedelta(days=400)
        upper = (anchor or today) + dt.timedelta(days=d.settings.future_date_horizon_days)
        if not (dt.date(lower.year, lower.month, 1) <= dt.date(year, month, 1) <= dt.date(upper.year, upper.month, 1)):
            await query.answer("📅 Bu oy mavjud emas.", show_alert=False)
            return
        await query.answer()
        flow.cal_year, flow.cal_month = year, month
        flows.set_absence(context, flow)
        if flow.step == flows.STEP_RETURN and flow.start_date:
            min_date: dt.date | None = flow.start_date + dt.timedelta(days=1)
            max_date = flow.start_date + dt.timedelta(days=d.settings.max_absence_days)
        else:
            min_date = today - dt.timedelta(days=d.settings.past_date_grace_days)
            max_date = today + dt.timedelta(days=d.settings.future_date_horizon_days)
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                flow.token, year, month, today=today, min_date=min_date, max_date=max_date
            )
        )
        return

    if action != "d":
        await query.answer()
        return

    chosen = dt.date.fromisoformat(payload)
    await query.answer()
    await _accept_date(update, context, flow, chosen, edit_query=True)


async def _accept_date(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    flow: flows.AbsenceFlow,
    chosen: dt.date,
    *,
    edit_query: bool,
) -> None:
    d = deps(context)
    today = d.cal.today()
    query = update.callback_query
    chat_id = update.effective_chat.id if update.effective_chat else None

    async def complain(text: str) -> None:
        if chat_id is not None:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)

    if flow.step == flows.STEP_START:
        error = validate_date(chosen, today=today, settings=d.settings)
        if error:
            await complain(error)
            return
        flow.start_date = chosen
        flow.return_date = None
    elif flow.step == flows.STEP_RETURN:
        error = validate_date(
            chosen, today=today, settings=d.settings, min_date=flow.start_date
        )
        if error:
            await complain(error)
            return
        flow.return_date = chosen
    else:
        return

    label = texts.fmt_date(chosen)
    if edit_query and query is not None:
        try:
            await query.edit_message_text(f"✅ {label}")
        except Exception:  # noqa: BLE001 - message may be unchanged/too old
            pass
    await _advance(update, context, flow)


async def on_skip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token = query.data.split(":", 1)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await _advance(update, context, flow)


async def on_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token = query.data.split(":", 1)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    flow.reset_answers()
    await _ask_step(update, context, flow)


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token = query.data.split(":", 1)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token):
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    flows.clear_absence(context)
    try:
        await query.edit_message_text(texts.CANCELLED)
    except Exception:  # noqa: BLE001
        await query.edit_message_reply_markup(reply_markup=None)
    if update.effective_chat:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=texts.MENU_TEXT,
            reply_markup=keyboards.main_menu(),
        )


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token = query.data.split(":", 1)
    flow = flows.get_absence(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    if not (flow.kind and flow.start_date and flow.return_date):
        await query.answer(texts.FLOW_LOST, show_alert=True)
        flows.clear_absence(context)
        return
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)
    await _save(update, context, flow)


async def _save(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.AbsenceFlow
) -> None:
    d = deps(context)
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if user is None or chat_id is None:
        return

    employee = await d.db.get_employee(user.id)
    if employee is None:
        await context.bot.send_message(chat_id=chat_id, text=texts.NOT_REGISTERED)
        flows.clear_absence(context)
        return

    absence = await d.db.create_absence(user.id, **flow.as_kwargs())

    if flow.check_in_id:
        check_in = await d.db.get_check_in(flow.check_in_id)
        if check_in is not None and check_in["answer"] is None:
            await d.db.answer_check_in(flow.check_in_id, False, int(absence["id"]))
            await clear_markup(context.bot, check_in["chat_id"], check_in["message_id"])

    flows.clear_absence(context)

    await context.bot.send_message(
        chat_id=chat_id,
        text=texts.delivered_with_summary(
            kind=absence["kind"],
            start_date=absence["start_date"],
            return_date=absence["return_date"],
            destination=absence["destination"],
            comment=absence["comment"],
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.main_menu(),
    )

    await notify_admins(
        context,
        texts.admin_absence_notice(
            full_name=employee["full_name"],
            department=employee["department"],
            kind=absence["kind"],
            start_date=absence["start_date"],
            return_date=absence["return_date"],
            destination=absence["destination"],
            comment=absence["comment"],
        ),
    )


# ---------------------------------------------------------------- text & files


async def handle_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.AbsenceFlow
) -> None:
    message = update.message
    if message is None or not message.text:
        return
    d = deps(context)

    if flow.step in (flows.STEP_START, flows.STEP_RETURN):
        chosen = parse_date(message.text, today=d.cal.today())
        if chosen is None:
            await message.reply_text(texts.BAD_DATE_FORMAT, parse_mode=ParseMode.HTML)
            return
        await _accept_date(update, context, flow, chosen, edit_query=False)
        return

    if flow.step == flows.STEP_DESTINATION:
        value = clean_text(message.text)
        if not value or len(value) < 2:
            await message.reply_text(texts.BAD_SHORT_TEXT)
            return
        flow.destination = value
        await _advance(update, context, flow)
        return

    if flow.step == flows.STEP_COMMENT:
        value = clean_text(message.text)
        if not value or len(value) < 2:
            await message.reply_text(texts.BAD_SHORT_TEXT)
            return
        flow.comment = value
        await _advance(update, context, flow)
        return

    if flow.step == flows.STEP_ATTACHMENT:
        await message.reply_text(texts.ATTACHMENT_BAD)
        return

    if flow.step == flows.STEP_KIND:
        await message.reply_text(texts.ASK_KIND, reply_markup=keyboards.kinds(flow.token))
        return

    if flow.step == flows.STEP_CONFIRM:
        await _ask_step(update, context, flow)


async def handle_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    flow = flows.get_absence(context)
    if message is None or flow is None:
        return
    if flow.step != flows.STEP_ATTACHMENT:
        return

    if message.photo:
        flow.file_id = message.photo[-1].file_id
        flow.file_kind = "photo"
    elif message.document:
        flow.file_id = message.document.file_id
        flow.file_kind = "document"
    else:
        await message.reply_text(texts.ATTACHMENT_BAD)
        return

    await message.reply_text(texts.ATTACHMENT_SAVED)
    await _advance(update, context, flow)


# -------------------------------------------------------------- my records


async def cmd_my_records(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    employee = await _require_approved(update, context)
    if employee is None or update.message is None:
        return
    d = deps(context)
    rows = await d.db.my_active_absences(int(employee["telegram_id"]), d.cal.today())
    if not rows:
        await update.message.reply_text(texts.NO_ACTIVE_ABSENCE)
        return
    body = "\n".join(
        texts.my_absence_line(
            kind=r["kind"],
            start_date=r["start_date"],
            return_date=r["return_date"],
            destination=r["destination"],
        )
        for r in rows
    )
    await update.message.reply_text(
        "<b>Faol yozuvlaringiz:</b>\n\n" + body,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.my_absences(rows),
    )


async def on_cancel_absence(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, _, raw_id = query.data.split(":", 2)
    d = deps(context)
    ok = await d.db.cancel_absence(int(raw_id), query.from_user.id)
    await query.answer(texts.ABSENCE_CANCELLED if ok else texts.STALE_BUTTON, show_alert=not ok)
    if ok:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:  # noqa: BLE001
            pass
        employee = await d.db.get_employee(query.from_user.id)
        absence = await d.db.get_absence(int(raw_id))
        if employee and absence:
            await notify_admins(
                context,
                "🗑 <b>Yo'qlik yozuvi bekor qilindi</b>\n\n"
                f"👤 {employee['full_name']} ({employee['department']})\n"
                f"{texts.kind_label(absence['kind'])} "
                f"{texts.fmt_date(absence['start_date'])} → "
                f"{texts.fmt_date(absence['return_date'])}",
            )


__all__ = [
    "cmd_my_records",
    "handle_attachment",
    "handle_text",
    "on_calendar",
    "on_cancel",
    "on_cancel_absence",
    "on_change_or_not",
    "on_check_in_answer",
    "on_confirm",
    "on_kind",
    "on_report_absence_button",
    "on_restart",
    "on_skip",
]
