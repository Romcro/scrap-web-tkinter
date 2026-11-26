"""Tests du chargement, de la validation et de la sauvegarde des paramètres."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from app.config import load_settings, save_settings, validate_settings
from app.models import Settings


def write(path: Path, content: object) -> Path:
    path.write_text(content if isinstance(content, str) else json.dumps(content), "utf-8")
    return path


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "absent.json") == Settings()


@pytest.mark.parametrize("content", ["{pas du json", "[1, 2]", '"texte"', ""])
def test_unreadable_file_gives_defaults(tmp_path: Path, content: str) -> None:
    assert load_settings(write(tmp_path / "s.json", content)) == Settings()


def test_valid_values_are_loaded(tmp_path: Path) -> None:
    values = {
        "max_depth": 3,
        "max_pages_per_site": 120,
        "delay_seconds": 2,  # un entier est accepté pour un paramètre décimal
        "timeout_seconds": 20,
        "max_workers": 8,
        "respect_robots": False,
        "include_subdomains": True,
        "user_agent": "MonOutil/1.0 (+moi@exemple-reel.fr)",
        "debug_logging": True,
    }
    settings = load_settings(write(tmp_path / "s.json", values))
    assert asdict(settings) == {**values, "delay_seconds": 2.0}
    assert isinstance(settings.delay_seconds, float)


def test_invalid_values_fall_back_one_by_one(tmp_path: Path) -> None:
    settings = load_settings(
        write(
            tmp_path / "s.json",
            {
                "max_depth": 99,  # hors limites
                "max_pages_per_site": "50",  # mauvais type
                "delay_seconds": 0.1,  # trop court
                "timeout_seconds": True,  # un booléen n'est pas un nombre
                "max_workers": 6,  # valide
                "respect_robots": "oui",  # mauvais type
                "user_agent": "Outil é",  # accent interdit dans un en-tête HTTP
                "inconnu": 1,  # ignoré
            },
        )
    )
    defaults = Settings()
    assert settings == replace(defaults, max_workers=6)


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config" / "settings.json"
    settings = Settings(max_depth=4, delay_seconds=1.5, include_subdomains=True)
    save_settings(settings, path)
    assert load_settings(path) == settings
    assert not list(path.parent.glob("*.tmp"))
    assert json.loads(path.read_text("utf-8"))["max_depth"] == 4


def test_validate_settings_messages() -> None:
    assert validate_settings(Settings()) == []
    errors = validate_settings(
        Settings(max_depth=-1, delay_seconds=100, max_workers=0, user_agent="  ")
    )
    assert errors == [
        "La profondeur doit être comprise entre 0 et 10.",
        "Le délai entre requêtes doit être compris entre 0,5 et 60.",
        "Le nombre de sites traités en parallèle doit être compris entre 1 et 16.",
        "Le User-Agent ne peut pas être vide.",
    ]


def test_user_agent_rules() -> None:
    assert validate_settings(Settings(user_agent="x" * 201)) == [
        "Le User-Agent ne doit pas dépasser 200 caractères."
    ]
    assert validate_settings(Settings(user_agent="Outil (contact : élise@x.fr)")) == [
        "Le User-Agent ne doit contenir que des caractères simples (sans accents)."
    ]
