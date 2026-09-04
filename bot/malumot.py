"""The MAʼLUMOT Word document.

Reproduces A.docx. Every constant below was read out of that file's XML rather
than eyeballed, so the output matches it run for run:

* A4 portrait, the template's exact margins, Times New Roman throughout.
* Headings 14pt bold — the two title lines in navy ``#002060``, MAʼLUMOT in
  red ``#C00000``.
* The ``(DD.MM.YYYY й)`` date line right-aligned and fully *italic*, 12pt.
* A five-column table with **no borders at all** (the template sets every
  border to ``none``), column widths in twips, every cell vertically centred.
* Header row shaded ``#F2F2F2`` with navy bold 14pt text.
* Surname in ``#002060``, bold, ALL CAPS, on its own line above the rest of
  the name, which is black and not bold.
* Table dates written as day + Cyrillic month name — "4 сентябрь". The heading
  date stays numeric, ``04.09.2026``.
* The trailing parenthesis that makes a shared title unique in DEPARTMENT —
  "Раис ўринбосари (Фазилов)" — dropped from the Лавозими column, leaving
  "Раис ўринбосари". See :func:`clean_department`.

Placeholder → source mapping, as specified in A.docx:

    DATEQ            the date the report is for, DD.MM.YYYY
    SURNAMEQ         first word of NAME, upper-cased, navy, bold, own line
    RestofthenameQ   everything after that first space, black, not bold
    DEPARTMENTQ      the DEPARTMENT entry, minus its trailing parenthesis
    ABSENCEDAYQ      absence start date, bold
    REASONQ          the absence reason, in brackets
    ARRIVALDAYQ      return-to-work date, bold

Everything drawn from DEPARTMENT/NAME is transliterated Latin → Cyrillic so the
table matches the Cyrillic headings.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from typing import Any, Iterable, Sequence

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt, RGBColor, Twips

from . import texts
from .translit import split_name, transliterate

# --- page geometry, measured from A.docx (EMU) -------------------------------
PAGE_WIDTH = 7560310
PAGE_HEIGHT = 10692130
MARGIN_LEFT = 900430
MARGIN_RIGHT = 359410
MARGIN_TOP = 360045
MARGIN_BOTTOM = 360045

# --- table geometry, measured from A.docx (twips = 1/20 pt) ------------------
# A.docx carries two disagreeing sets of widths — w:tblGrid and the per-cell
# w:tcW — as Word files often do after columns have been dragged by hand.
# Rendering the original shows w:tblGrid is the set that actually takes effect,
# and it is also the one with room for a month name in the last column.
# Both sets sum to 9923 twips = the table width = the full text column.
COLUMN_WIDTHS_TWIPS = (652, 2426, 2729, 2073, 2043)
TABLE_WIDTH_TWIPS = sum(COLUMN_WIDTHS_TWIPS)
DATA_ROW_HEIGHT_TWIPS = 1150

FONT = "Times New Roman"
SIZE_TITLE = Pt(14)
SIZE_BODY = Pt(12)

# --- palette, from A.docx ----------------------------------------------------
NAVY = RGBColor(0x00, 0x20, 0x60)
RED = RGBColor(0xC0, 0x00, 0x00)
BLACK = RGBColor(0x00, 0x00, 0x00)
HEADER_FILL = "F2F2F2"

TITLE_LINE_1 = "ИШ ЖОЙИДА БЎЛМАГАН МАРКАЗИЙ БАНК"
TITLE_LINE_2 = "РАҲБАР ХОДИМЛАРИ ТЎҒРИСИДА"
TITLE_LINE_3 = "МАЪЛУМОТ"
HEADERS = ("Т/Р", "Ф.И.Ш.", "Лавозими", "Кетган куни", "Ишга чиқиш куни")

# Uzbek Cyrillic month names, nominative — "4 сентябрь".
MONTHS_CYRILLIC = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)

# A DEPARTMENT entry has to be unique, because it doubles as the roster slot
# key. Where several people share a title, the entries are told apart by a
# parenthesised surname — "Раис ўринбосари (Фазилов)". The МАЪЛУМОТ table does
# not want that disambiguator: the Ф.И.Ш. column already names the person, so
# the Лавозими column shows the bare title.
#
# The rule is structural rather than a list of phrases, so it works for any
# duplicated title and in either script. Only a *trailing* parenthesis is
# dropped; one in the middle of a title is assumed to be part of it.
STRIP_TRAILING_PARENTHESES = True

_TRAILING_PARENTHESIS = re.compile(r"\s*\([^()]*\)\s*$")


def fmt_day_month(day: dt.date) -> str:
    """``4 сентябрь`` — day plus Cyrillic month name, no year."""
    return f"{day.day} {MONTHS_CYRILLIC[day.month - 1]}"


def fmt_heading_date(day: dt.date) -> str:
    """``04.09.2026`` for the ``(… й)`` line."""
    return day.strftime("%d.%m.%Y")


def clean_department(text: str | None) -> str:
    """Transliterate the lavozim and drop the disambiguating surname.

    ``"Раис ўринбосари (Фазилов)"`` → ``"Раис ўринбосари"``.

    Repeated trailing groups are all removed, and whitespace plus any comma or
    dash left dangling by the removal is tidied. If stripping would empty the
    cell — an entry that is nothing but a parenthesis — the original is kept,
    because a blank Лавозими is worse than an untidy one.
    """
    out = transliterate(text)
    if STRIP_TRAILING_PARENTHESES:
        while True:
            shorter = _TRAILING_PARENTHESIS.sub("", out)
            if shorter == out:
                break
            out = shorter
        if not out.strip(" ,;-–—"):
            out = transliterate(text)
    out = " ".join(out.split())
    return out.strip(" ,;-–—")


# ------------------------------------------------------------------- low level


def _style_run(run, *, bold: bool, size, color: RGBColor = BLACK, italic: bool = False):
    run.bold = bold
    run.italic = italic
    run.font.size = size
    run.font.name = FONT
    run.font.color.rgb = color
    # python-docx only sets w:ascii; Cyrillic needs the complex-script and
    # east-asian hints too or Word substitutes a different face.
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attribute), FONT)
    return run


def _write(paragraph, text: str, *, bold: bool = False, size=SIZE_BODY,
           color: RGBColor = BLACK, italic: bool = False):
    return _style_run(
        paragraph.add_run(text), bold=bold, size=size, color=color, italic=italic
    )


def _tidy(paragraph, *, alignment=None):
    """Kill the default template's paragraph padding inside cells."""
    if alignment is not None:
        paragraph.alignment = alignment
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    return paragraph


def _cell_paragraph(cell, index: int = 0):
    """Reuse the cell's own first paragraph, then add more as needed."""
    if index < len(cell.paragraphs):
        return cell.paragraphs[index]
    return cell.add_paragraph()


def _shade(cell, fill: str) -> None:
    """``<w:shd w:fill="F2F2F2"/>`` — python-docx has no API for this."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def _remove_borders(table) -> None:
    """Set all six borders to ``none``, exactly as the template does.

    Done in XML rather than by choosing a borderless style, so the result does
    not depend on which table style python-docx's default template supplies.
    """
    tbl_pr = table._tbl.tblPr
    for existing in tbl_pr.findall(qn("w:tblBorders")):
        tbl_pr.remove(existing)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "none")
        element.set(qn("w:sz"), "0")
        element.set(qn("w:space"), "0")
        element.set(qn("w:color"), "auto")
        borders.append(element)
    tbl_pr.append(borders)


def _set_row(cells, *, shaded: bool) -> None:
    for cell, width in zip(cells, COLUMN_WIDTHS_TWIPS):
        cell.width = Twips(width)
        cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        if shaded:
            _shade(cell, HEADER_FILL)


# ------------------------------------------------------------------ the report


def build_document(
    rows: Sequence[dict[str, Any]],
    *,
    report_date: dt.date,
    department_order,
) -> io.BytesIO:
    """Build the report.

    ``rows`` are absence records joined to employee data, as returned by
    ``Database.absences_on``. ``department_order`` is a callable mapping a
    department name to its index in the DEPARTMENT env var, so the table
    follows the organisation's own ordering rather than the alphabet.
    """
    document = Document()

    section = document.sections[0]
    section.page_width = Emu(PAGE_WIDTH)
    section.page_height = Emu(PAGE_HEIGHT)
    section.left_margin = Emu(MARGIN_LEFT)
    section.right_margin = Emu(MARGIN_RIGHT)
    section.top_margin = Emu(MARGIN_TOP)
    section.bottom_margin = Emu(MARGIN_BOTTOM)

    normal = document.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = SIZE_BODY
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.element.rPr.rFonts.set(qn("w:cs"), FONT)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.1

    # --- headings -----------------------------------------------------------
    title = _tidy(document.add_paragraph(), alignment=WD_ALIGN_PARAGRAPH.CENTER)
    title.paragraph_format.space_after = Pt(4)
    _write(title, TITLE_LINE_1, bold=True, size=SIZE_TITLE, color=NAVY)
    breaker = _write(title, "", bold=True, size=SIZE_TITLE, color=NAVY)
    breaker.add_break()
    _write(title, TITLE_LINE_2, bold=True, size=SIZE_TITLE, color=NAVY)

    subtitle = _tidy(document.add_paragraph(), alignment=WD_ALIGN_PARAGRAPH.CENTER)
    subtitle.paragraph_format.space_after = Pt(4)
    _write(subtitle, TITLE_LINE_3, bold=True, size=SIZE_TITLE, color=RED)

    # The whole line is italic in the template, brackets and "й" included.
    date_line = _tidy(document.add_paragraph(), alignment=WD_ALIGN_PARAGRAPH.RIGHT)
    date_line.paragraph_format.space_after = Pt(6)
    _write(date_line, f"({fmt_heading_date(report_date)} й)", italic=True)

    spacer = _tidy(document.add_paragraph(), alignment=WD_ALIGN_PARAGRAPH.RIGHT)
    spacer.paragraph_format.space_after = Pt(6)

    # --- table --------------------------------------------------------------
    table = document.add_table(rows=1, cols=len(HEADERS))
    table.autofit = False
    table.width = Twips(TABLE_WIDTH_TWIPS)
    _remove_borders(table)
    for column, width in zip(table.columns, COLUMN_WIDTHS_TWIPS):
        column.width = Twips(width)

    header_cells = table.rows[0].cells
    _set_row(header_cells, shaded=True)
    for cell, header in zip(header_cells, HEADERS):
        paragraph = _tidy(_cell_paragraph(cell), alignment=WD_ALIGN_PARAGRAPH.CENTER)
        _write(paragraph, header, bold=True, size=SIZE_TITLE, color=NAVY)

    ordered = sorted(
        rows,
        key=lambda r: (department_order(r["department"]), r["full_name"] or ""),
    )

    for number, record in enumerate(ordered, start=1):
        surname, rest = split_name(record.get("full_name") or "")
        row = table.add_row()
        row.height = Twips(DATA_ROW_HEIGHT_TWIPS)
        cells = row.cells
        _set_row(cells, shaded=False)

        # Т/Р
        paragraph = _tidy(_cell_paragraph(cells[0]), alignment=WD_ALIGN_PARAGRAPH.CENTER)
        _write(paragraph, f"{number}.", bold=True)

        # Ф.И.Ш. — SURNAME navy bold in caps, rest of the name below in black
        paragraph = _tidy(_cell_paragraph(cells[1]))
        _write(
            paragraph,
            transliterate(surname).upper() + " ",
            bold=True,
            color=NAVY,
        )
        if rest:
            breaker = _write(paragraph, "", bold=True, color=NAVY)
            breaker.add_break()
            _write(paragraph, transliterate(rest), bold=False)

        # Лавозими
        paragraph = _tidy(_cell_paragraph(cells[2]), alignment=WD_ALIGN_PARAGRAPH.CENTER)
        _write(paragraph, clean_department(record.get("department")))

        # Кетган куни — date bold, reason in brackets underneath
        paragraph = _tidy(_cell_paragraph(cells[3]), alignment=WD_ALIGN_PARAGRAPH.CENTER)
        _write(paragraph, fmt_day_month(record["start_date"]), bold=True)
        reason = texts.KIND_LABELS.get(record["kind"], record["kind"])
        paragraph = _tidy(
            _cell_paragraph(cells[3], 1), alignment=WD_ALIGN_PARAGRAPH.CENTER
        )
        _write(paragraph, f"({transliterate(reason)})")

        # Ишга чиқиш куни
        paragraph = _tidy(_cell_paragraph(cells[4]), alignment=WD_ALIGN_PARAGRAPH.CENTER)
        _write(paragraph, fmt_day_month(record["return_date"]), bold=True)

    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer


def filename(report_date: dt.date) -> str:
    return f"malumot_{report_date.strftime('%d.%m.%Y')}.docx"


def plain_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    """The same data as Telegram-friendly text, for /absent.

    Deliberately keeps numeric dates and shows the destination and comment —
    it is a working list, not the official document.
    """
    out: list[str] = []
    for number, record in enumerate(rows, start=1):
        tail = f" — 📍 {record['destination']}" if record.get("destination") else ""
        note = f"\n   <i>{record['comment']}</i>" if record.get("comment") else ""
        out.append(
            f"{number}. <b>{record['full_name']}</b>\n"
            f"   {record['department']}\n"
            f"   {texts.kind_label(record['kind'])} · "
            f"{texts.fmt_date(record['start_date'])} → "
            f"{texts.fmt_date(record['return_date'])}{tail}{note}"
        )
    return out
