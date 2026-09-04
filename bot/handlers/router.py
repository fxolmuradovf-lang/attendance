"""Text dispatch and the global error handler."""

from __future__ import annotations

import html
import logging
import traceback

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import Conflict, NetworkError, TelegramError
from telegram.ext import ContextTypes

from .. import flows, keyboards, texts
from ..db import STATUS_APPROVED, STATUS_PENDING
from ..services import deps
from . import absence, registration

log = logging.getLogger(__name__)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Free-text messages belong to whichever wizard is currently open."""
    if update.message is None or update.effective_user is None:
        return

    reg_flow = flows.get_reg(context)
    if reg_flow is not None:
        await registration.handle_text(update, context, reg_flow)
        return

    absence_flow = flows.get_absence(context)
    if absence_flow is not None:
        await absence.handle_text(update, context, absence_flow)
        return

    d = deps(context)
    employee = await d.db.get_employee(update.effective_user.id)
    if employee is None:
        await update.message.reply_text(texts.NOT_REGISTERED)
        return
    if employee["status"] == STATUS_PENDING:
        await update.message.reply_text(texts.NOT_APPROVED_YET)
        return
    if employee["status"] != STATUS_APPROVED:
        await update.message.reply_text(texts.NOT_REGISTERED)
        return

    await update.message.reply_text(
        texts.MENU_TEXT, reply_markup=keyboards.main_menu()
    )


async def on_unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Buttons from a message older than the current deployment land here."""
    query = update.callback_query
    if query is None:
        return
    log.info("Unhandled callback data: %r", query.data)
    await query.answer(texts.STALE_BUTTON, show_alert=True)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error

    if isinstance(error, Conflict):
        log.error(
            "Telegram returned 409 Conflict. Another process is polling with the same "
            "BOT_TOKEN. On Railway this almost always means the service has more than "
            "one replica, or the bot is also running on your laptop. Scale to exactly "
            "one replica."
        )
        return

    if isinstance(error, NetworkError):
        log.warning("Network error (will retry): %s", error)
        return

    log.error("Unhandled exception while processing update", exc_info=error)

    # Tell the user something rather than leaving them staring at a dead wizard.
    if isinstance(update, Update) and update.effective_chat is not None:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring yoki /menu ni bosing.",
            )
        except TelegramError:
            pass

    d = None
    try:
        d = deps(context)
    except RuntimeError:
        return
    if not d.settings.admin_ids:
        return

    trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    body = (
        "🐞 <b>Bot xatoligi</b>\n<pre>"
        + html.escape(trace[-2500:])
        + "</pre>"
    )
    try:
        await context.bot.send_message(
            chat_id=d.settings.admin_ids[0], text=body, parse_mode=ParseMode.HTML
        )
    except TelegramError:
        pass
