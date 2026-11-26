"""Tests de l'import des listes de sites."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.io.importer import ImportFileError, read_url_file


def write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path


def test_txt_one_url_per_line(tmp_path: Path) -> None:
    path = write(tmp_path / "sites.txt", "site1.fr\n\n  https://site2.com  \r\nsite3.org\n")
    assert read_url_file(path) == ["site1.fr", "https://site2.com", "site3.org"]


def test_txt_with_bom_and_windows_encoding(tmp_path: Path) -> None:
    assert read_url_file(write(tmp_path / "a.txt", "﻿site.fr\n", "utf-8")) == ["site.fr"]
    path = write(tmp_path / "b.txt", "# communes de l'agglomération\nsite.fr\n", "cp1252")
    assert read_url_file(path) == ["# communes de l'agglomération", "site.fr"]


@pytest.mark.parametrize(
    "content",
    [
        "nom;url;ville\nMairie A;https://a.fr;Metz\nMairie B;b.fr;Nancy\n",
        "nom,URL,ville\nMairie A,https://a.fr,Metz\nMairie B,b.fr,Nancy\n",
        "nom\tSite web\nMairie A\thttps://a.fr\nMairie B\tb.fr\n",
    ],
)
def test_csv_url_column_is_detected(tmp_path: Path, content: str) -> None:
    assert read_url_file(write(tmp_path / "sites.csv", content)) == ["https://a.fr", "b.fr"]


def test_csv_without_header_uses_first_column(tmp_path: Path) -> None:
    path = write(tmp_path / "sites.csv", "a.fr;Mairie A\nb.fr;Mairie B\n")
    assert read_url_file(path) == ["a.fr", "b.fr"]


def test_csv_single_column(tmp_path: Path) -> None:
    path = write(tmp_path / "sites.csv", "url\na.fr\nhttps://b.fr/contact\n")
    assert read_url_file(path) == ["a.fr", "https://b.fr/contact"]


def test_csv_excel_french_export(tmp_path: Path) -> None:
    content = "﻿Commune;URL\r\nMoyeuvre-Grande;moyeuvre.fr\r\n;\r\nRombas;rombas.fr\r\n"
    assert read_url_file(write(tmp_path / "s.csv", content, "utf-8")) == [
        "moyeuvre.fr",
        "rombas.fr",
    ]


def test_empty_file(tmp_path: Path) -> None:
    assert read_url_file(write(tmp_path / "vide.csv", "")) == []


def test_unsupported_extension(tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match=r"Format non pris en charge \(\.xlsx\)"):
        read_url_file(write(tmp_path / "sites.xlsx", "x"))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ImportFileError, match="Impossible de lire le fichier"):
        read_url_file(tmp_path / "absent.txt")
