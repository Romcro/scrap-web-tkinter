"""Chargement, validation et sauvegarde des paramètres (config/settings.json)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from app.models import Settings

logger = logging.getLogger(__name__)

# Bornes des paramètres numériques : (minimum, maximum).
LIMITS: dict[str, tuple[float, float]] = {
    "max_depth": (0, 10),
    "max_pages_per_site": (1, 1000),
    "delay_seconds": (0.5, 60),
    "timeout_seconds": (1, 120),
    "max_workers": (1, 16),
}

# Début de phrase de chaque message d'erreur (accordé en genre).
_LIMIT_MESSAGES: dict[str, str] = {
    "max_depth": "La profondeur doit être comprise",
    "max_pages_per_site": "Le nombre de pages par site doit être compris",
    "delay_seconds": "Le délai entre requêtes doit être compris",
    "timeout_seconds": "Le délai maximal d'une requête doit être compris",
    "max_workers": "Le nombre de sites traités en parallèle doit être compris",
}

MAX_USER_AGENT_LENGTH = 200

# Présent dans le User-Agent par défaut : signale que l'utilisateur n'a pas mis son contact.
PLACEHOLDER_CONTACT = "votre-domaine"

_INVALID = object()


def _format_number(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def field_error(name: str, value: Any) -> str | None:
    """Message d'erreur si `value` n'est pas acceptable pour le paramètre `name`, sinon None."""
    if name in LIMITS:
        low, high = LIMITS[name]
        if not low <= value <= high:
            return f"{_LIMIT_MESSAGES[name]} entre {_format_number(low)} et {_format_number(high)}."
    elif name == "user_agent":
        text = value.strip()
        if not text:
            return "Le User-Agent ne peut pas être vide."
        if len(text) > MAX_USER_AGENT_LENGTH:
            return f"Le User-Agent ne doit pas dépasser {MAX_USER_AGENT_LENGTH} caractères."
        if not (text.isascii() and text.isprintable()):
            return "Le User-Agent ne doit contenir que des caractères simples (sans accents)."
    return None


def validate_settings(settings: Settings) -> list[str]:
    """Liste des erreurs de validation (vide si tout est correct)."""
    errors = [field_error(f.name, getattr(settings, f.name)) for f in fields(Settings)]
    return [error for error in errors if error is not None]


def _coerce(value: Any, default: Any) -> Any:
    """Convertit une valeur lue dans le JSON vers le type du paramètre, ou _INVALID."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else _INVALID
    if isinstance(value, bool):  # True/False ne sont pas des nombres acceptables
        return _INVALID
    if isinstance(default, int):
        return value if isinstance(value, int) else _INVALID
    if isinstance(default, float):
        return float(value) if isinstance(value, int | float) else _INVALID
    if isinstance(default, str):
        return value if isinstance(value, str) else _INVALID
    return _INVALID


def load_settings(path: Path) -> Settings:
    """Charge les paramètres ; valeur par défaut pour tout paramètre absent ou invalide."""
    defaults = Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.info("%s absent : paramètres par défaut", path)
        return defaults
    except (OSError, ValueError) as exc:
        logger.warning("%s illisible (%s) : paramètres par défaut", path, exc)
        return defaults
    if not isinstance(raw, dict):
        logger.warning("%s ne contient pas un objet JSON : paramètres par défaut", path)
        return defaults

    values: dict[str, Any] = {}
    for f in fields(Settings):
        if f.name not in raw:
            continue
        value = _coerce(raw[f.name], getattr(defaults, f.name))
        if value is _INVALID or field_error(f.name, value) is not None:
            logger.warning("Paramètre %s invalide (%r) : valeur par défaut", f.name, raw[f.name])
            continue
        values[f.name] = value
    return Settings(**values)


def save_settings(settings: Settings, path: Path) -> None:
    """Enregistre les paramètres (écriture atomique : pas de fichier à moitié écrit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
