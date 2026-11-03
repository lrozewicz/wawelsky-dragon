"""Konwertery arkuszy: xlsx/xlsm (openpyxl), xls (xlrd), csv/tsv (kontrakt C8)."""

from __future__ import annotations

import csv
import datetime as dt
import io
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from xlrd.xldate import xldate_as_datetime

from app.parsing.converters.common import check_zip, finish, read_bytes
from app.parsing.converters.pdf_layout import clean_cell, is_value, join_label
from app.parsing.encoding import decode_bytes
from app.parsing.errors import corrupted_file, encrypted_file, limit_exceeded
from app.parsing.html import esc, section_html, table_html
from app.parsing.types import ConvertedDocument, ConvertOptions

_DIAGNOSIS = "spreadsheet has no data"
_HIDDEN_WARNING = "sheet '{name}' is hidden, skipped"
_NAVIGATION = ("powrót do", "return to", "wróć do", "back to")
_MIN_VALUES = 2  # tyle liczb w wierszu odróżnia dane od numeracji i opisów


class _SemicolonDialect(csv.excel):
    """Fallback dialektu CSV: średnik (pierwsza linia ma więcej ';' niż ',')."""

    delimiter = ";"


class _SheetRows:
    """Wiersze jednego arkusza: pomijanie pustych wierszy, obcinanie pustych
    kolumn na końcu (po całym arkuszu) i wspólny limit wierszy dokumentu (C8)."""

    def __init__(self, opts: ConvertOptions, used: int = 0) -> None:
        self._opts = opts
        self.used = used  # wiersze policzone dotąd w całym dokumencie
        self.rows: list[list[str]] = []

    def feed(self, raw_rows: Iterable[Sequence[object]]) -> None:
        """Dodaje wiersze; limit sprawdzany natychmiast po przekroczeniu."""
        for raw in raw_rows:
            cells = [cell_str(value) for value in raw]
            if not any(cells):
                continue  # pusty wiersz
            self.used += 1
            if self.used > self._opts.max_sheet_rows:
                raise limit_exceeded("sheet rows", self.used, self._opts.max_sheet_rows)
            self.rows.append(cells)
        self._trim_trailing_columns()

    def _trim_trailing_columns(self) -> None:
        """Obcina końcowe kolumny puste w każdym zachowanym wierszu."""
        width = 0
        for row in self.rows:
            for index in range(len(row) - 1, -1, -1):
                if row[index]:
                    width = max(width, index + 1)
                    break
        self.rows = [row[:width] for row in self.rows]


def _first_data_row(rows: Sequence[Sequence[str]]) -> int | None:
    """Pierwszy wiersz danych: opis lub rok po lewej i co najmniej dwie liczby po nim.

    Numeracja kolumn czy wiek (``"", "", "0", "15", "30"``) nie ma opisu, więc to jeszcze nagłówek.
    """
    for index, row in enumerate(rows):
        cells = [cell for cell in row if cell.strip()]
        labelled = len(cells) > _MIN_VALUES and not is_value(cells[0])
        if labelled and sum(is_value(cell) for cell in cells[1:]) >= _MIN_VALUES:
            return index
    return None


def _table_start(rows: Sequence[Sequence[str]]) -> int:
    """Początek tabeli: tytuł i nawigacja nad nią mają co najwyżej jedną niepustą komórkę."""
    for index, row in enumerate(rows):
        if sum(1 for cell in row if cell.strip()) > 1:
            return index
    return 0


def _flat_header(rows: Sequence[Sequence[str]], width: int) -> list[str]:
    """Nagłówek wielopoziomowy jako jeden wiersz; pusta komórka należy do grupy z lewej.

    Ostatni poziom niczego nie dziedziczy, bo jego puste komórki to zwykle brak podpisu.
    """
    grid = [list(row) + [""] * (width - len(row)) for row in rows]
    for row in grid[:-1]:
        for column in range(1, width):
            if not row[column].strip():
                row[column] = row[column - 1]
    return [join_label([row[column] for row in grid]) for column in range(width)]


def _fill_labels(rows: Sequence[list[str]]) -> list[list[str]]:
    """Scalone opisy po lewej (``OGÓŁEM`` nad kilkoma latami) powielone w wierszach wartości."""
    if not rows:
        return []
    labels = 0
    for cell in rows[0]:
        if is_value(cell):
            break
        labels += 1
    out: list[list[str]] = []
    last = [""] * labels
    for raw in rows:
        row = [clean_cell(cell) for cell in raw]
        has_values = any(is_value(cell) for cell in row[labels:])
        for column in range(labels):
            if row[column]:
                last[column] = row[column]
            elif has_values:
                row[column] = last[column]
        out.append(row)
    return out


def sheet_html(rows: Sequence[list[str]]) -> str:
    """Arkusz: tytuł jako nagłówek (trafia do każdego chunku), nagłówek spłaszczony, dane."""
    first = _first_data_row(rows)
    if first is None:
        return table_html(rows)
    start = min(_table_start(rows), first)
    title = " ".join(
        clean_cell(cell)
        for row in rows[:start]
        for cell in row
        if cell.strip() and not cell.strip().lower().startswith(_NAVIGATION)
    )
    width = max(len(row) for row in rows)
    header = _flat_header(rows[start:first], width) if first > start else None
    body = _fill_labels(rows[first:])
    table = [header, *body] if header else body
    heading = f"<h2>{esc(title)}</h2>" if title else ""
    return heading + table_html(table, header_rows=1 if header else 0)


def cell_str(value: object) -> str:  # noqa: PLR0911 — jeden return na typ komórki
    """Komórka arkusza → tekst (C8): bool TRUE/FALSE, daty ISO, całkowity float bez .0."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time() else value.isoformat()
    if isinstance(value, (dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return _short_float(value)
    return str(value)


def _short_float(value: float) -> str:
    """Najkrótszy zapis w granicy szumu binarnego: 805.2775094000001 → 805.2775094.

    Prawdziwe wartości z 15 cyframi (100.375234521576) zostają bez zmian.
    """
    for digits in range(1, 16):
        text = format(value, f".{digits}g")
        if abs(float(text) - value) <= abs(value) * 1e-14:
            return text
    return repr(value)


def _finish_sheets(sections: list[str], warnings: list[str]) -> ConvertedDocument:
    """Skleja sekcje arkuszy i zamyka dokument wspólną diagnozą (C8)."""
    return finish("".join(sections), diagnosis=_DIAGNOSIS, warnings=warnings)


def convert_xlsx(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """XLSX i XLSM (ta sama funkcja) → sekcje <section data-sheet> z tabelami (C8)."""
    fmt = "xlsm" if path.suffix.lower() == ".xlsm" else "xlsx"
    check_zip(path, fmt, opts)
    sections: list[str] = []
    warnings: list[str] = []
    used = 0
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for name in workbook.sheetnames:
            sheet = workbook[name]
            if sheet.sheet_state != "visible":
                warnings.append(_HIDDEN_WARNING.format(name=name))
                continue
            rows = _SheetRows(opts, used)
            rows.feed(sheet.iter_rows(values_only=True))
            used = rows.used
            if rows.rows:  # pusty arkusz pominięty
                sections.append(section_html("sheet", name, sheet_html(rows.rows)))
    finally:
        workbook.close()
    return _finish_sheets(sections, warnings)


def convert_xls(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """XLS (xlrd) → sekcje <section data-sheet>; daty przez xldate_as_datetime (C8)."""
    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
    except xlrd.XLRDError as exc:
        if "encrypted" in str(exc).lower():
            raise encrypted_file("xls") from None
        raise corrupted_file("xls", str(exc)) from None
    sections: list[str] = []
    warnings: list[str] = []
    used = 0
    try:
        for index in range(book.nsheets):
            sheet = book.sheet_by_index(index)
            if sheet.visibility != 0:
                warnings.append(_HIDDEN_WARNING.format(name=sheet.name))
                continue
            rows = _SheetRows(opts, used)
            rows.feed(_xls_cells(sheet, book.datemode))
            used = rows.used
            if rows.rows:  # pusty arkusz pominięty
                sections.append(section_html("sheet", sheet.name, sheet_html(rows.rows)))
    finally:
        book.release_resources()
    return _finish_sheets(sections, warnings)


def _xls_cells(sheet: xlrd.sheet.Sheet, datemode: int) -> Iterator[list[object]]:
    """Wiersze arkusza xlrd; komórki datowe zamieniane na datetime (C8)."""
    for row_index in range(sheet.nrows):
        yield [
            (
                xldate_as_datetime(cell.value, datemode)
                if cell.ctype == xlrd.XL_CELL_DATE
                else cell.value
            )
            for cell in sheet.row(row_index)
        ]


def convert_csv(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """CSV → jedna tabela HTML; separator sniffowany, fallback ';' lub ',' (C8)."""
    text, encoding = decode_bytes(read_bytes(path), fmt="csv")
    return _delimited_document(text, _sniff_dialect(text), encoding, opts)


def convert_tsv(path: Path, opts: ConvertOptions) -> ConvertedDocument:
    """TSV → jedna tabela HTML; separator tabulator (C8)."""
    text, encoding = decode_bytes(read_bytes(path), fmt="tsv")
    return _delimited_document(text, csv.excel_tab, encoding, opts)


def _sniff_dialect(text: str) -> Any:
    """Dialekt CSV ze Sniffera; po csv.Error fallback na ';' albo ',' (C8)."""
    try:
        return csv.Sniffer().sniff(text[:65536], delimiters=",;\t|")
    except csv.Error:
        first_line = text.split("\n", 1)[0]
        if first_line.count(";") > first_line.count(","):
            return _SemicolonDialect
        return csv.excel


def _delimited_document(
    text: str, dialect: Any, encoding: str, opts: ConvertOptions
) -> ConvertedDocument:
    """Wspólne domknięcie csv/tsv: wiersze przez csv.reader, encoding w metadanych."""
    rows = _SheetRows(opts)
    rows.feed(csv.reader(io.StringIO(text, newline=""), dialect))
    return finish(
        table_html(rows.rows),
        diagnosis=_DIAGNOSIS,
        metadata={"encoding": encoding},
    )
