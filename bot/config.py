"""Configuration loaded from environment variables.

Every knob the bot has lives here so that Railway's Variables tab is the only
place you ever need to change behaviour.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo


def _get(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            "See README.md -> 'Environment variables'."
        )
    return value or ""


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "y", "on"}


def _get_time(name: str, default: str) -> time:
    """Parse "HH:MM" into a timezone-aware time in the bot's timezone."""
    raw = os.environ.get(name, "").strip() or default
    try:
        hour_s, minute_s = raw.split(":", 1)
        return time(hour=int(hour_s), minute=int(minute_s))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"{name} must look like 'HH:MM', got {raw!r}") from exc


def _get_id_list(name: str) -> list[int]:
    raw = os.environ.get(name, "")
    ids: list[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.append(int(chunk))
        except ValueError as exc:
            raise RuntimeError(
                f"{name} must be a comma-separated list of numeric Telegram IDs; "
                f"{chunk!r} is not a number."
            ) from exc
    return ids


def _get_str_list(*names: str) -> list[str]:
    """Read a "|"-separated list from the first of ``names`` that is set."""
    for name in names:
        raw = os.environ.get(name, "").strip()
        if raw:
            return [c.strip() for c in raw.split("|") if c.strip()]
    return []


def normalise_database_url(url: str) -> str:
    """Make a Railway/Heroku-style URL safe for asyncpg.

    asyncpg does not understand the ``postgres+driver://`` prefixes that some
    ORMs use, and it rejects the ``sslmode`` query parameter that libpq
    accepts. Railway hands out plain ``postgresql://`` URLs, but people paste
    all sorts of things into that variable, so we clean it up defensively.
    """
    if not url:
        return url

    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    # Strip libpq-only query params that asyncpg refuses.
    if "?" in url:
        base, _, query = url.partition("?")
        keep = [
            part
            for part in query.split("&")
            if part and part.split("=", 1)[0]
            not in {"sslmode", "ssl", "target_session_attrs", "channel_binding", "gssencmode"}
        ]
        url = base + ("?" + "&".join(keep) if keep else "")
    return url


# Uzbek public holidays. Non-fixed ones (Ramazon/Qurbon hayit) move every year
# and transferred working days are announced by decree, so treat this only as a
# starting point and manage the live list with /holiday from inside the bot.
DEFAULT_HOLIDAYS_2026: list[tuple[str, str]] = [
    ("2026-01-01", "Yangi yil"),
    ("2026-01-14", "Vatan himoyachilari kuni"),
    ("2026-03-08", "Xotin-qizlar kuni"),
    ("2026-03-21", "Navro'z"),
    ("2026-05-09", "Xotira va qadrlash kuni"),
    ("2026-09-01", "Mustaqillik kuni"),
    ("2026-10-01", "O'qituvchi va murabbiylar kuni"),
    ("2026-12-08", "Konstitutsiya kuni"),
]

DEFAULT_HOLIDAYS_2027: list[tuple[str, str]] = [
    ("2027-01-01", "Yangi yil"),
    ("2027-01-14", "Vatan himoyachilari kuni"),
    ("2027-03-08", "Xotin-qizlar kuni"),
    ("2027-03-21", "Navro'z"),
    ("2027-05-09", "Xotira va qadrlash kuni"),
    ("2027-09-01", "Mustaqillik kuni"),
    ("2027-10-01", "O'qituvchi va murabbiylar kuni"),
    ("2027-12-08", "Konstitutsiya kuni"),
]


@dataclass(frozen=True)
class Settings:
    # --- Required -----------------------------------------------------------
    bot_token: str
    database_url: str

    # --- People -------------------------------------------------------------
    admin_ids: list[int] = field(default_factory=list)
    hr_chat_id: int | None = None

    # --- Time & calendar ----------------------------------------------------
    timezone: ZoneInfo = ZoneInfo("Asia/Tashkent")
    morning_time: time = time(8, 0)
    evening_time: time = time(17, 0)
    morning_deadline: time = time(10, 0)
    evening_deadline: time = time(19, 0)
    reminder_every_minutes: int = 15
    max_reminders: int = 8
    # 0=Monday .. 6=Sunday. Mon-Sat means Sunday (6) is the only weekly day off.
    weekend_weekdays: frozenset[int] = frozenset({6})

    # --- Behaviour ----------------------------------------------------------
    ask_during_known_absence: bool = True
    allow_sick_leave_attachment: bool = True
    require_admin_approval: bool = True
    max_absence_days: int = 365
    past_date_grace_days: int = 30
    future_date_horizon_days: int = 400

    # --- Roster -------------------------------------------------------------
    # DEPARTMENT and NAME are two parallel "|"-separated lists of equal length.
    # Entry i of DEPARTMENT (which now also carries the lavozim, e.g.
    # "Moliya departamenti direktori") belongs to entry i of NAME.
    departments: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    departments_per_page: int = 8

    # --- Ops ----------------------------------------------------------------
    health_port: int | None = None
    log_level: str = "INFO"
    db_min_pool: int = 1
    db_max_pool: int = 5

    @property
    def has_admins(self) -> bool:
        return bool(self.admin_ids)

    def is_admin(self, telegram_id: int | None) -> bool:
        return telegram_id is not None and telegram_id in self.admin_ids

    # --- Roster helpers -----------------------------------------------------

    @property
    def has_roster(self) -> bool:
        return bool(self.departments)

    @property
    def roster(self) -> list[tuple[str, str]]:
        """``[(department, name), …]`` in the order they appear in the env var."""
        return list(zip(self.departments, self.names))

    def name_for_department(self, department: str) -> str | None:
        """The person who holds a department slot, matched on the exact text.

        Matching by text rather than index means you can safely reorder or
        insert entries in the env vars without re-pointing existing employees.
        """
        for dept, name in zip(self.departments, self.names):
            if dept == department:
                return name
        return None

    def department_index(self, department: str) -> int:
        """Position in the env var, used to sort reports into hierarchy order."""
        try:
            return self.departments.index(department)
        except ValueError:
            return len(self.departments) + 1


def load_settings() -> Settings:
    hr_raw = os.environ.get("HR_CHAT_ID", "").strip()
    health_raw = os.environ.get("PORT", "").strip()

    departments = _get_str_list("DEPARTMENT", "DEPARTMENTS")
    names = _get_str_list("NAME", "NAMES")

    # Fail loudly at boot rather than handing somebody the wrong name at 08:00.
    if bool(departments) != bool(names):
        missing = "NAME" if departments else "DEPARTMENT"
        raise RuntimeError(
            f"DEPARTMENT and NAME must both be set, but {missing} is empty. "
            "They are two parallel '|'-separated lists of the same length: "
            "entry 1 of DEPARTMENT belongs to entry 1 of NAME."
        )
    if len(departments) != len(names):
        raise RuntimeError(
            f"DEPARTMENT has {len(departments)} entries but NAME has {len(names)}. "
            "They must match exactly, because entry i of one pairs with entry i "
            "of the other. Count your '|' separators — a trailing '|' or a name "
            "containing '|' is the usual cause."
        )
    duplicates = sorted({d for d in departments if departments.count(d) > 1})
    if duplicates:
        raise RuntimeError(
            "DEPARTMENT contains duplicate entries, so the bot cannot tell which "
            f"person a slot belongs to: {', '.join(duplicates)}"
        )

    return Settings(
        bot_token=_get("BOT_TOKEN", required=True).strip(),
        database_url=normalise_database_url(_get("DATABASE_URL", required=True).strip()),
        admin_ids=_get_id_list("ADMIN_IDS"),
        hr_chat_id=int(hr_raw) if hr_raw else None,
        timezone=ZoneInfo(_get("TZ_NAME", "Asia/Tashkent")),
        morning_time=_get_time("MORNING_TIME", "08:00"),
        evening_time=_get_time("EVENING_TIME", "17:00"),
        morning_deadline=_get_time("MORNING_DEADLINE", "10:00"),
        evening_deadline=_get_time("EVENING_DEADLINE", "19:00"),
        reminder_every_minutes=_get_int("REMINDER_EVERY_MINUTES", 15),
        max_reminders=_get_int("MAX_REMINDERS", 8),
        weekend_weekdays=frozenset(
            int(x) for x in _get("WEEKEND_WEEKDAYS", "6").replace(" ", "").split(",") if x != ""
        ),
        ask_during_known_absence=_get_bool("ASK_DURING_KNOWN_ABSENCE", True),
        allow_sick_leave_attachment=_get_bool("ALLOW_ATTACHMENTS", True),
        require_admin_approval=_get_bool("REQUIRE_ADMIN_APPROVAL", True),
        max_absence_days=_get_int("MAX_ABSENCE_DAYS", 365),
        past_date_grace_days=_get_int("PAST_DATE_GRACE_DAYS", 30),
        future_date_horizon_days=_get_int("FUTURE_DATE_HORIZON_DAYS", 400),
        departments=departments,
        names=names,
        departments_per_page=_get_int("DEPARTMENTS_PER_PAGE", 8),
        health_port=int(health_raw) if health_raw else None,
        log_level=_get("LOG_LEVEL", "INFO").upper(),
        db_min_pool=_get_int("DB_MIN_POOL", 1),
        db_max_pool=_get_int("DB_MAX_POOL", 5),
    )
