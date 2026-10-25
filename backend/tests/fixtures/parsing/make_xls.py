"""Generuje fixtures/parsing/sample.xls (T6). Uruchamiać ręcznie, nie przez pytest:

cd backend && uv run --no-project --with xlwt python tests/fixtures/parsing/make_xls.py
"""

import datetime
from pathlib import Path

import xlwt

OUT = Path(__file__).with_name("sample.xls")


def main() -> None:
    wb = xlwt.Workbook()
    sheet = wb.add_sheet("Dane")
    date_style = xlwt.easyxf(num_format_str="YYYY-MM-DD")
    sheet.write(0, 0, "Nazwa")
    sheet.write(0, 1, "Kwota")
    sheet.write(0, 2, "Data")
    sheet.write(1, 0, "Ala")
    sheet.write(1, 1, 3.5)
    sheet.write(1, 2, datetime.datetime(2024, 1, 2), date_style)
    sheet.write(2, 0, "Kot")
    sheet.write(2, 1, 4.0)
    sheet.write(2, 2, datetime.datetime(2024, 2, 3), date_style)
    hidden = wb.add_sheet("Ukryty")
    hidden.write(0, 0, "sekret")
    hidden.visibility = 1  # ukryty arkusz — konwerter ma go pominąć z warningiem
    wb.save(str(OUT))
    print(f"written {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
