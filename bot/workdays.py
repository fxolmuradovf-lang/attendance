"""Working-day calendar.

The organisation runs a six-day week (Monday-Saturday), with Sunday off, plus
a database-managed list of public holidays. Because Uzbekistan regularly
*transfers* days off onto adjacent working days, the holidays table can also
hold rows with ``is_workday = TRUE``, which force a normally-off day to count
as a working day.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .config import Settings
    from .db import Database

MAX_LOOKAHEAD_DAYS = 60


class WorkdayCalendar:
    def __init__(self, db: "Database", settings: "Settings") -> None:
        self._db = db
        self._s = settings

    def now(self) -> dt.datetime:
        return dt.datetime.now(self._s.timezone)

    def today(self) -> dt.date:
        return self.now().date()

    async def is_working_day(self, day: dt.date) -> bool:
        holiday = await self._db.get_holiday(day)
        if holiday is not None:
            # An explicit row always wins: either a day off, or a transferred
            # working day that overrides the weekend.
            return bool(holiday["is_workday"])
        return day.weekday() not in self._s.weekend_weekdays

    async def holiday_name(self, day: dt.date) -> str | None:
        holiday = await self._db.get_holiday(day)
        if holiday and not holiday["is_workday"]:
            return str(holiday["name"])
        return None

    async def next_working_day(self, after: dt.date) -> dt.date | None:
        """The first working day strictly after ``after``."""
        candidate = after
        for _ in range(MAX_LOOKAHEAD_DAYS):
            candidate += dt.timedelta(days=1)
            if await self.is_working_day(candidate):
                return candidate
        return None

    async def working_days_between(self, start: dt.date, end_exclusive: dt.date) -> int:
        """Count working days in ``[start, end_exclusive)`` — capped for safety."""
        if end_exclusive <= start:
            return 0
        count = 0
        day = start
        limit = min((end_exclusive - start).days, 800)
        for _ in range(limit):
            if await self.is_working_day(day):
                count += 1
            day += dt.timedelta(days=1)
        return count


def in_window(now: dt.datetime, start: dt.time, end: dt.time) -> bool:
    """Is the local clock inside ``[start, end)`` on the same day?"""
    current = now.time()
    return start <= current < end
