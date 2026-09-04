"""Entry point.

Run locally with:   python main.py
Run on Railway as:  python main.py   (see Procfile)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from telegram import BotCommand, Update
from telegram.ext import (
    AIORateLimiter,
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import jobs, texts
from bot.config import DEFAULT_HOLIDAYS_2026, DEFAULT_HOLIDAYS_2027, Settings, load_settings
from bot.db import Database
from bot.handlers import absence, admin, registration, router
from bot.services import Deps
from bot.workdays import WorkdayCalendar

log = logging.getLogger("bot")

TICK_SECONDS = int(os.environ.get("TICK_SECONDS", "60"))

BOT_COMMANDS = [
    BotCommand("start", "Ro'yxatdan o'tish / asosiy menyu"),
    BotCommand("menu", "Asosiy menyu"),
    BotCommand("mening", "Faol yo'qlik yozuvlarim"),
    BotCommand("help", "Yordam"),
]


# --------------------------------------------------------------------- logging


def setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
        stream=sys.stdout,
    )
    # httpx logs every single Telegram API call at INFO; far too chatty.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Application").setLevel(logging.INFO)


# ---------------------------------------------------------------- health probe


async def start_health_server(port: int) -> asyncio.base_events.Server:
    """Tiny HTTP 200 endpoint so a Railway healthcheck can pass.

    Only started when Railway exposes ``PORT`` (i.e. the service has a domain).
    A plain worker service does not need it.
    """

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await asyncio.wait_for(reader.read(2048), timeout=5)
            writer.write(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 2\r\n"
                b"Connection: close\r\n\r\nok"
            )
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    server = await asyncio.start_server(handle, "0.0.0.0", port)
    log.info("Health endpoint listening on :%s", port)
    return server


# -------------------------------------------------------------------- handlers


def register_handlers(app: Application) -> None:
    # --- commands ---------------------------------------------------------
    app.add_handler(CommandHandler("start", registration.cmd_start))
    app.add_handler(CommandHandler("menu", registration.cmd_menu))
    app.add_handler(CommandHandler("help", registration.cmd_help))
    app.add_handler(CommandHandler("whoami", registration.cmd_whoami))
    app.add_handler(CommandHandler(["mening", "my"], absence.cmd_my_records))

    app.add_handler(CommandHandler("admin", admin.cmd_admin))
    app.add_handler(CommandHandler("pending", admin.cmd_pending))
    app.add_handler(CommandHandler("roster", admin.cmd_roster))
    app.add_handler(CommandHandler("today", admin.cmd_today))
    app.add_handler(CommandHandler(["absent", "yoq"], admin.cmd_absent))
    app.add_handler(CommandHandler(["malumot", "info"], admin.cmd_malumot))
    app.add_handler(CommandHandler("export", admin.cmd_export))
    app.add_handler(CommandHandler("holiday", admin.cmd_holiday))
    app.add_handler(CommandHandler("broadcast", admin.cmd_broadcast))

    # --- inline buttons ---------------------------------------------------
    app.add_handler(CallbackQueryHandler(absence.on_check_in_answer, pattern=r"^ci:"))
    app.add_handler(CallbackQueryHandler(absence.on_change_or_not, pattern=r"^ev:"))
    app.add_handler(CallbackQueryHandler(absence.on_kind, pattern=r"^k:"))
    app.add_handler(CallbackQueryHandler(absence.on_calendar, pattern=r"^cal:"))
    app.add_handler(CallbackQueryHandler(absence.on_skip, pattern=r"^sk:"))
    app.add_handler(CallbackQueryHandler(absence.on_confirm, pattern=r"^ok:"))
    app.add_handler(CallbackQueryHandler(absence.on_restart, pattern=r"^rs:"))
    app.add_handler(CallbackQueryHandler(absence.on_cancel, pattern=r"^cx:"))
    app.add_handler(CallbackQueryHandler(absence.on_cancel_absence, pattern=r"^abs:c:"))

    app.add_handler(CallbackQueryHandler(registration.on_confirm, pattern=r"^reg:"))
    app.add_handler(CallbackQueryHandler(registration.on_page, pattern=r"^depp:"))
    app.add_handler(CallbackQueryHandler(registration.on_show_all, pattern=r"^depall:"))
    app.add_handler(CallbackQueryHandler(registration.on_pick_list, pattern=r"^dep:"))
    app.add_handler(CallbackQueryHandler(registration.on_profile_field, pattern=r"^pf:"))

    app.add_handler(CallbackQueryHandler(admin.on_decision, pattern=r"^ad:"))

    # Anything left over is a button from a pre-deploy message.
    app.add_handler(CallbackQueryHandler(router.on_unknown_callback))

    # --- the two persistent reply-keyboard buttons ------------------------
    app.add_handler(
        MessageHandler(
            filters.Text([texts.BTN_EDIT_PROFILE]), registration.on_edit_profile_button
        )
    )
    app.add_handler(
        MessageHandler(
            filters.Text([texts.BTN_REPORT_ABSENCE]), absence.on_report_absence_button
        )
    )

    # --- attachments and free text ----------------------------------------
    app.add_handler(
        MessageHandler(filters.PHOTO | filters.Document.ALL, absence.handle_attachment)
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router.on_text))

    app.add_error_handler(router.on_error)


# ------------------------------------------------------------------- lifecycle


async def post_init(app: Application) -> None:
    d: Deps = app.bot_data[Deps.KEY]

    await d.db.connect()
    await d.db.apply_schema()
    seeded = await d.db.seed_holidays(
        DEFAULT_HOLIDAYS_2026 + DEFAULT_HOLIDAYS_2027, "holidays_seeded_v1"
    )
    if seeded:
        log.info("Seeded %d default holidays", seeded)

    # NAME is the single source of truth for spelling: push it onto existing
    # rows so fixing a typo in Railway and redeploying is all it takes.
    # Matching is on the department text, so reordering the env vars is safe.
    if d.settings.has_roster:
        changed = await d.db.resync_names(d.settings.roster)
        for department, was, now_is in changed:
            log.info("Re-synced name for %r: %r -> %r", department, was, now_is)
        log.info(
            "Roster: %d slots configured, %d name(s) re-synced from NAME",
            len(d.settings.departments),
            len(changed),
        )
    else:
        log.warning(
            "DEPARTMENT/NAME are not set, so nobody can register. Set both in "
            "Railway as two '|'-separated lists of equal length."
        )

    if d.settings.health_port:
        app.bot_data["health_server"] = await start_health_server(d.settings.health_port)

    if app.job_queue is None:  # pragma: no cover
        raise RuntimeError(
            "JobQueue is unavailable. Install with: pip install "
            "'python-telegram-bot[job-queue,rate-limiter]'"
        )

    app.job_queue.run_repeating(
        jobs.tick, interval=TICK_SECONDS, first=15, name="tick"
    )
    app.job_queue.run_once(jobs.on_startup_report, when=8, name="startup-report")

    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
    except Exception:  # noqa: BLE001
        log.warning("Could not set bot commands", exc_info=True)

    me = await app.bot.get_me()
    log.info(
        "Started as @%s | tz=%s | morning=%s | evening=%s | admins=%s",
        me.username,
        d.settings.timezone,
        d.settings.morning_time,
        d.settings.evening_time,
        d.settings.admin_ids or "NONE SET",
    )
    if not d.settings.admin_ids:
        log.warning(
            "ADMIN_IDS is empty: nobody will receive approval requests, digests or "
            "/export. Send /whoami to the bot and put the number in ADMIN_IDS."
        )


async def post_shutdown(app: Application) -> None:
    server = app.bot_data.get("health_server")
    if server is not None:
        server.close()
    d: Deps | None = app.bot_data.get(Deps.KEY)
    if d is not None:
        await d.db.close()
    log.info("Shutdown complete")


def build_application(settings: Settings) -> Application:
    db = Database(
        settings.database_url,
        min_size=settings.db_min_pool,
        max_size=settings.db_max_pool,
    )
    app = (
        ApplicationBuilder()
        .token(settings.bot_token)
        .rate_limiter(AIORateLimiter())
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.bot_data[Deps.KEY] = Deps(db, settings, WorkdayCalendar(db, settings))
    register_handlers(app)
    return app


def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    app = build_application(settings)
    # drop_pending_updates: after a redeploy, replaying a backlog of taps on
    # buttons from yesterday is worse than losing them.
    app.run_polling(
        allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
