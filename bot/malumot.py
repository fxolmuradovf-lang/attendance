"""The MAʼLUMOT Word document.

Reproduces A.docx exactly: A4 portrait with the same margins, Times New Roman
throughout, 14pt bold headings, a five-column bordered table, and per-cell
formatting matched to the template (bold surname above the rest of the name,
bold dates, the reason in brackets under the departure date).

Placeholder → source mapping, as specified in A.docx:

    DATEQ            the date the report is for, DD.MM.YYYY
    SURNAMEQ         first word of NAME, bold, on its own line
    RestofthenameQ   everything after that first space, not bold
    DEPARTMENTQ      the DEPARTMENT entry (which carries the lavozim)
    ABSENCEDAYQ      absence start date, bold
    REASONQ          the absence reason, in brackets
    ARRIVALDAYQ      return-to-work date, bold

Everything drawn from DEPARTMENT/NAME is transliterated Latin → Cyrillic so the
table matches the Cyrillic headings.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any, Iterable, Sequence

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Emu, Pt

from . import texts
from .translit import split_name, transliterate

# --- measured from A.docx, in EMU -------------------------------------------
PAGE_WIDTH = 7560310
PAGE_HEIGHT = 10692130
MARGIN_LEFT = 900430
MARGIN_RIGHT = 359410
MARGIN_TOP = 360045
MARGIN_BOTTOM = 360045

COLUMN_WIDTHS = (414020, 1540510, 1732915, 1316355, 1297305)
DATA_ROW_HEIGHT = 730250

FONT = "Times New Roman"
SIZE_TITLE = Pt(14)
SIZE_BODY = Pt(12)

TITLE_LINE_1 = "ИШ ЖОЙИДА БЎЛМАГАН МАРКАЗИЙ БАНК"
TITLE_LINE_2 = "РАҲБАР ХОДИМЛАРИ ТЎҒРИСИДА"
TITLE_LINE_3 = "МАЪЛУМОТ"
HEADERS = ("Т/Р", "Ф.И.Ш.", "Лавозими", "Кетган куни", "Ишга чиқиш куни")


def _style_run(run, *, bold: bool, size) -> None:
    run.bold = bold
    run.font.size = size
    run.font.name = FONT
    # python-docx only sets w:ascii; Cyrillic needs the complex-script and
    # east-asian hints too or Word substitutes a different face.
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attribute), FONT)


def _write(paragraph, text: str, *, bold: bool = False, size=SIZE_BODY):
    run = paragraph.add_run(text)
    _style_run(run, bold=bold, size=size)
    return run


def _cell_paragraph(cell, index: int = 0):
    """Reuse the cell's own first paragraph, then add more as needed."""
    if index < len(cell.paragraphs):
        return cell.paragraphs[index]
    return cell.add_paragraph()


def _set_cell_width(cell, width_emu: int) -> None:
    cell.width = Emu(width_emu)


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

    # --- headings -----------------------------------------------------------
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _write(title, TITLE_LINE_1, bold=True, size=SIZE_TITLE)
    run = title.add_run()
    _style_run(run, bold=True, size=SIZE_TITLE)
    run.add_break()
    _write(title, TITLE_LINE_2, bold=True, size=SIZE_TITLE)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _write(subtitle, TITLE_LINE_3, bold=True, size=SIZE_TITLE)

    date_line = document.add_paragraph()
    date_line.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _write(date_line, f"({report_date.strftime('%d.%m.%Y')} й)")

    document.add_paragraph()

    # --- table --------------------------------------------------------------
    table = document.add_table(rows=1, cols=len(HEADERS))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for cell, header, width in zip(table.rows[0].cells, HEADERS, COLUMN_WIDTHS):
        _set_cell_width(cell, width)
        paragraph = _cell_paragraph(cell)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, header, bold=True, size=SIZE_TITLE)

    ordered = sorted(
        rows,
        key=lambda r: (department_order(r["department"]), r["full_name"] or ""),
    )

    for number, record in enumerate(ordered, start=1):
        surname, rest = split_name(record.get("full_name") or "")
        cells = table.add_row().cells
        table.rows[-1].height = Emu(DATA_ROW_HEIGHT)
        for cell, width in zip(cells, COLUMN_WIDTHS):
            _set_cell_width(cell, width)

        # Т/Р
        paragraph = _cell_paragraph(cells[0])
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, f"{number}.", bold=True)

        # Ф.И.Ш. — surname bold, rest of the name on the next line, not bold
        paragraph = _cell_paragraph(cells[1])
        _write(paragraph, transliterate(surname) + " ", bold=True)
        if rest:
            run = paragraph.add_run()
            _style_run(run, bold=True, size=SIZE_BODY)
            run.add_break()
            _write(paragraph, transliterate(rest), bold=False)

        # Лавозими
        paragraph = _cell_paragraph(cells[2])
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, transliterate(record.get("department") or ""))

        # Кетган куни — date bold, reason in brackets underneath
        paragraph = _cell_paragraph(cells[3])
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, record["start_date"].strftime("%d.%m.%Y"), bold=True)
        reason = texts.KIND_LABELS.get(record["kind"], record["kind"])
        paragraph = _cell_paragraph(cells[3], 1)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, f"({transliterate(reason)})")

        # Ишга чиқиш куни
        paragraph = _cell_paragraph(cells[4])
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write(paragraph, record["return_date"].strftime("%d.%m.%Y"), bold=True)

    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer


def filename(report_date: dt.date) -> str:
    return f"malumot_{report_date.strftime('%d.%m.%Y')}.docx"


def plain_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    """The same data as Telegram-friendly text, for /absent."""
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
