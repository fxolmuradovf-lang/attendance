"""Postgres access layer.

Deliberately plain asyncpg + SQL: the whole data model is four tables, and a
readable query is worth more here than an ORM. Every function takes/returns
plain Python types so the handlers never touch SQL.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any, Iterable

import asyncpg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

KIND_SICK = "sick"
KIND_TRIP = "trip"
KIND_UNPAID = "unpaid"
KIND_OTHER = "other"
ALL_KINDS = (KIND_SICK, KIND_TRIP, KIND_UNPAID, KIND_OTHER)

SLOT_MORNING = "morning"
SLOT_EVENING = "evening"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class Database:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self._dsn = dsn
        self._min = min_size
        self._max = max_size
        self._pool: asyncpg.Pool | None = None

    # ------------------------------------------------------------------ setup

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() has not been awaited yet")
        return self._pool

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min,
            max_size=self._max,
            command_timeout=30,
            # Railway's proxy can drop idle connections; recycle them politely.
            max_inactive_connection_lifetime=300,
        )
        log.info("Connected to Postgres (pool %s-%s)", self._min, self._max)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def apply_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
        log.info("Schema applied")

    async def seed_holidays(self, rows: Iterable[tuple[str, str]], marker: str) -> int:
        """Insert default holidays once. Admin edits are never overwritten."""
        async with self.pool.acquire() as conn:
            already = await conn.fetchval("SELECT value FROM bot_meta WHERE key = $1", marker)
            if already:
                return 0
            inserted = 0
            for day_s, name in rows:
                day = dt.date.fromisoformat(day_s)
                result = await conn.execute(
                    """
                    INSERT INTO holidays (day, name, is_workday)
                    VALUES ($1, $2, FALSE)
                    ON CONFLICT (day) DO NOTHING
                    """,
                    day,
                    name,
                )
                if result.endswith("1"):
                    inserted += 1
            await conn.execute(
                """
                INSERT INTO bot_meta (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
                """,
                marker,
                "done",
            )
            return inserted

    # ------------------------------------------------------------------ meta

    async def try_mark(self, key: str) -> bool:
        """Claim a one-shot marker. ``True`` only for the caller that won.

        Used so that "send today's 10:00 digest" happens exactly once even if
        the tick runs twice or the container restarts inside the window.
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO bot_meta (key, value) VALUES ($1, 'done')
            ON CONFLICT (key) DO NOTHING
            RETURNING key
            """,
            key,
        )
        return row is not None

    async def prune_meta(self, older_than_days: int = 90) -> int:
        result = await self.pool.execute(
            "DELETE FROM bot_meta WHERE updated_at < now() - ($1::int * INTERVAL '1 day') "
            "AND key LIKE 'digest:%'",
            older_than_days,
        )
        try:
            return int(result.rsplit(" ", 1)[-1])
        except ValueError:
            return 0

    # -------------------------------------------------------------- employees

    async def get_employee(self, telegram_id: int) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM employees WHERE telegram_id = $1", telegram_id
        )
        return dict(row) if row else None

    async def upsert_employee(
        self,
        telegram_id: int,
        *,
        full_name: str,
        department: str,
        username: str | None,
        status: str,
    ) -> dict[str, Any]:
        """Claim a roster slot.

        Raises ``asyncpg.UniqueViolationError`` if another live employee already
        holds ``department`` — the handler turns that into a friendly message.
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO employees (telegram_id, full_name, department,
                                   username, status, is_active)
            VALUES ($1, $2, $3, $4, $5, TRUE)
            ON CONFLICT (telegram_id) DO UPDATE
               SET full_name  = EXCLUDED.full_name,
                   department = EXCLUDED.department,
                   username   = EXCLUDED.username,
                   status     = EXCLUDED.status,
                   is_active  = TRUE,
                   updated_at = now()
            RETURNING *
            """,
            telegram_id,
            full_name,
            department,
            username,
            status,
        )
        return dict(row)

    async def update_employee_fields(self, telegram_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"full_name", "department", "username"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return await self.get_employee(telegram_id)
        assignments = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(updates))
        row = await self.pool.fetchrow(
            f"UPDATE employees SET {assignments}, updated_at = now() "
            f"WHERE telegram_id = $1 RETURNING *",
            telegram_id,
            *updates.values(),
        )
        return dict(row) if row else None

    async def set_employee_status(
        self, telegram_id: int, status: str, *, approved_by: int | None = None
    ) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            UPDATE employees
               SET status = $2,
                   approved_by = COALESCE($3, approved_by),
                   approved_at = CASE WHEN $2 = 'approved' THEN now() ELSE approved_at END,
                   updated_at = now()
             WHERE telegram_id = $1
            RETURNING *
            """,
            telegram_id,
            status,
            approved_by,
        )
        return dict(row) if row else None

    async def set_employee_active(self, telegram_id: int, active: bool) -> None:
        await self.pool.execute(
            "UPDATE employees SET is_active = $2, updated_at = now() WHERE telegram_id = $1",
            telegram_id,
            active,
        )

    async def list_employees(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = await self.pool.fetch(
                "SELECT * FROM employees WHERE status = $1 ORDER BY department, full_name",
                status,
            )
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM employees ORDER BY department, full_name"
            )
        return [dict(r) for r in rows]

    async def employee_by_department(self, department: str) -> dict[str, Any] | None:
        """Who currently holds a roster slot (ignoring rejected records)."""
        row = await self.pool.fetchrow(
            """
            SELECT * FROM employees
             WHERE department = $1 AND status <> 'rejected'
             LIMIT 1
            """,
            department,
        )
        return dict(row) if row else None

    async def claimed_departments(self) -> set[str]:
        rows = await self.pool.fetch(
            "SELECT department FROM employees WHERE status <> 'rejected'"
        )
        return {r["department"] for r in rows}

    async def resync_names(self, roster: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
        """Push the NAME env var back onto matching employee rows.

        NAME is the single source of truth, so fixing a typo in Railway and
        redeploying is enough. Matching is on the department text, so
        reordering or inserting entries in the env vars is safe.

        Returns ``[(department, old_name, new_name), …]`` for what changed.
        """
        changed: list[tuple[str, str, str]] = []
        for department, name in roster:
            row = await self.pool.fetchrow(
                """
                UPDATE employees AS e
                   SET full_name = $2, updated_at = now()
                  FROM (SELECT telegram_id, full_name FROM employees
                         WHERE department = $1 AND status <> 'rejected') AS old
                 WHERE e.telegram_id = old.telegram_id
                   AND old.full_name <> $2
                RETURNING old.full_name AS was, $2::text AS now_is
                """,
                department,
                name,
            )
            if row is not None:
                changed.append((department, row["was"], row["now_is"]))
        return changed

    async def list_pollable_employees(self) -> list[dict[str, Any]]:
        """Approved employees who have not blocked the bot."""
        rows = await self.pool.fetch(
            """
            SELECT * FROM employees
             WHERE status = 'approved' AND is_active = TRUE
             ORDER BY telegram_id
            """
        )
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- absences

    async def create_absence(
        self,
        telegram_id: int,
        *,
        kind: str,
        start_date: dt.date,
        return_date: dt.date,
        destination: str | None,
        comment: str | None,
        source: str,
        target_date: dt.date | None,
        file_id: str | None = None,
        file_kind: str | None = None,
    ) -> dict[str, Any]:
        row = await self.pool.fetchrow(
            """
            INSERT INTO absences (telegram_id, kind, start_date, return_date, destination,
                                  comment, source, target_date, file_id, file_kind)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            telegram_id,
            kind,
            start_date,
            return_date,
            destination,
            comment,
            source,
            target_date,
            file_id,
            file_kind,
        )
        return dict(row)

    async def get_absence(self, absence_id: int) -> dict[str, Any] | None:
        row = await self.pool.fetchrow("SELECT * FROM absences WHERE id = $1", absence_id)
        return dict(row) if row else None

    async def cancel_absence(self, absence_id: int, telegram_id: int) -> bool:
        result = await self.pool.execute(
            """
            UPDATE absences SET is_cancelled = TRUE, updated_at = now()
             WHERE id = $1 AND telegram_id = $2 AND is_cancelled = FALSE
            """,
            absence_id,
            telegram_id,
        )
        return result.endswith("1")

    async def attach_file_to_absence(
        self, absence_id: int, file_id: str, file_kind: str
    ) -> None:
        await self.pool.execute(
            "UPDATE absences SET file_id = $2, file_kind = $3, updated_at = now() WHERE id = $1",
            absence_id,
            file_id,
            file_kind,
        )

    async def latest_absence(self, telegram_id: int) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            SELECT * FROM absences
             WHERE telegram_id = $1 AND is_cancelled = FALSE
             ORDER BY created_at DESC
             LIMIT 1
            """,
            telegram_id,
        )
        return dict(row) if row else None

    async def absence_covering(
        self, telegram_id: int, day: dt.date
    ) -> dict[str, Any] | None:
        """The active absence record that covers ``day``, if any.

        ``return_date`` is the first day back at work, so the absence covers
        ``start_date <= day < return_date``.
        """
        row = await self.pool.fetchrow(
            """
            SELECT * FROM absences
             WHERE telegram_id = $1
               AND is_cancelled = FALSE
               AND start_date <= $2
               AND return_date > $2
             ORDER BY created_at DESC
             LIMIT 1
            """,
            telegram_id,
            day,
        )
        return dict(row) if row else None

    async def absences_on(
        self, day: dt.date, *, approved_only: bool = True
    ) -> list[dict[str, Any]]:
        """Everyone whose absence covers ``day``.

        Defaults to approved employees only: a pending or rejected registration
        is not somebody HR should be reporting on.
        """
        rows = await self.pool.fetch(
            f"""
            SELECT a.*, e.full_name, e.department, e.status
              FROM absences a
              JOIN employees e USING (telegram_id)
             WHERE a.is_cancelled = FALSE
               AND a.start_date <= $1
               AND a.return_date > $1
               {"AND e.status = 'approved'" if approved_only else ""}
             ORDER BY e.department, e.full_name
            """,
            day,
        )
        return [dict(r) for r in rows]

    async def my_active_absences(self, telegram_id: int, today: dt.date) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM absences
             WHERE telegram_id = $1
               AND is_cancelled = FALSE
               AND return_date > $2
             ORDER BY start_date
            """,
            telegram_id,
            today,
        )
        return [dict(r) for r in rows]

    async def all_absences(self) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT a.*, e.full_name, e.department
              FROM absences a
              JOIN employees e USING (telegram_id)
             ORDER BY a.created_at DESC
            """
        )
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- check-ins

    async def ensure_check_in(
        self, telegram_id: int, slot: str, target_date: dt.date, asked_on: dt.date
    ) -> tuple[dict[str, Any], bool]:
        """Get-or-create the check-in row. Returns ``(row, created)``.

        The UNIQUE constraint means two concurrent job runs cannot both create
        it, so this is safe to call from a retry or a catch-up tick.
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO check_ins (telegram_id, slot, target_date, asked_on)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (telegram_id, slot, target_date) DO NOTHING
            RETURNING *
            """,
            telegram_id,
            slot,
            target_date,
            asked_on,
        )
        if row is not None:
            return dict(row), True
        existing = await self.pool.fetchrow(
            """
            SELECT * FROM check_ins
             WHERE telegram_id = $1 AND slot = $2 AND target_date = $3
            """,
            telegram_id,
            slot,
            target_date,
        )
        return dict(existing), False

    async def get_check_in(self, check_in_id: int) -> dict[str, Any] | None:
        row = await self.pool.fetchrow("SELECT * FROM check_ins WHERE id = $1", check_in_id)
        return dict(row) if row else None

    async def set_check_in_message(
        self, check_in_id: int, chat_id: int, message_id: int
    ) -> None:
        await self.pool.execute(
            "UPDATE check_ins SET chat_id = $2, message_id = $3 WHERE id = $1",
            check_in_id,
            chat_id,
            message_id,
        )

    async def answer_check_in(
        self, check_in_id: int, answer: bool, absence_id: int | None = None
    ) -> dict[str, Any] | None:
        row = await self.pool.fetchrow(
            """
            UPDATE check_ins
               SET answer = $2,
                   answered_at = now(),
                   absence_id = COALESCE($3, absence_id)
             WHERE id = $1
            RETURNING *
            """,
            check_in_id,
            answer,
            absence_id,
        )
        return dict(row) if row else None

    async def clear_check_in_answer(self, check_in_id: int) -> None:
        """Used when a user re-opens a prompt to correct their answer."""
        await self.pool.execute(
            "UPDATE check_ins SET answer = NULL, answered_at = NULL, absence_id = NULL "
            "WHERE id = $1",
            check_in_id,
        )

    async def pending_check_ins(
        self,
        slot: str,
        asked_on: dt.date,
        max_reminders: int,
        due_after_minutes: int,
    ) -> list[dict[str, Any]]:
        """Unanswered check-ins whose next reminder is due.

        ``COALESCE(last_reminder_at, created_at)`` means a freshly created
        prompt is never nudged in the same breath, and a tick that runs twice
        cannot double-nudge.
        """
        rows = await self.pool.fetch(
            """
            SELECT c.*, e.full_name, e.department
              FROM check_ins c
              JOIN employees e USING (telegram_id)
             WHERE c.slot = $1
               AND c.asked_on = $2
               AND c.answer IS NULL
               AND c.reminders < $3
               AND e.is_active = TRUE
               AND e.status = 'approved'
               AND COALESCE(c.last_reminder_at, c.created_at)
                   < now() - ($4::int * INTERVAL '1 minute')
             ORDER BY c.id
            """,
            slot,
            asked_on,
            max_reminders,
            due_after_minutes,
        )
        return [dict(r) for r in rows]

    async def employees_without_check_in(
        self, slot: str, target_date: dt.date
    ) -> list[dict[str, Any]]:
        """Approved, reachable employees who have not been asked yet.

        This single query is the whole "send the prompts" sweep. It is
        self-healing: it covers the normal 08:00 run, a container that was
        redeploying at 08:00, and someone who registered at 08:40.
        """
        rows = await self.pool.fetch(
            """
            SELECT e.*
              FROM employees e
              LEFT JOIN check_ins c
                     ON c.telegram_id = e.telegram_id
                    AND c.slot = $1
                    AND c.target_date = $2
             WHERE e.status = 'approved'
               AND e.is_active = TRUE
               AND c.id IS NULL
             ORDER BY e.telegram_id
            """,
            slot,
            target_date,
        )
        return [dict(r) for r in rows]

    async def unanswered_check_ins(self, slot: str, asked_on: dt.date) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT c.*, e.full_name, e.department
              FROM check_ins c
              JOIN employees e USING (telegram_id)
             WHERE c.slot = $1 AND c.asked_on = $2 AND c.answer IS NULL
               AND e.status = 'approved'
             ORDER BY e.department, e.full_name
            """,
            slot,
            asked_on,
        )
        return [dict(r) for r in rows]

    async def bump_reminder(self, check_in_id: int) -> None:
        await self.pool.execute(
            "UPDATE check_ins SET reminders = reminders + 1, last_reminder_at = now() "
            "WHERE id = $1",
            check_in_id,
        )

    async def previous_answered_check_in(
        self, telegram_id: int, exclude_id: int
    ) -> dict[str, Any] | None:
        """The most recently answered check-in, used for the "o'zgarish bormi?" flow."""
        row = await self.pool.fetchrow(
            """
            SELECT * FROM check_ins
             WHERE telegram_id = $1 AND id <> $2 AND answer IS NOT NULL
             ORDER BY answered_at DESC
             LIMIT 1
            """,
            telegram_id,
            exclude_id,
        )
        return dict(row) if row else None

    async def all_check_ins(self) -> list[dict[str, Any]]:
        rows = await self.pool.fetch(
            """
            SELECT c.*, e.full_name, e.department, a.kind AS absence_kind
              FROM check_ins c
              JOIN employees e USING (telegram_id)
              LEFT JOIN absences a ON a.id = c.absence_id
             ORDER BY c.target_date DESC, c.slot
            """
        )
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- holidays

    async def get_holiday(self, day: dt.date) -> dict[str, Any] | None:
        row = await self.pool.fetchrow("SELECT * FROM holidays WHERE day = $1", day)
        return dict(row) if row else None

    async def list_holidays(self, year: int | None = None) -> list[dict[str, Any]]:
        if year is None:
            rows = await self.pool.fetch("SELECT * FROM holidays ORDER BY day")
        else:
            rows = await self.pool.fetch(
                "SELECT * FROM holidays WHERE EXTRACT(YEAR FROM day) = $1 ORDER BY day",
                year,
            )
        return [dict(r) for r in rows]

    async def set_holiday(self, day: dt.date, name: str, *, is_workday: bool) -> None:
        await self.pool.execute(
            """
            INSERT INTO holidays (day, name, is_workday) VALUES ($1, $2, $3)
            ON CONFLICT (day) DO UPDATE SET name = EXCLUDED.name,
                                            is_workday = EXCLUDED.is_workday
            """,
            day,
            name,
            is_workday,
        )

    async def delete_holiday(self, day: dt.date) -> bool:
        result = await self.pool.execute("DELETE FROM holidays WHERE day = $1", day)
        return result.endswith("1")
