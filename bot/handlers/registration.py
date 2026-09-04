"""Registration (/start) and the "change my lavozim" button.

Registration is a single choice: the employee picks their entry from the
DEPARTMENT roster, and their F.I.SH. is filled in from the matching NAME entry.
Nobody ever types a name, so HR's spelling is the only spelling, and each
roster slot can be held by exactly one Telegram account.
"""

from __future__ import annotations

import logging

import asyncpg
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .. import flows, keyboards, texts
from ..db import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED
from ..services import clean_text, deps, notify_admins

log = logging.getLogger(__name__)

MIN_QUERY_LEN = 2


# ------------------------------------------------------------------ entrypoints


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = deps(context)
    user = update.effective_user
    if user is None or update.message is None:
        return

    employee = await d.db.get_employee(user.id)

    if employee is None or employee["status"] == STATUS_REJECTED:
        if not d.settings.has_roster:
            await update.message.reply_text(
                texts.ROSTER_NOT_CONFIGURED, parse_mode=ParseMode.HTML
            )
            return
        flows.clear_all(context)
        flow = flows.RegFlow()
        flows.set_reg(context, flow)
        await update.message.reply_text(texts.START_NEW, parse_mode=ParseMode.HTML)
        await _show_picker(update, context, flow)
        return

    # Keep the username fresh — handy for HR when they need to find someone.
    if user.username and employee.get("username") != user.username:
        await d.db.update_employee_fields(user.id, username=user.username)

    if employee["status"] == STATUS_PENDING:
        await update.message.reply_text(texts.NOT_APPROVED_YET)
        return

    await update.message.reply_text(texts.MENU_TEXT, reply_markup=keyboards.main_menu())


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    flows.clear_all(context)
    await update.message.reply_text(texts.MENU_TEXT, reply_markup=keyboards.main_menu())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await update.message.reply_text(texts.HELP_TEXT, parse_mode=ParseMode.HTML)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if update.message is None or user is None:
        return
    await update.message.reply_text(
        f"Telegram ID: <code>{user.id}</code>\nChat ID: <code>{update.message.chat_id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def on_edit_profile_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    d = deps(context)
    user = update.effective_user
    if update.message is None or user is None:
        return
    employee = await d.db.get_employee(user.id)
    if employee is None:
        await update.message.reply_text(texts.NOT_REGISTERED)
        return
    flows.clear_all(context)
    await update.message.reply_text(
        texts.profile_view(employee["full_name"], employee["department"], user.id),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.profile_fields(),
    )


async def on_profile_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles ``pf:dept`` (re-pick the slot) and ``pf:x`` (cancel)."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()
    _, field = query.data.split(":", 1)

    if field == "x":
        flows.clear_all(context)
        try:
            await query.edit_message_text(texts.CANCELLED)
        except Exception:  # noqa: BLE001 - message may be unchanged
            await query.edit_message_reply_markup(reply_markup=None)
        return

    if field != "dept":
        return

    d = deps(context)
    if not d.settings.has_roster:
        await query.edit_message_text(texts.ROSTER_NOT_CONFIGURED, parse_mode=ParseMode.HTML)
        return

    employee = await d.db.get_employee(query.from_user.id)
    if employee is None:
        await query.edit_message_text(texts.NOT_REGISTERED)
        return

    flow = flows.RegFlow(is_edit=True)
    flows.set_reg(context, flow)
    await query.edit_message_reply_markup(reply_markup=None)
    await _show_picker(update, context, flow)


# ---------------------------------------------------------------- roster picker


def _candidates(context: ContextTypes.DEFAULT_TYPE, query: str | None) -> list[tuple[int, str]]:
    """``[(absolute index, label), …]``, optionally filtered by a search term.

    The search deliberately covers both the department text and the person's
    name, so typing a surname finds the right slot.
    """
    d = deps(context)
    pairs = list(enumerate(zip(d.settings.departments, d.settings.names)))
    if not query:
        return [(i, dept) for i, (dept, _) in pairs]
    needle = query.casefold()
    return [
        (i, dept)
        for i, (dept, name) in pairs
        if needle in dept.casefold() or needle in (name or "").casefold()
    ]


async def _show_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    flow: flows.RegFlow,
    *,
    edit: bool = False,
) -> None:
    d = deps(context)
    chat = update.effective_chat
    if chat is None:
        return

    candidates = _candidates(context, flow.query)
    claimed = await d.db.claimed_departments()
    # Never show the employee's own slot as locked against them.
    own = None
    if flow.is_edit:
        employee = await d.db.get_employee(chat.id)
        own = employee["department"] if employee else None
    taken = {
        i
        for i, dept in enumerate(d.settings.departments)
        if dept in claimed and dept != own
    }

    if not candidates:
        body = texts.ASK_DEPARTMENT_SEARCH_EMPTY.format(query=flow.query or "")
        flow.query = None
        flow.page = 0
        flows.set_reg(context, flow)
        await context.bot.send_message(
            chat_id=chat.id, text=body, parse_mode=ParseMode.HTML
        )
        candidates = _candidates(context, None)

    if flow.query:
        body = texts.department_search_results(flow.query, len(candidates))
    else:
        body = texts.ASK_DEPARTMENT_PICK

    markup = keyboards.departments_keyboard(
        flow.token,
        candidates,
        page=flow.page,
        per_page=d.settings.departments_per_page,
        taken=taken,
        searching=bool(flow.query),
    )
    flows.set_reg(context, flow)

    query = update.callback_query
    if edit and query is not None:
        try:
            await query.edit_message_text(
                body, parse_mode=ParseMode.HTML, reply_markup=markup
            )
            return
        except Exception:  # noqa: BLE001 - identical content, or too old
            pass
    await context.bot.send_message(
        chat_id=chat.id, text=body, parse_mode=ParseMode.HTML, reply_markup=markup
    )


async def on_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``depp:<token>:<page>`` — flip a page of the roster."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token, raw_page = query.data.split(":", 2)
    flow = flows.get_reg(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    flow.page = int(raw_page)
    await _show_picker(update, context, flow, edit=True)


async def on_show_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``depall:<token>`` — drop the search filter."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token = query.data.split(":", 1)
    flow = flows.get_reg(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()
    flow.query = None
    flow.page = 0
    await _show_picker(update, context, flow, edit=True)


async def on_pick_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """``dep:<token>:<index>`` — a roster slot was chosen."""
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token, raw_index = query.data.split(":", 2)
    flow = flows.get_reg(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return

    d = deps(context)
    index = int(raw_index)
    if not (0 <= index < len(d.settings.departments)):
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return

    department = d.settings.departments[index]
    name = d.settings.name_for_department(department)

    holder = await d.db.employee_by_department(department)
    if holder is not None and int(holder["telegram_id"]) != query.from_user.id:
        await query.answer()
        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=texts.slot_taken(department, holder["full_name"]),
            parse_mode=ParseMode.HTML,
        )
        return

    await query.answer()
    flow.department = department
    flow.full_name = name
    flow.step = flows.STEP_REG_CONFIRM
    flows.set_reg(context, flow)

    await query.edit_message_text(
        texts.registration_summary(name or "", department),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.confirm_registration(flow.token),
    )


async def handle_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.RegFlow
) -> None:
    """Typed text during registration is treated as a roster search."""
    message = update.message
    if message is None or not message.text:
        return

    if flow.step == flows.STEP_REG_CONFIRM:
        await message.reply_text(
            texts.registration_summary(flow.full_name or "", flow.department or ""),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboards.confirm_registration(flow.token),
        )
        return

    needle = clean_text(message.text, limit=60)
    if not needle or len(needle) < MIN_QUERY_LEN:
        await message.reply_text(texts.BAD_SHORT_TEXT)
        return

    flow.query = needle
    flow.page = 0
    await _show_picker(update, context, flow)


async def on_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    _, token, action = query.data.split(":", 2)
    flow = flows.get_reg(context)
    if not flows.token_matches(flow, token) or flow is None:
        await query.answer(texts.STALE_BUTTON, show_alert=True)
        return
    await query.answer()

    if action == "rs":
        flow.department = None
        flow.full_name = None
        flow.query = None
        flow.page = 0
        flow.step = flows.STEP_DEPT
        flows.set_reg(context, flow)
        await query.edit_message_reply_markup(reply_markup=None)
        await _show_picker(update, context, flow)
        return

    await query.edit_message_reply_markup(reply_markup=None)
    await _save(update, context, flow)


async def _save(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: flows.RegFlow
) -> None:
    d = deps(context)
    user = update.effective_user
    chat_id = update.effective_chat.id if update.effective_chat else None
    if user is None or chat_id is None:
        return

    if not (flow.full_name and flow.department):
        await context.bot.send_message(chat_id=chat_id, text=texts.FLOW_LOST)
        flows.clear_reg(context)
        return

    existing = await d.db.get_employee(user.id)
    was_approved = existing is not None and existing["status"] == STATUS_APPROVED

    # If approval is required but nobody can approve, approve automatically and
    # shout about it in the logs rather than trapping every employee forever.
    if d.settings.require_admin_approval and not d.settings.has_admins:
        log.warning(
            "REQUIRE_ADMIN_APPROVAL is on but ADMIN_IDS is empty — auto-approving %s. "
            "Set ADMIN_IDS in Railway.",
            user.id,
        )
        status = STATUS_APPROVED
    elif was_approved:
        status = STATUS_APPROVED  # changing slot never revokes access
    elif d.settings.require_admin_approval:
        status = STATUS_PENDING
    else:
        status = STATUS_APPROVED

    try:
        employee = await d.db.upsert_employee(
            user.id,
            full_name=flow.full_name,
            department=flow.department,
            username=user.username,
            status=status,
        )
    except asyncpg.UniqueViolationError:
        # Somebody claimed the same slot between the check and the write.
        holder = await d.db.employee_by_department(flow.department)
        flows.clear_reg(context)
        await context.bot.send_message(
            chat_id=chat_id,
            text=texts.slot_taken(
                flow.department, holder["full_name"] if holder else "—"
            ),
            parse_mode=ParseMode.HTML,
        )
        return

    flows.clear_reg(context)

    if status == STATUS_PENDING:
        await context.bot.send_message(chat_id=chat_id, text=texts.REGISTRATION_PENDING)
        await notify_admins(
            context,
            texts.admin_new_registration(
                full_name=employee["full_name"],
                department=employee["department"],
                telegram_id=user.id,
                username=user.username,
            ),
            reply_markup=keyboards.admin_decision(user.id),
        )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text=texts.PROFILE_UPDATED if was_approved else texts.REGISTRATION_DONE,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboards.main_menu(),
    )
    if was_approved:
        await notify_admins(
            context,
            texts.admin_profile_changed(
                full_name=employee["full_name"],
                department=employee["department"],
                telegram_id=user.id,
            ),
        )
    else:
        await notify_admins(
            context,
            texts.admin_new_registration(
                full_name=employee["full_name"],
                department=employee["department"],
                telegram_id=user.id,
                username=user.username,
            ),
        )
