# Davomat boti — Telegram attendance bot

A Telegram bot that asks every employee twice a working day whether they will be at
work, collects a structured reason when they will not, chases non-responders every
15 minutes, and gives HR an Excel export of the whole thing.

The bot's interface is entirely in Uzbek (Latin). This README is in English.

---

## Contents

1. [What the bot does](#1-what-the-bot-does)
2. [Before you start](#2-before-you-start)
3. [Deploy on Railway](#3-deploy-on-railway)
4. [First-run checklist](#4-first-run-checklist)
5. [Environment variables](#5-environment-variables)
6. [Testing without waiting until 08:00](#6-testing-without-waiting-until-0800)
7. [Admin commands](#7-admin-commands)
8. [How the data is stored](#8-how-the-data-is-stored)
9. [Running it — the things that will bite you](#9-running-it--the-things-that-will-bite-you)
10. [Troubleshooting](#10-troubleshooting)
11. [Local development](#11-local-development)
12. [Design decisions](#12-design-decisions)
13. [Still open](#13-still-open)

---

## 1. What the bot does

### Registration — one choice, from the roster

`DEPARTMENT` and `NAME` are two parallel `|`-separated lists of the same length.
Entry *i* of one belongs to entry *i* of the other:

```
DEPARTMENT=Amaliyot departamenti direktori|Yuridik departamenti direktori|…|Moliya departamenti direktori
NAME=Akmalov Akmal|Axmadov Ravshan|…|Asadov Javoxir
```

…which means *Moliya departamenti direktori* is *Asadov Javoxir*. `DEPARTMENT`
carries the lavozim too, so there is no separate position question.

On `/start` the employee is shown a paged list of those entries and picks their
own. Their **F.I.SH. is filled in from `NAME`** — nobody ever types a name, so
HR's spelling is the only spelling. With 45 entries the list is 6 pages; typing
part of a lavozim or a surname searches it instead of scrolling.

| Column 1 | Column 2 | Column 3 |
|---|---|---|
| `full_name` — from `NAME` | `department` — the chosen entry, lavozim included | `telegram_id` |

Two consequences worth knowing:

- **One Telegram account per entry.** Picking a claimed slot tells you who
  holds it. Enforced by a partial unique index in the database, not just in the
  handler. Rejecting somebody frees their slot again.
- **`NAME` is authoritative.** Fix a typo in Railway, redeploy, and every
  matching employee row is corrected on boot — matched on the department text,
  so reordering or inserting entries is safe. Employees cannot edit their own
  name; button 1 only re-picks their slot, and the name follows.

The record starts as **pending**. An admin gets a card with **Tasdiqlash / Rad
etish** buttons; the bot does not poll the person until someone approves them.

Because the roster is a fixed list, the bot can also tell you who is *missing*:
`/roster` shows all 45 entries and their state, and `/pending` plus both daily
digests report the slots nobody has registered for.

### Every working day

```
08:00  ──▶  "Bugun — 07 Sentabr 2026, Dushanba — ishda bo'lasizmi?"   [✅ Ha] [❌ Yo'q]
              │
              ├── Ha  ──▶  recorded, done
              │
              └── Yo'q ──▶  was the previous answer also "Yo'q"?
                              │
                              ├── yes ──▶ show the old record ──▶ [✅ O'zgarish yo'q] [✏️ O'zgarish bor]
                              │                                        │                    │
                              │                                     reuse it            fall through ↓
                              └── no  ──────────────────────────────────────────────────────▶ pick a reason
                                                                                                   │
        🏥 Kasallik varaqasi          →  boshlanish sanasi, ishga chiqish sanasi (+ optional scan)
        ✈️ Xizmat safari              →  boshlanish, ishga chiqish, qayerga
        📄 Ish haqi saqlanmaydigan    →  boshlanish, ishga chiqish
        📝 Boshqalar                  →  boshlanish, ishga chiqish, izoh
                                                                                                   │
                                                                            summary ──▶ [✅ Tasdiqlash]
                                                                                                   │
                                                                          "✅ Muvaffaqiyatli yetkazildi."

08:15, 08:30 … 09:45  ──▶  reminder to anyone who has not answered
10:00                 ──▶  digest to admins: who is out, who never answered

17:00  ──▶  the same thing, asking about the next working day
17:15 … 18:45         ──▶  reminders
19:00                 ──▶  digest
```

Dates are picked from an inline month calendar (tap, don't type), but typing
`15.09.2026`, `15/09/2026`, `2026-09-15` or even `15.09` also works.

### The two persistent buttons

| Button | What it does |
|---|---|
| 👤 Lavozimni o'zgartirish | Shows the current F.I.SH. and lavozim, and lets the employee re-pick their roster entry — their name follows the new slot. Admins are notified of the change. |
| 📝 Yo'qlik haqida xabar berish | Reports an absence at any time, outside the 08:00/17:00 windows — the same four reasons and the same wizard. |

### Working week

Monday–**Saturday**, Sunday off, plus a holiday list stored in the database. The
holiday table also supports *transferred working days* (`is_workday = true`) for
when a day off is officially moved onto a Sunday. Nothing is ever sent on a
non-working day.

---

## 2. Before you start

You need four things. Budget about 15 minutes.

### 2.1 A bot token

1. Open [@BotFather](https://t.me/BotFather) in Telegram.
2. Send `/newbot`, give it a display name and a username ending in `bot`
   (e.g. `avotech_davomat_bot`).
3. BotFather replies with a token like `8012345678:AAH...`. **This is your
   `BOT_TOKEN`.** Treat it like a password — anyone holding it controls the bot.
4. While you are there, useful extras:
   - `/setdescription` — what employees see before pressing Start
   - `/setprivacy` → **Enable** — the bot then only sees commands in groups, which
     is the right setting for privacy
   - `/setuserpic` — a logo

### 2.2 Your Telegram numeric ID

You need this for `ADMIN_IDS`. The easiest way: deploy first, then send `/whoami`
to your own bot — it answers with your ID even before you are approved. Or message
[@userinfobot](https://t.me/userinfobot).

IDs are numbers like `123456789`, never `@usernames`.

### 2.3 A GitHub repository

Railway deploys from Git. Put this whole folder in a repo:

```bash
cd attendance-bot
git init
git add .
git commit -m "Davomat boti"
git branch -M main
git remote add origin git@github.com:YOUR-ORG/attendance-bot.git
git push -u origin main
```

`.gitignore` already excludes `.env`, so your token will not end up in Git — keep
it that way.

### 2.4 A Railway account

Sign up at [railway.com](https://railway.com). A paid plan is required for a
service that runs continuously; the entry plan includes usage credit and a bot of
this size plus a small Postgres sits at the low end of it. Check
[railway.com/pricing](https://railway.com/pricing) for current numbers.

---

## 3. Deploy on Railway

Railway moves its UI labels around from time to time. The five things you need to
accomplish are stable, so if a button is named slightly differently, look for the
one that does the same job.

### Step 1 — Create the project from your repo

1. Railway dashboard → **New Project** → **Deploy from GitHub repo**.
2. Authorise Railway for your GitHub account/org if asked, and pick the repo.
3. Railway starts a build immediately. **It will fail.** That is expected — there
   is no `BOT_TOKEN` or `DATABASE_URL` yet. Carry on.

`railway.toml` in the repo already sets the start command (`python main.py`), the
restart policy, and `overlapSeconds = 0` so a redeploy never briefly runs two
pollers.

### Step 2 — Add Postgres

1. In the project canvas, **+ Create** (or **+ New**) → **Database** →
   **Add PostgreSQL**.
2. Wait for it to go green. Note the service name in the canvas — it is normally
   **`Postgres`**. You need that exact name in the next step.

> **Do not use SQLite.** Railway's container filesystem is ephemeral: every
> redeploy would wipe the database. Postgres is the whole reason the bot survives
> deploys.

### Step 3 — Set the variables

Click your **bot service** (not the Postgres one) → **Variables** tab.

The fastest way is the **Raw Editor**. Paste this, then edit the values:

```
BOT_TOKEN=8012345678:AAH-paste-your-real-token-here
DATABASE_URL=${{Postgres.DATABASE_URL}}
ADMIN_IDS=123456789
TZ_NAME=Asia/Tashkent
```

Three things to get right:

- **`DATABASE_URL` must be the reference, typed literally as
  `${{Postgres.DATABASE_URL}}`** — braces and all. Railway resolves it to the
  Postgres service's internal connection string at deploy time. If you copy-paste
  the actual URL instead, it will break the day Railway rotates the password. If
  your database service is named something other than `Postgres`, use that name
  inside the braces.
- **`ADMIN_IDS`** takes numeric IDs, comma-separated for several people:
  `ADMIN_IDS=123456789,987654321`. Leave it wrong and nobody can approve
  registrations. (The bot notices an empty `ADMIN_IDS` and auto-approves everyone
  rather than locking the whole company out — but it logs a loud warning, and
  auto-approval is not what you want in production.)
- Everything else is optional. See [section 5](#5-environment-variables) for the
  full list; the defaults already match the spec.

### Step 4 — Pin the replica count to 1

Bot service → **Settings** → find **Replicas** (under Deploy).
**It must be 1.**

Telegram permits exactly one long-polling connection per token. Two replicas means
two processes fighting over `getUpdates`, `409 Conflict` in the logs, and employees
receiving every question twice.

While you are in Settings, you do **not** need to generate a public domain. This
is a worker, not a web service. (If you generate one anyway, Railway injects
`PORT` and the bot will serve `GET /` → `200 ok` so a healthcheck can pass.)

### Step 5 — Deploy and watch the logs

Saving variables triggers a redeploy. Open **Deployments** → **View Logs**. A
healthy boot looks like this:

```
2026-09-03 08:00:01 | INFO | bot.db     | Connected to Postgres (pool 1-5)
2026-09-03 08:00:01 | INFO | bot.db     | Schema applied
2026-09-03 08:00:01 | INFO | bot        | Seeded 16 default holidays
2026-09-03 08:00:02 | INFO | bot        | Started as @avotech_davomat_bot | tz=Asia/Tashkent | morning=08:00:00 | evening=17:00:00 | admins=[123456789]
```

The schema is created automatically on first boot — there is no migration step to
run. Every admin also receives a "🤖 Bot ishga tushdi" message on each deploy,
which doubles as confirmation that `ADMIN_IDS` is correct.

---

## 4. First-run checklist

Do this once, in order, before telling anyone about the bot.

- [ ] Open your bot in Telegram, send `/whoami`. Confirm the number matches
      `ADMIN_IDS`. If not, fix the variable and redeploy.
- [ ] Set `DEPARTMENT` and `NAME` in Railway. If the counts disagree the bot
      will not start and the log says both numbers.
- [ ] Send `/start`. Pick your own entry from the roster (or type part of your
      surname to find it), check the auto-filled F.I.SH., then **Tasdiqlash**.
- [ ] You should immediately receive the approval card (you are the admin). Tap
      **✅ Tasdiqlash**. You now have the two persistent buttons.
- [ ] Tap **📝 Yo'qlik haqida xabar berish**, walk through a business trip, confirm.
      You should get **"✅ Muvaffaqiyatli yetkazildi"** and a copy of the notice as
      admin.
- [ ] Send `/mening` — the record is listed with a cancel button. Cancel it.
- [ ] Send `/today`, then `/export`. The Excel file should arrive with four sheets.
- [ ] Set the year's holidays: `/holiday list 2026` shows what was seeded; add any
      that are missing (see [section 9](#9-running-it--the-things-that-will-bite-you)).
- [ ] Force a real 08:00 cycle using the trick in the next section.
- [ ] Only now share the bot's `@username` with staff, and tell them to send
      `/start`.

---

## 5. Environment variables

Required:

| Variable | Example | Notes |
|---|---|---|
| `BOT_TOKEN` | `8012345678:AAH…` | From @BotFather. |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Use the Railway reference, not a literal URL. |
| `ADMIN_IDS` | `123456789,987654321` | Numeric Telegram IDs. Approvals, digests, `/export`, `/absent`, `/malumot`, error reports. |
| `DEPARTMENT` | `Amaliyot departamenti direktori\|…` | The roster of lavozim entries, `\|`-separated. Position included — there is no separate lavozim variable. |
| `NAME` | `Akmalov Akmal\|…` | The people, in the **same order and the same count** as `DEPARTMENT`. |

> The bot refuses to boot if `DEPARTMENT` and `NAME` differ in length, if only
> one of them is set, or if `DEPARTMENT` repeats an entry. A miscounted `|` is
> then a startup error you see immediately, instead of the wrong person's name
> appearing on an official document. `DEPARTMENTS` is still accepted as an alias
> for `DEPARTMENT`.

Optional — every default already matches the agreed behaviour:

| Variable | Default | What it changes |
|---|---|---|
| `HR_CHAT_ID` | — | An extra group/channel that also receives every notification. Add the bot to the group, run `/whoami` there; group IDs start with `-100`. |
| `TZ_NAME` | `Asia/Tashkent` | Timezone for every schedule and every date shown. |
| `MORNING_TIME` | `08:00` | When the "today?" question goes out. |
| `MORNING_DEADLINE` | `10:00` | Reminders stop; digest is sent. |
| `EVENING_TIME` | `17:00` | When the "next working day?" question goes out. |
| `EVENING_DEADLINE` | `19:00` | Reminders stop; digest is sent. |
| `REMINDER_EVERY_MINUTES` | `15` | Gap between reminders. |
| `MAX_REMINDERS` | `8` | Hard cap per person per slot. |
| `WEEKEND_WEEKDAYS` | `6` | `0`=Monday … `6`=Sunday. `6` = Mon–Sat week. Use `5,6` for Mon–Fri. |
| `ASK_DURING_KNOWN_ABSENCE` | `true` | `true`: ask every working day even mid-absence (they get the "o'zgarish bormi?" shortcut). `false`: stay silent on covered days. |
| `REQUIRE_ADMIN_APPROVAL` | `true` | Turn off only if you trust everyone who can find the bot. |
| `ALLOW_ATTACHMENTS` | `true` | Offer a photo/file upload for sick-leave certificates. |
| `MAX_ABSENCE_DAYS` | `365` | Longest allowed absence. |
| `PAST_DATE_GRACE_DAYS` | `30` | How far back a start date may be (retroactive sick leave). |
| `FUTURE_DATE_HORIZON_DAYS` | `400` | How far ahead a date may be. |
| `DEPARTMENTS_PER_PAGE` | `8` | Roster entries per page in the picker. |
| `TICK_SECONDS` | `60` | Scheduler wake-up interval. Lower it only for testing. |
| `LOG_LEVEL` | `INFO` | `DEBUG` when investigating. |
| `DB_MIN_POOL` / `DB_MAX_POOL` | `1` / `5` | Connection pool bounds. |
| `PORT` | — | Injected by Railway only if the service has a domain. Enables `GET /` → `200 ok`. |

`.env.example` has the same list with comments, ready to copy.

### Getting the roster right

This is the one variable pair worth double-checking, because everything else
depends on it.

- Count the entries. `DEPARTMENT` and `NAME` must have the same number, and a
  trailing `|` creates an invisible empty entry. The bot tells you the two
  counts if they disagree.
- No `|` inside a name or a lavozim — it is the separator.
- Order matters only in that the two lists must line up. The order you choose
  is also the order rows appear in `/absent`, `/today` and the Word document,
  so putting the list in hierarchy order gives you correctly ordered reports
  for free.
- Write them in Latin. The МАЪЛУМОТ document transliterates to Cyrillic; any
  entry you write in Cyrillic is passed through untouched, which is the escape
  hatch if a particular name transliterates badly.

---

## 6. Testing without waiting until 08:00

You do not want to discover a problem at 08:00 on Monday in front of 200 people.

**Option A — temporarily move the clock windows.** In Railway Variables, set:

```
MORNING_TIME=00:00
MORNING_DEADLINE=23:59
REMINDER_EVERY_MINUTES=2
TICK_SECONDS=20
```

Save. Within ~20 seconds the morning question arrives, and reminders follow every
2 minutes until you answer. Walk through all four reasons. **Then put the real
values back** (or delete the overrides so the defaults apply).

**Option B — run it locally against the same schedule.** See
[section 11](#11-local-development). Stop the Railway service first, or you get
`409 Conflict` from two pollers.

Two details that make testing predictable:

- The question is only ever created **once** per person, per slot, per day. To
  re-test the same day, either use a second Telegram account or delete the row:
  `DELETE FROM check_ins WHERE telegram_id = 123456789;`
- Nothing is sent on a non-working day. If you are testing on a Sunday, add a
  transferred working day first: `/holiday workday 2026-09-06 Test`.

---

## 7. Admin commands

Available only to IDs in `ADMIN_IDS`.

| Command | What it does |
|---|---|
| `/admin` | Lists these commands. |
| `/absent 09.09.2026` | Approved employees whose absence covers that date, in roster order, with reason, dates, destination and comment. No date = today. |
| `/malumot 09.09.2026` | The same list as the official **МАЪЛУМОТ** Word document (see below). No date = today. |
| `/roster` | All `DEPARTMENT` entries and their state: ✅ approved, ⏳ pending, ❌ rejected, ⬜️ nobody registered. |
| `/pending` | Pending registrations with Approve/Reject buttons, today's non-responders, and the unclaimed roster slots. |
| `/today` | Everyone who is out today, with reason and dates. |
| `/export` | Excel workbook: **Xodimlar**, **Yo'qliklar**, **Javoblar**, **Bayramlar**. |
| `/holiday list [year]` | Shows the calendar. 🔴 = day off, 🟢 = transferred working day. |
| `/holiday add 2026-12-31 Yangi yil oldi` | Marks a day off. |
| `/holiday workday 2026-09-06 Ko'chirilgan` | Forces a normally-off day to be a working day. |
| `/holiday del 2026-12-31` | Removes the entry. |
| `/broadcast Xabar matni` | Sends a message to every approved employee, throttled. |
| `/whoami` | Your Telegram ID (works for everyone). |

Admins also receive, unprompted:

- an approval card for every new registration,
- a notice for every absence submitted,
- a notice when someone edits their personal data or cancels a record,
- the 10:00 and 19:00 digests,
- a ⚠️ **Nomuvofiqlik** warning when somebody answers "I'll be at work" on a day an
  active absence record still covers — usually an early return, and worth a phone
  call rather than a silent data edit,
- a 🐞 traceback if the bot hits an unhandled exception (first admin only).

### The МАЪЛУМОТ document

`/malumot 09.09.2026` produces `malumot_09.09.2026.docx`, built to match the
template you supplied: A4 portrait with the same margins, Times New Roman
throughout, 14pt bold headings, and a five-column bordered table.

| Template placeholder | Filled with |
|---|---|
| `DATEQ` | the date you passed, as `DD.MM.YYYY`, in the `(… й)` line |
| `SURNAMEQ` | the first word of `NAME`, **bold**, on its own line |
| `RestofthenameQ` | everything after that first space, not bold |
| `DEPARTMENTQ` | the employee's `DEPARTMENT` entry |
| `ABSENCEDAYQ` | the absence start date, bold |
| `REASONQ` | the absence reason, in brackets underneath |
| `ARRIVALDAYQ` | the return-to-work date, bold |

Rows are numbered and sorted by position in `DEPARTMENT`, so the document
follows your own ordering rather than the alphabet. Everything from `NAME`,
`DEPARTMENT` and the reason labels is transliterated Latin → Cyrillic to match
the Cyrillic headings — write an entry in Cyrillic in Railway if you want it
left exactly as typed.

Two things it deliberately does not do: it never lists a pending or rejected
registration, and it prints the reason only, without the business-trip
destination, because the template has no column for it. Say the word if you
want the destination appended to the reason.

---

## 8. How the data is stored

Five tables, created automatically. Connect with Railway's Postgres **Data** tab or
`psql` if you want to look around.

**`employees`** — the four columns from the spec plus bookkeeping.
`status` is `pending` / `approved` / `rejected`; `is_active` goes false
automatically when someone blocks the bot, which stops the scheduler wasting
requests on them.

**`absences`** — one row per submitted absence: `kind`
(`sick`/`trip`/`unpaid`/`other`), `start_date`, `return_date`, `destination`,
`comment`, optional `file_id`, and `source` (`morning`/`evening`/`manual`).
A database `CHECK` constraint enforces `return_date > start_date`.

> **`return_date` means the first day back at work.** An absence covers
> `start_date … return_date - 1`. This was ambiguous in the original spec and it is
> the one definition worth being sure about, because headcount reports depend on
> it. The wizard says so explicitly: *"Ya'ni ishga qaytadigan birinchi kun."*

**`check_ins`** — one row per question asked: which slot, which day it was about,
the yes/no answer, which absence it produced, how many reminders were sent.
`UNIQUE (telegram_id, slot, target_date)` is what makes the scheduler safe to
re-run.

**`holidays`** — `day`, `name`, `is_workday`. An explicit row always wins over the
weekly pattern, in both directions.

**`bot_meta`** — one-shot markers, so "send the 10:00 digest" happens exactly once
even across a restart.

Nothing is ever hard-deleted: cancelling sets `is_cancelled = true`, so the audit
trail survives.

---

## 9. Running it — the things that will bite you

**One replica. Always.** Covered above, and it is the single most likely thing to
go wrong. If you see `409 Conflict` in the logs, this is why.

**Holidays need attention every year.** The bot ships with the fixed Uzbek public
holidays for 2026 and 2027. It cannot know:

- **Ramazon hayit and Qurbon hayit**, which move each year;
- **transferred working days**, which are announced by government decree.

Each December, run `/holiday list <next year>`, then add what is missing. Wrong
holidays mean the bot pings 200 people on Navro'z, and nothing damages adoption
faster.

**Turn on database backups.** Postgres service → **Backups**. Do it now, not after
you need it. `/export` is a fine manual snapshot but it is not a backup strategy.

**Redeploys are safe but not invisible.** `overlapSeconds = 0` prevents dual
polling. `drop_pending_updates=True` means taps that arrived while the container
was restarting are discarded rather than replayed. Someone halfway through a
wizard when you deploy will see *"jarayon uzilib qoldi"* and has to tap again —
their question is not lost, because the next reminder re-offers it.

**Rotating the token.** `/revoke` in BotFather invalidates the old token
immediately. Update `BOT_TOKEN` in Railway; the redeploy picks it up. Chat history
and the database are unaffected.

**People who block the bot** are marked inactive automatically and drop out of the
polling list. They come back on their next `/start`. Watch for this: someone who
mutes or blocks the bot quietly stops appearing in the non-responder list, which
is exactly when HR stops noticing them. `/export` → **Xodimlar** sheet → the
**Faol** column shows `Yo'q` for them.

**Logs are not forever.** Railway retains a limited window. If you need long-term
records, `/export` on a schedule, or wire the logs to an external sink.

**Privacy.** Sick-leave dates and certificate scans are health data about
identifiable employees. Decide who may read the database and the exports, keep
`ADMIN_IDS` to the people who genuinely need it, and agree a retention period. The
bot keeps everything forever unless you delete rows yourself.

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Build fails, "no start command" | `railway.toml` should set `startCommand = "python main.py"`. Confirm it is committed at the repo root. |
| `Required environment variable 'BOT_TOKEN' is not set` | Set it in the bot service's Variables — not on the Postgres service. |
| `Required environment variable 'DATABASE_URL' is not set` | Add `DATABASE_URL=${{Postgres.DATABASE_URL}}`. Braces literal, and the name inside must match your database service's name. |
| `InvalidToken` on boot | Token mistyped, or an extra space/newline. Re-copy from BotFather. |
| `409 Conflict` repeating in the logs | Two pollers on one token. Replicas > 1, or the bot is also running on your laptop. |
| Every question arrives twice | Same cause as above. |
| Bot answers `/start` but never asks at 08:00 | (a) the person is still `pending` — run `/pending`; (b) today is not a working day — `/holiday list`; (c) `TZ_NAME` is wrong; (d) the container was asleep — check that Railway shows the deployment as active. |
| Nobody gets approval cards | `ADMIN_IDS` empty or wrong. Send `/whoami` and compare. |
| Reminders never arrive | The person already answered, `MAX_REMINDERS` is reached, or the current time is outside the window. |
| A button does nothing | It is from a message older than the current deployment; the bot replies "Bu savol allaqachon yopilgan". Use the persistent buttons. |
| `asyncpg` connection errors after idle | Normally self-healing via the pool. If persistent, check the Postgres service is running and that you used the internal `DATABASE_URL`. |
| `/export` produces an empty workbook | No data yet, or you are looking at a fresh database (e.g. you deleted and re-added the Postgres service). |
| Container restarts in a loop | Read the last 30 log lines. Almost always a bad variable value — a malformed `MORNING_TIME`, a non-numeric `ADMIN_IDS`, or an unknown `TZ_NAME`. |

Set `LOG_LEVEL=DEBUG` for a noisier picture, and remember to set it back.

---

## 11. Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# a throwaway Postgres
docker run -d --name attendance-db -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=attendance postgres:16

cp .env.example .env      # then edit BOT_TOKEN and ADMIN_IDS
set -a && source .env && set +a
python main.py
```

Use a **second bot** from BotFather for development. Pointing your laptop at the
production token gives you `409 Conflict` and a broken production bot.

### Tests

Two suites, both requiring a real Postgres (they truncate the tables, so point
them at a throwaway database):

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/attendance

python tests/smoke.py   # schema, every query, calendar, date parsing,
                        # callback-data limits, Excel export, handler wiring
python tests/flow.py    # drives the real handlers with fake Telegram objects:
                        # registration → approval → 08:00 prompt → each of the
                        # four wizards → 17:00 "o'zgarish bormi?" → reminders
```

`tests/flow.py` is the useful one when you change behaviour: it taps the buttons
the bot actually sent and asserts on what ends up in the database.

### Layout

```
main.py                    entry point, handler registration, lifecycle
bot/config.py              every environment variable
bot/schema.sql             the tables (idempotent, applied on boot)
bot/db.py                  asyncpg queries
bot/workdays.py            Mon–Sat + holidays calendar
bot/texts.py               every Uzbek string, in one place
bot/keyboards.py           keyboards, incl. the inline calendar
bot/flows.py               wizard state machines
bot/services.py            sending, retries, date parsing/validation
bot/jobs.py                the scheduler
bot/export.py              Excel workbook
bot/translit.py            Uzbek Latin -> Cyrillic (for the Word document)
bot/malumot.py             the MA'LUMOT Word document
bot/handlers/registration.py  /start and the profile button
bot/handlers/absence.py       check-ins and the four wizards
bot/handlers/admin.py         admin commands
bot/handlers/router.py        text dispatch, error handler
```

To reword anything employees see, edit `bot/texts.py` and nothing else.

---

## 12. Design decisions

**Long polling, not webhooks.** No public domain, no TLS, no URL to register. For
one bot and a few hundred users, polling is simpler and has fewer moving parts.
Webhooks would only matter at a scale you are not at.

**A one-minute tick instead of cron jobs.** The scheduler wakes every 60 seconds
and asks the database what still needs doing, rather than firing at exactly 08:00.
This is the most important design decision in the project, because it makes three
classes of bug impossible:

- *Missed runs.* If the container was redeploying at 08:00, the next tick notices
  people without a prompt and sends them.
- *Duplicates.* Prompts are created by a query that finds employees *without* a
  check-in row, guarded by a `UNIQUE` constraint. Running the tick twice cannot
  double-send.
- *Timezone drift.* Every comparison is against `datetime.now(ZoneInfo(TZ_NAME))`,
  so the container's UTC clock is irrelevant.

The cost is that a prompt may be up to 60 seconds late. Nobody notices.

**Reminders are throttled in SQL, not in memory.** `COALESCE(last_reminder_at,
created_at) < now() - interval` means a freshly-sent prompt is never nudged in the
same breath, and a restart cannot reset the reminder count.

**Where I went beyond your spec:**

- *The "o'zgarish bormi?" shortcut applies to the 08:00 question too*, not only
  17:00. You chose to keep asking every day during a known absence; without this,
  a ten-day sick leave would mean walking the full wizard twenty times. Now it is
  two taps. Set `ASK_DURING_KNOWN_ABSENCE=false` if you would rather have silence.
- *"Ha" answers are stored*, so you have real attendance data rather than only a
  record of absences.
- *Admin approval, sick-leave attachments, `/export`, the 10:00 and 19:00 digests,
  edit/cancel for your own records, and the early-return warning* were all
  additions. The digest in particular does more for compliance than the eighth
  reminder does.
- *Reminders escalate in tone* and are capped at `MAX_REMINDERS`, because eight
  identical pings in two hours is how a bot gets muted — and a muted bot is worse
  than a late answer, since it fails silently.

---

## 13. Still open

Things worth a decision at some point. None of them block launch.

1. **Half-days, remote work, and hourly leave** have no representation. If people
   need them, "Boshqalar" + a comment is the workaround, and the comment will not
   aggregate.
2. **Deputies and handovers.** One account per roster slot means an acting
   director cannot report on behalf of the person they are covering. Today the
   fix is to reject the old registration (which frees the slot) and let the
   deputy claim it, or to add a temporary `DEPARTMENT` entry.
3. **No approval workflow for the absences themselves.** The bot records what the
   employee says; a manager cannot confirm or dispute a business trip in the bot.
4. **No Russian/Cyrillic interface.** Adding it means a `language` column and
   turning each constant in `bot/texts.py` into a dict — cheap now, tedious later.
5. **Retention.** Health data accumulates forever. Agree a policy and a delete
   script.
6. **No integration with your HR system.** Data leaves via `/export` only. A daily
   push to 1C/Excel/an API is a small job if it becomes tedious.

---

## Uzbek glossary

| Uzbek | English |
|---|---|
| F.I.SH. | Full name (surname, first name, patronymic) |
| Departament / bo'lim | Department |
| Lavozim | Position |
| Kasallik varaqasi | Sick leave certificate |
| Xizmat safari | Business trip |
| Ish haqi saqlanmaydigan ta'til | Unpaid leave |
| Boshqalar | Other |
| Boshlanish sanasi | Start date |
| Ishga chiqish sanasi | Return-to-work date |
| Izoh | Comment |
| Muvaffaqiyatli yetkazildi | Successfully delivered |
| O'zgarish bormi? | Is there any change? |
| Dam olish kuni | Day off |
