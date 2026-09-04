-- Applied on every boot. Every statement must be idempotent.

CREATE TABLE IF NOT EXISTS employees (
    telegram_id  BIGINT      PRIMARY KEY,
    -- full_name comes from the NAME env var, never typed by the employee.
    full_name    TEXT        NOT NULL,
    -- department carries the lavozim too, e.g. "Moliya departamenti direktori".
    -- It is the roster slot: exactly one live employee may hold each value.
    department   TEXT        NOT NULL,
    -- Legacy. The lavozim question was removed once DEPARTMENT started
    -- carrying it; kept nullable so no existing data is destroyed.
    position     TEXT,
    username     TEXT,
    status       TEXT        NOT NULL DEFAULT 'pending',  -- pending|approved|rejected
    is_active    BOOLEAN     NOT NULL DEFAULT TRUE,       -- FALSE when the user blocked the bot
    approved_by  BIGINT,
    approved_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS employees_status_idx ON employees (status, is_active);

-- One Telegram account per roster slot. Partial, so rejecting somebody frees
-- their department for the next person. This is the database-level backstop;
-- the handler also checks and gives a friendly message.
CREATE UNIQUE INDEX IF NOT EXISTS employees_department_slot_idx
    ON employees (department) WHERE status <> 'rejected';

-- Migration for databases created before the lavozim question was removed.
ALTER TABLE employees ALTER COLUMN position DROP NOT NULL;

CREATE TABLE IF NOT EXISTS absences (
    id           BIGSERIAL   PRIMARY KEY,
    telegram_id  BIGINT      NOT NULL REFERENCES employees (telegram_id) ON DELETE CASCADE,
    kind         TEXT        NOT NULL,   -- sick | trip | unpaid | other
    start_date   DATE        NOT NULL,   -- boshlanish sanasi
    return_date  DATE        NOT NULL,   -- ishga chiqish sanasi (first day BACK at work)
    destination  TEXT,                   -- xizmat safari uchun: qayerga
    comment      TEXT,                   -- boshqalar uchun: izoh
    file_id      TEXT,                   -- optional Telegram file_id of a scan/photo
    file_kind    TEXT,                   -- photo | document
    source       TEXT        NOT NULL,   -- morning | evening | manual
    target_date  DATE,                   -- the day the question was about (NULL for manual)
    is_cancelled BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT absences_dates_ck CHECK (return_date > start_date)
);

CREATE INDEX IF NOT EXISTS absences_employee_idx  ON absences (telegram_id, start_date DESC);
CREATE INDEX IF NOT EXISTS absences_range_idx     ON absences (start_date, return_date)
    WHERE is_cancelled = FALSE;

CREATE TABLE IF NOT EXISTS check_ins (
    id               BIGSERIAL   PRIMARY KEY,
    telegram_id      BIGINT      NOT NULL REFERENCES employees (telegram_id) ON DELETE CASCADE,
    slot             TEXT        NOT NULL,   -- morning | evening
    target_date      DATE        NOT NULL,   -- the working day being asked about
    asked_on         DATE        NOT NULL,   -- the day the question was sent
    answer           BOOLEAN,                -- NULL = still unanswered
    answered_at      TIMESTAMPTZ,
    absence_id       BIGINT      REFERENCES absences (id) ON DELETE SET NULL,
    chat_id          BIGINT,
    message_id       BIGINT,
    reminders        INTEGER     NOT NULL DEFAULT 0,
    last_reminder_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- This is what makes the scheduler restart-safe: a redeploy at 08:07 cannot
    -- create a second prompt for the same person, slot and day.
    CONSTRAINT check_ins_unique UNIQUE (telegram_id, slot, target_date)
);

CREATE INDEX IF NOT EXISTS check_ins_pending_idx ON check_ins (asked_on, slot)
    WHERE answer IS NULL;
CREATE INDEX IF NOT EXISTS check_ins_history_idx ON check_ins (telegram_id, created_at DESC);

CREATE TABLE IF NOT EXISTS holidays (
    day        DATE    PRIMARY KEY,
    name       TEXT    NOT NULL,
    -- FALSE: a day off that would otherwise be a working day.
    -- TRUE:  a transferred working day (ish kuniga ko'chirilgan dam olish kuni).
    is_workday BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Small key/value table for bookkeeping such as "did we already seed holidays".
CREATE TABLE IF NOT EXISTS bot_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
