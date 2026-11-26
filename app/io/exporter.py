"""Export des résultats en CSV (compatible Excel FR) et en XLSX."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from app.models import METHOD_LABELS, EmailResult

EXPORT_COLUMNS: tuple[str, ...] = ("email", "site", "page_source", "methode", "date_trouvee")

CSV_DELIMITER = ";"
CSV_ENCODING = "utf-8-sig"  # le BOM permet à Excel de reconnaître l'UTF-8 (accents)
CSV_DATE_FORMAT = "%d/%m/%Y %H:%M:%S"
XLSX_DATE_FORMAT = "dd/mm/yyyy hh:mm:ss"
XLSX_SHEET_TITLE = "E-mails"
XLSX_MAX_COLUMN_WIDTH = 80
XLSX_DATE_WIDTH = 20

# Une cellule commençant par l'un de ces caractères serait interprétée comme une formule.
_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


def default_export_name(extension: str, now: datetime | None = None) -> str:
    """Nom proposé par défaut : emails_AAAA-MM-JJ_HHMM.<extension>."""
    return f"emails_{(now or datetime.now()):%Y-%m-%d_%H%M}.{extension}"


def neutralize_formula(text: str) -> str:
    """Empêche Excel d'exécuter une valeur comme une formule (injection CSV)."""
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def _text_row(result: EmailResult) -> list[str]:
    return [
        neutralize_formula(result.email),
        neutralize_formula(result.site),
        neutralize_formula(result.source_url),
        METHOD_LABELS.get(result.method, result.method),
    ]


def export_csv(results: Iterable[EmailResult], path: Path) -> int:
    """Écrit le fichier CSV et retourne le nombre de lignes exportées."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding=CSV_ENCODING, newline="") as file:
        writer = csv.writer(file, delimiter=CSV_DELIMITER, lineterminator="\r\n")
        writer.writerow(EXPORT_COLUMNS)
        for result in results:
            writer.writerow([*_text_row(result), f"{result.found_at:{CSV_DATE_FORMAT}}"])
            count += 1
    return count


def export_xlsx(results: Iterable[EmailResult], path: Path) -> int:
    """Écrit le classeur XLSX (en-tête en gras, filtre, largeurs ajustées) ; retourne le nombre
    de lignes exportées."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = XLSX_SHEET_TITLE
    sheet.append(list(EXPORT_COLUMNS))
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    widths = [len(name) for name in EXPORT_COLUMNS]
    count = 0
    for result in results:
        texts = _text_row(result)
        sheet.append([*texts, result.found_at])
        row = sheet.max_row
        sheet.cell(row=row, column=len(EXPORT_COLUMNS)).number_format = XLSX_DATE_FORMAT
        link = sheet.cell(row=row, column=EXPORT_COLUMNS.index("page_source") + 1)
        if result.source_url.startswith(("http://", "https://")):
            link.hyperlink = result.source_url
            link.style = "Hyperlink"
        for index, text in enumerate(texts):
            widths[index] = max(widths[index], len(text))
        count += 1
    widths[-1] = XLSX_DATE_WIDTH

    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = min(
            width + 2, XLSX_MAX_COLUMN_WIDTH
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    return count
