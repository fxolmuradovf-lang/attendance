"""In-memory wizard state.

Kept in ``context.user_data`` rather than the database on purpose: a wizard is
seconds-to-minutes long, and if the container restarts mid-wizard the 15-minute
reminder job will re-offer the question, so nothing is permanently lost. The
user just sees :data:`bot.texts.FLOW_LOST` and taps again.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from telegram.ext import ContextTypes

from .keyboards import new_token

# --- absence wizard steps ---
STEP_KIND = "kind"
STEP_START = "start"
STEP_RETURN = "return"
STEP_DESTINATION = "destination"
STEP_COMMENT = "comment"
STEP_ATTACHMENT = "attachment"
STEP_CONFIRM = "confirm"

# --- registration wizard steps ---
# There is no name step any more: full_name comes from the NAME env var, paired
# with the DEPARTMENT entry the employee picks.
STEP_DEPT = "dept"
STEP_REG_CONFIRM = "reg_confirm"

ABSENCE_KEY = "absence_flow"
REG_KEY = "reg_flow"


@dataclass
class AbsenceFlow:
    source: str  # morning | evening | manual
    token: str = field(default_factory=new_token)
    step: str = STEP_KIND
    kind: str | None = None
    start_date: dt.date | None = None
    return_date: dt.date | None = None
    destination: str | None = None
    comment: str | None = None
    file_id: str | None = None
    file_kind: str | None = None
    check_in_id: int | None = None
    target_date: dt.date | None = None
    cal_year: int | None = None
    cal_month: int | None = None

    def reset_answers(self) -> None:
        self.kind = None
        self.start_date = None
        self.return_date = None
        self.destination = None
        self.comment = None
        self.file_id = None
        self.file_kind = None
        self.step = STEP_KIND

    def needs_destination(self) -> bool:
        return self.kind == "trip"

    def needs_comment(self) -> bool:
        return self.kind == "other"

    def as_kwargs(self) -> dict[str, Any]:
        assert self.kind and self.start_date and self.return_date
        return {
            "kind": self.kind,
            "start_date": self.start_date,
            "return_date": self.return_date,
            "destination": self.destination,
            "comment": self.comment,
            "file_id": self.file_id,
            "file_kind": self.file_kind,
            "source": self.source,
            "target_date": self.target_date,
        }


@dataclass
class RegFlow:
    token: str = field(default_factory=new_token)
    step: str = STEP_DEPT
    full_name: str | None = None
    department: str | None = None
    # Roster-picker view state.
    page: int = 0
    query: str | None = None
    # True when an already-registered employee is changing their slot.
    is_edit: bool = False


# --------------------------------------------------------------------- accessors


def get_absence(context: ContextTypes.DEFAULT_TYPE) -> AbsenceFlow | None:
    value = context.user_data.get(ABSENCE_KEY) if context.user_data is not None else None
    return value if isinstance(value, AbsenceFlow) else None


def set_absence(context: ContextTypes.DEFAULT_TYPE, flow: AbsenceFlow) -> None:
    context.user_data[ABSENCE_KEY] = flow


def clear_absence(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data is not None:
        context.user_data.pop(ABSENCE_KEY, None)


def get_reg(context: ContextTypes.DEFAULT_TYPE) -> RegFlow | None:
    value = context.user_data.get(REG_KEY) if context.user_data is not None else None
    return value if isinstance(value, RegFlow) else None


def set_reg(context: ContextTypes.DEFAULT_TYPE, flow: RegFlow) -> None:
    context.user_data[REG_KEY] = flow


def clear_reg(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data is not None:
        context.user_data.pop(REG_KEY, None)


def clear_all(context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_absence(context)
    clear_reg(context)


def token_matches(flow: AbsenceFlow | RegFlow | None, token: str) -> bool:
    return flow is not None and flow.token == token
