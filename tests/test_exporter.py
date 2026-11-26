"""Tests de l'export CSV / XLSX."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from app.io.exporter import default_export_name, export_csv, export_xlsx, neutralize_formula
from app.models import EmailResult

FOUND = datetime(2026, 11, 26, 14, 32, 5)
RESULTS = [
    EmailResult("contact@mairie.fr", "mairie.fr", "https://mairie.fr/contact", FOUND, "mailto"),
    EmailResult("élu@mairie.fr", "mairie.fr", "https://mairie.fr/équipe", FOUND, "obfuscated"),
    EmailResult("-x@site.fr", "site.fr", "https://site.fr", FOUND, "regex"),
]


def test_default_export_name() -> None:
    assert default_export_name("csv", datetime(2026, 3, 7, 9, 5)) == "emails_2026-03-07_0905.csv"


def test_neutralize_formula() -> None:
    assert neutralize_formula("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert neutralize_formula("+33@x.fr") == "'+33@x.fr"
    assert neutralize_formula("contact@x.fr") == "contact@x.fr"


def test_csv_is_excel_french_compatible(tmp_path: Path) -> None:
    path = tmp_path / "exports" / "emails.csv"
    assert export_csv(RESULTS, path) == 3
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM UTF-8 : accents corrects dans Excel
    assert b"\r\n" in raw
    lines = raw.decode("utf-8-sig").splitlines()
    assert lines == [
        "email;site;page_source;methode;date_trouvee",
        "contact@mairie.fr;mairie.fr;https://mairie.fr/contact;mailto;26/11/2026 14:32:05",
        "élu@mairie.fr;mairie.fr;https://mairie.fr/équipe;masqué;26/11/2026 14:32:05",
        "'-x@site.fr;site.fr;https://site.fr;texte;26/11/2026 14:32:05",
    ]


def test_csv_values_with_separator_are_quoted(tmp_path: Path) -> None:
    result = EmailResult("a@b.fr", "b.fr", "https://b.fr/p?a=1;b=2", FOUND, "regex")
    path = tmp_path / "e.csv"
    export_csv([result], path)
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file, delimiter=";"))
    assert rows[1][2] == "https://b.fr/p?a=1;b=2"


def test_csv_empty(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    assert export_csv([], path) == 0
    assert path.read_text("utf-8-sig").splitlines() == [
        "email;site;page_source;methode;date_trouvee"
    ]


def test_xlsx_content_and_formatting(tmp_path: Path) -> None:
    path = tmp_path / "emails.xlsx"
    assert export_xlsx(RESULTS, path) == 3
    sheet = load_workbook(path).active
    assert sheet is not None
    assert sheet.title == "E-mails"
    assert [c.value for c in sheet[1]] == [
        "email",
        "site",
        "page_source",
        "methode",
        "date_trouvee",
    ]
    assert all(c.font.bold for c in sheet[1])
    assert [c.value for c in sheet[3]] == [
        "élu@mairie.fr",
        "mairie.fr",
        "https://mairie.fr/équipe",
        "masqué",
        FOUND,
    ]
    assert sheet["E2"].number_format == "dd/mm/yyyy hh:mm:ss"
    assert sheet["C2"].hyperlink is not None
    assert sheet["C2"].hyperlink.target == "https://mairie.fr/contact"
    assert sheet.auto_filter.ref == "A1:E4"
    assert sheet.freeze_panes == "A2"
    assert sheet.column_dimensions["A"].width == len("contact@mairie.fr") + 2
    assert sheet["A4"].value == "'-x@site.fr"


def test_xlsx_formula_is_not_executed(tmp_path: Path) -> None:
    result = EmailResult("a@b.fr", "=1+1", "https://b.fr", FOUND, "regex")
    path = tmp_path / "e.xlsx"
    export_xlsx([result], path)
    sheet = load_workbook(path).active
    assert sheet is not None
    assert sheet["B2"].value == "'=1+1"
    assert sheet["B2"].data_type == "s"
