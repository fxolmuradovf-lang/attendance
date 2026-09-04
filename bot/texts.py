"""All user-facing strings, in Uzbek (Latin script).

Everything the employee ever reads lives in this one file, so wording changes
never require touching the logic. If you later need Russian too, turn each
constant into a dict keyed by language code and add a ``language`` column to
``employees``.
"""

from __future__ import annotations

import datetime as dt

# --------------------------------------------------------------------- calendar

WEEKDAYS = (
    "Dushanba",
    "Seshanba",
    "Chorshanba",
    "Payshanba",
    "Juma",
    "Shanba",
    "Yakshanba",
)

WEEKDAYS_SHORT = ("Du", "Se", "Cho", "Pa", "Ju", "Sha", "Ya")

MONTHS = (
    "Yanvar",
    "Fevral",
    "Mart",
    "Aprel",
    "May",
    "Iyun",
    "Iyul",
    "Avgust",
    "Sentabr",
    "Oktabr",
    "Noyabr",
    "Dekabr",
)

KIND_LABELS = {
    "sick": "Kasallik varaqasi",
    "trip": "Xizmat safari",
    "unpaid": "Ish haqi saqlanmaydigan ta'til",
    "other": "Boshqalar",
}

KIND_EMOJI = {"sick": "🏥", "trip": "✈️", "unpaid": "📄", "other": "📝"}


def fmt_date(day: dt.date) -> str:
    """31.12.2026"""
    return day.strftime("%d.%m.%Y")


def fmt_date_long(day: dt.date) -> str:
    """31 Dekabr 2026, Payshanba"""
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}, {WEEKDAYS[day.weekday()]}"


def fmt_month(year: int, month: int) -> str:
    return f"{MONTHS[month - 1]} {year}"


def kind_label(kind: str) -> str:
    return f"{KIND_EMOJI.get(kind, '•')} {KIND_LABELS.get(kind, kind)}"


# ----------------------------------------------------------------- main buttons

BTN_EDIT_PROFILE = "👤 Lavozimni o'zgartirish"
BTN_REPORT_ABSENCE = "📝 Yo'qlik haqida xabar berish"

BTN_YES = "✅ Ha"
BTN_NO = "❌ Yo'q"
BTN_NO_CHANGES = "✅ O'zgarish yo'q"
BTN_HAS_CHANGES = "✏️ O'zgarish bor"
BTN_CONFIRM = "✅ Tasdiqlash"
BTN_RESTART = "🔄 Boshidan"
BTN_CANCEL = "✖️ Bekor qilish"
BTN_BACK = "⬅️ Orqaga"
BTN_SKIP = "⏭ O'tkazib yuborish"
BTN_TODAY = "📅 Bugun"
BTN_TOMORROW = "📅 Ertaga"

# ---------------------------------------------------------------- registration

START_NEW = (
    "Assalomu alaykum! 👋\n\n"
    "Bu bot xodimlarning ishda bo'lishi/bo'lmasligini qayd etib boradi.\n\n"
    "Ro'yxatdan o'tish uchun ro'yxatdan <b>o'z lavozimingizni</b> tanlang — "
    "F.I.SH. avtomatik to'ldiriladi."
)

ASK_DEPARTMENT_PICK = (
    "🏢 <b>Lavozimingizni tanlang.</b>\n\n"
    "<i>Ro'yxat uzun bo'lsa, ⬅️ ➡️ tugmalari bilan varaqlang yoki "
    "familiyangiz/lavozimingizning bir qismini yozib qidiring.</i>"
)

ASK_DEPARTMENT_SEARCH_EMPTY = (
    "🔍 <b>{query}</b> bo'yicha hech narsa topilmadi.\n\n"
    "Boshqa so'z bilan qidirib ko'ring yoki ro'yxatni varaqlang."
)


def department_search_results(query: str, found: int) -> str:
    return (
        f"🔍 <b>{query}</b> bo'yicha {found} ta natija:\n\n"
        "<i>Kerakli lavozimni tanlang, yoki boshqa so'z yozib qayta qidiring.</i>"
    )


ROSTER_NOT_CONFIGURED = (
    "⚙️ Bot hali to'liq sozlanmagan: lavozimlar ro'yxati kiritilmagan.\n\n"
    "Iltimos, administratorga murojaat qiling."
)


def slot_taken(department: str, holder: str) -> str:
    return (
        "🔒 <b>Bu lavozim allaqachon band.</b>\n\n"
        f"🏢 {department}\n"
        f"👤 {holder}\n\n"
        "Agar bu xato bo'lsa yoki lavozim sizga o'tgan bo'lsa, "
        "administratorga murojaat qiling."
    )


BAD_SHORT_TEXT = "❗️ Juda qisqa. Iltimos, kamida 2 belgi kiriting."
BAD_LONG_TEXT = "❗️ Juda uzun. Iltimos, {limit} belgidan oshmasin."
EXPECTED_TEXT = "❗️ Iltimos, matn ko'rinishida yuboring."


def registration_summary(full_name: str, department: str) -> str:
    return (
        "Ma'lumotlaringizni tekshirib chiqing:\n\n"
        f"👤 <b>F.I.SH.:</b> {full_name}\n"
        f"🏢 <b>Lavozim:</b> {department}\n\n"
        "Hammasi to'g'rimi?"
    )


REGISTRATION_PENDING = (
    "✅ Ma'lumotlaringiz qabul qilindi.\n\n"
    "⏳ Administrator tasdiqlashini kuting. Tasdiqlangandan so'ng bot sizga "
    "har kuni soat 08:00 va 17:00 da savol yuboradi."
)

REGISTRATION_DONE = (
    "✅ Ma'lumotlaringiz saqlandi!\n\n"
    "Endi bot har kuni soat <b>08:00</b> da bugungi, <b>17:00</b> da esa "
    "keyingi ish kuni haqida savol yuboradi.\n\n"
    "Pastdagi tugmalardan istalgan vaqtda foydalanishingiz mumkin."
)

APPROVED_NOTICE = (
    "🎉 Ma'lumotlaringiz administrator tomonidan tasdiqlandi!\n\n"
    "Endi bot har kuni soat <b>08:00</b> va <b>17:00</b> da savol yuboradi."
)

REJECTED_NOTICE = (
    "❌ Afsuski, ma'lumotlaringiz tasdiqlanmadi.\n"
    "Iltimos, Inson resurslarini boshqarish departamentiga murojaat qiling "
    "yoki /start bilan qaytadan urinib ko'ring."
)

NOT_REGISTERED = "Siz hali ro'yxatdan o'tmagansiz. /start buyrug'ini yuboring."

NOT_APPROVED_YET = (
    "⏳ Ma'lumotlaringiz hali tasdiqlanmagan. Administrator tasdiqlashini kuting."
)


def profile_view(full_name: str, department: str, telegram_id: int) -> str:
    return (
        "👤 <b>Shaxsiy ma'lumotlaringiz</b>\n\n"
        f"<b>F.I.SH.:</b> {full_name}\n"
        f"<b>Lavozim:</b> {department}\n"
        f"<b>Telegram ID:</b> <code>{telegram_id}</code>\n\n"
        "<i>F.I.SH. lavozimga bog'langan va avtomatik to'ldiriladi. "
        "Ismingizda xatolik bo'lsa, administratorga murojaat qiling.</i>"
    )


PROFILE_UPDATED = "✅ Ma'lumotlaringiz yangilandi."

# -------------------------------------------------------------------- check-in


def ask_today(full_name: str, day: dt.date) -> str:
    return (
        f"🌅 Xayrli tong, <b>{full_name}</b>!\n\n"
        f"Bugun — <b>{fmt_date_long(day)}</b> — ishda bo'lasizmi?"
    )


def ask_next_day(full_name: str, day: dt.date, today: dt.date) -> str:
    when = "Ertaga" if day == today + dt.timedelta(days=1) else "Keyingi ish kuni"
    return (
        f"🌆 Xayrli kech, <b>{full_name}</b>!\n\n"
        f"{when} — <b>{fmt_date_long(day)}</b> — ishda bo'lasizmi?"
    )


def ask_manual() -> str:
    return "Yo'qligingiz sababini tanlang:"


PRESENT_RECORDED = "✅ Rahmat! Javobingiz qayd etildi: <b>ishda bo'laman</b>."

ASK_KIND = "Yo'qligingiz sababini tanlang:"

ASK_START_DATE = "📅 <b>Yo'qlik boshlanish sanasini</b> tanlang:"
ASK_RETURN_DATE = (
    "📅 <b>Ishga chiqish sanasini</b> tanlang.\n\n"
    "<i>Ya'ni ishga qaytadigan birinchi kun. Masalan, 10-sentabrda ishga "
    "qaytsangiz, 10.09 ni tanlang.</i>"
)
ASK_DESTINATION = (
    "📍 <b>Qayerga xizmat safari?</b>\n\n<i>Masalan: Samarqand / Toshkent, Moliya vazirligi</i>"
)
ASK_COMMENT = "💬 <b>Izoh kiriting:</b>\n\n<i>Yo'qlik sababini qisqacha yozing.</i>"
ASK_ATTACHMENT = (
    "📎 Agar kasallik varaqasi rasmi yoki fayli bo'lsa, yuboring.\n"
    "<i>Majburiy emas — o'tkazib yuborishingiz mumkin.</i>"
)
ATTACHMENT_SAVED = "📎 Fayl saqlandi."
ATTACHMENT_BAD = "❗️ Iltimos, rasm yoki fayl yuboring, yoki «O'tkazib yuborish» ni bosing."

DATE_RETURN_BEFORE_START = (
    "❗️ Ishga chiqish sanasi boshlanish sanasidan keyin bo'lishi kerak.\n"
    "Boshlanish sanasi: <b>{start}</b>. Iltimos, kechroq sanani tanlang."
)
DATE_TOO_FAR_PAST = "❗️ Bu sana juda uzoq o'tmishda ({limit} kundan oshiq). Iltimos, tekshirib ko'ring."
DATE_TOO_FAR_FUTURE = "❗️ Bu sana juda uzoq kelajakda. Iltimos, tekshirib ko'ring."
DATE_RANGE_TOO_LONG = "❗️ Yo'qlik davri {limit} kundan oshmasligi kerak."
BAD_DATE_FORMAT = (
    "❗️ Sanani tushunmadim. Kalendardan tanlang yoki <code>KK.OO.YYYY</code> "
    "ko'rinishida yozing (masalan <code>15.09.2026</code>)."
)


def absence_summary(
    *,
    kind: str,
    start_date: dt.date,
    return_date: dt.date,
    destination: str | None,
    comment: str | None,
    has_file: bool = False,
    days: int | None = None,
) -> str:
    lines = [
        "Ma'lumotlarni tekshirib chiqing:\n",
        f"{kind_label(kind)}",
        f"📅 <b>Boshlanish:</b> {fmt_date(start_date)} ({WEEKDAYS[start_date.weekday()]})",
        f"📅 <b>Ishga chiqish:</b> {fmt_date(return_date)} ({WEEKDAYS[return_date.weekday()]})",
    ]
    if days is not None:
        lines.append(f"🗓 <b>Ish kunlari:</b> {days} kun")
    if destination:
        lines.append(f"📍 <b>Qayerga:</b> {destination}")
    if comment:
        lines.append(f"💬 <b>Izoh:</b> {comment}")
    if has_file:
        lines.append("📎 <b>Fayl:</b> biriktirilgan")
    lines.append("\nHammasi to'g'rimi?")
    return "\n".join(lines)


DELIVERED = "✅ <b>Muvaffaqiyatli yetkazildi.</b>"


def delivered_with_summary(
    *,
    kind: str,
    start_date: dt.date,
    return_date: dt.date,
    destination: str | None,
    comment: str | None,
) -> str:
    lines = [
        "✅ <b>Muvaffaqiyatli yetkazildi.</b>\n",
        f"{kind_label(kind)}",
        f"📅 {fmt_date(start_date)} — {fmt_date(return_date)} gacha",
    ]
    if destination:
        lines.append(f"📍 {destination}")
    if comment:
        lines.append(f"💬 {comment}")
    return "\n".join(lines)


def previous_details(
    *,
    kind: str,
    start_date: dt.date,
    return_date: dt.date,
    destination: str | None,
    comment: str | None,
) -> str:
    lines = [
        "Oldingi javobingizda ham ishda bo'lmasligingizni bildirgansiz.\n",
        "<b>Oldingi tafsilotlar:</b>",
        f"{kind_label(kind)}",
        f"📅 <b>Boshlanish:</b> {fmt_date(start_date)}",
        f"📅 <b>Ishga chiqish:</b> {fmt_date(return_date)}",
    ]
    if destination:
        lines.append(f"📍 <b>Qayerga:</b> {destination}")
    if comment:
        lines.append(f"💬 <b>Izoh:</b> {comment}")
    lines.append("\n<b>O'zgarish bormi?</b>")
    return "\n".join(lines)


NO_CHANGES_RECORDED = "✅ Rahmat! Oldingi ma'lumotlar o'zgarishsiz qayd etildi."

# ------------------------------------------------------------------- reminders

REMINDER_LEVELS = (
    "⏰ Eslatma: savolga javob bermadingiz.",
    "⏰ Iltimos, javob bering — Inson resurslarini boshqarish departamenti "
    "kutib turibdi.",
    "⚠️ Diqqat: javobingiz hali ham yo'q.",
    "⚠️ Oxirgi eslatmalardan biri — iltimos, javob bering.",
)


def reminder_text(level: int, deadline: dt.time) -> str:
    idx = min(level, len(REMINDER_LEVELS) - 1)
    return (
        f"{REMINDER_LEVELS[idx]}\n\n"
        f"Javob berish muddati: <b>{deadline.strftime('%H:%M')}</b> gacha."
    )


STALE_BUTTON = "Bu savol allaqachon yopilgan. Yangi savolni kuting yoki tugmadan foydalaning."
ALREADY_ANSWERED = "Siz bu savolga javob bergansiz."
FLOW_LOST = (
    "Kechirasiz, jarayon uzilib qoldi (bot qayta ishga tushdi). "
    "Iltimos, pastdagi tugma orqali qaytadan boshlang."
)
CANCELLED = "✖️ Bekor qilindi."

# ------------------------------------------------------------------ my records

NO_ACTIVE_ABSENCE = "Sizda faol yo'qlik yozuvi yo'q."


def my_absence_line(
    *, kind: str, start_date: dt.date, return_date: dt.date, destination: str | None
) -> str:
    tail = f" — 📍 {destination}" if destination else ""
    return f"{kind_label(kind)}: {fmt_date(start_date)} → {fmt_date(return_date)}{tail}"


ABSENCE_CANCELLED = "🗑 Yozuv bekor qilindi."

HELP_TEXT = (
    "<b>Buyruqlar</b>\n"
    "/start — ro'yxatdan o'tish yoki asosiy menyu\n"
    "/menu — asosiy menyu\n"
    "/mening — faol yo'qlik yozuvlarim\n"
    "/help — yordam\n\n"
    "<b>Tugmalar</b>\n"
    f"{BTN_EDIT_PROFILE} — lavozimni o'zgartirish\n"
    f"{BTN_REPORT_ABSENCE} — istalgan vaqtda yo'qlik haqida xabar berish"
)

MENU_TEXT = "Asosiy menyu. Kerakli tugmani tanlang."

# ----------------------------------------------------------------------- admin

ADMIN_ONLY = "Bu buyruq faqat administratorlar uchun."

ADMIN_HELP = (
    "<b>Administrator buyruqlari</b>\n"
    "/absent 09.09.2026 — o'sha kuni ishda bo'lmaganlar ro'yxati\n"
    "/malumot 09.09.2026 — o'sha kun uchun MAʼLUMOT (Word fayl)\n"
    "/today — bugun ishda bo'lmaganlar\n"
    "/pending — tasdiqlanmagan xodimlar, javob bermaganlar, bo'sh lavozimlar\n"
    "/roster — lavozimlar ro'yxati va kim band qilgani\n"
    "/export — barcha ma'lumotlarni Excel faylda olish\n"
    "/holiday list [yil] — bayramlar ro'yxati\n"
    "/holiday add YYYY-MM-DD Nomi — dam olish kuni qo'shish\n"
    "/holiday workday YYYY-MM-DD Nomi — ish kuniga ko'chirilgan kun\n"
    "/holiday del YYYY-MM-DD — o'chirish\n"
    "/broadcast matn — barcha xodimlarga xabar\n"
    "/whoami — Telegram ID ni ko'rish\n\n"
    "<i>Sana ko'rsatilmasa, bugungi kun olinadi.</i>"
)

USAGE_ABSENT = (
    "Foydalanish: <code>/absent 09.09.2026</code>\n\n"
    "Sana <code>KK.OO.YYYY</code> ko'rinishida bo'lishi kerak. "
    "Sanani yozmasangiz, bugungi kun olinadi."
)

USAGE_MALUMOT = (
    "Foydalanish: <code>/malumot 09.09.2026</code>\n\n"
    "Sana <code>KK.OO.YYYY</code> ko'rinishida bo'lishi kerak. "
    "Sanani yozmasangiz, bugungi kun olinadi."
)


def absent_report_header(day: dt.date, count: int) -> str:
    return (
        f"📋 <b>{fmt_date_long(day)}</b>\n"
        f"Ishda bo'lmagan tasdiqlangan xodimlar: <b>{count}</b>\n"
    )


def no_absences_on(day: dt.date) -> str:
    return f"✅ {fmt_date(day)} kuni ishda bo'lmagan xodim yo'q."


def malumot_caption(day: dt.date, count: int) -> str:
    return (
        f"📄 <b>MAʼLUMOT — {fmt_date(day)}</b>\n"
        f"Ro'yxatda {count} nafar xodim."
    )


def roster_coverage(registered: int, total: int) -> str:
    return f"👥 <b>Ro'yxat:</b> {registered} / {total} lavozim band qilingan."


ROSTER_FREE_HEADER = "<b>Bo'sh lavozimlar (hech kim ro'yxatdan o'tmagan):</b>"


def admin_new_registration(
    *, full_name: str, department: str, telegram_id: int, username: str | None
) -> str:
    handle = f"@{username}" if username else "—"
    return (
        "🆕 <b>Yangi ro'yxatdan o'tish</b>\n\n"
        f"👤 <b>F.I.SH.:</b> {full_name}\n"
        f"🏢 <b>Lavozim:</b> {department}\n"
        f"🆔 <b>Telegram ID:</b> <code>{telegram_id}</code>\n"
        f"🔗 <b>Username:</b> {handle}"
    )


def admin_profile_changed(*, full_name: str, department: str, telegram_id: int) -> str:
    return (
        "✏️ <b>Xodim lavozimini o'zgartirdi</b>\n\n"
        f"👤 {full_name}\n"
        f"🏢 {department}\n"
        f"🆔 <code>{telegram_id}</code>"
    )


def admin_absence_notice(
    *,
    full_name: str,
    department: str,
    kind: str,
    start_date: dt.date,
    return_date: dt.date,
    destination: str | None,
    comment: str | None,
) -> str:
    lines = [
        "📨 <b>Yangi yo'qlik xabari</b>\n",
        f"👤 {full_name} ({department})",
        f"{kind_label(kind)}",
        f"📅 {fmt_date(start_date)} → {fmt_date(return_date)}",
    ]
    if destination:
        lines.append(f"📍 {destination}")
    if comment:
        lines.append(f"💬 {comment}")
    return "\n".join(lines)


BTN_ADMIN_APPROVE = "✅ Tasdiqlash"
BTN_ADMIN_REJECT = "❌ Rad etish"

NO_PENDING = "Tasdiqlanmagan xodimlar yo'q."
NO_ABSENCES_TODAY = "Bugun hamma ishda. 🎉"
NOBODY_PENDING_ANSWER = "Hamma javob bergan. ✅"
