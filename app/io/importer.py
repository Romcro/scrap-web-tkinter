"""Lecture des listes de sites (.txt : une URL par ligne ; .csv : colonne « url »)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".txt", ".csv"})

# En-têtes reconnus pour la colonne des URL dans un CSV (comparés en minuscules).
URL_COLUMN_NAMES: tuple[str, ...] = ("url", "site", "site web", "site internet", "website", "lien")

# Encodages essayés dans l'ordre (le dernier accepte tous les octets).
_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1252", "latin-1")
_CSV_DELIMITERS = ";,\t"
_SNIFF_SIZE = 4096


class ImportFileError(Exception):
    """Fichier impossible à importer ; le message est destiné à l'utilisateur."""


def read_url_file(path: Path) -> list[str]:
    """Retourne les lignes non vides du fichier (URL brutes, non normalisées)."""
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ImportFileError(
            f"Format non pris en charge ({extension or 'sans extension'}) : "
            "utilisez un fichier .txt ou .csv."
        )
    text = _read_text(path)
    lines = parse_csv(text) if extension == ".csv" else text.splitlines()
    return [line.strip() for line in lines if line.strip()]


def parse_csv(text: str) -> list[str]:
    """Valeurs de la colonne d'URL (repérée par son en-tête), sinon de la première colonne."""
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(
            text[:_SNIFF_SIZE], delimiters=_CSV_DELIMITERS
        )
    except csv.Error:  # une seule colonne : pas de séparateur à détecter
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in row)]
    if not rows:
        return []
    header = [cell.strip().lower() for cell in rows[0]]
    for name in URL_COLUMN_NAMES:
        if name in header:
            column = header.index(name)
            return [row[column] for row in rows[1:] if len(row) > column]
    return [row[0] for row in rows]


def _read_text(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ImportFileError(f"Impossible de lire le fichier : {exc.strerror or exc}") from exc
    for encoding in _ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ImportFileError("Encodage du fichier non reconnu.")  # pragma: no cover (latin-1)
