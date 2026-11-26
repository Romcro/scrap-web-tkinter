"""Modèles de données partagés entre le cœur métier et l'interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

EmailMethod = Literal["mailto", "structured", "regex", "obfuscated"]
EventType = Literal["progress", "email", "log", "error", "site_done", "done"]
LogLevel = Literal["INFO", "WARN", "ERROR"]

# Libellés des méthodes d'extraction affichés à l'utilisateur (tableau, exports).
METHOD_LABELS: dict[str, str] = {
    "mailto": "mailto",
    "structured": "JSON-LD",
    "regex": "texte",
    "obfuscated": "masqué",
}


@dataclass(frozen=True)
class EmailResult:
    """Adresse e-mail trouvée, rattachée à son site et à sa page source."""

    email: str
    site: str
    source_url: str
    found_at: datetime
    method: EmailMethod


@dataclass
class CrawlStats:
    """Compteurs de progression d'une session de scraping."""

    sites_total: int = 0
    sites_done: int = 0
    pages_visited: int = 0
    emails_found: int = 0
    errors: int = 0


@dataclass
class Settings:
    """Paramètres d'une session (chargés depuis config/settings.json)."""

    max_depth: int = 2
    max_pages_per_site: int = 50
    delay_seconds: float = 1.0
    timeout_seconds: int = 10
    max_workers: int = 4
    respect_robots: bool = True
    include_subdomains: bool = False  # blog.site.fr fait-il partie de site.fr ?
    user_agent: str = "EmailScraperDesktop/1.0 (+contact@votre-domaine.fr)"
    debug_logging: bool = False  # journal technique détaillé dans logs/app.log


@dataclass(frozen=True)
class LogMessage:
    """Ligne de journal destinée à l'utilisateur (payload des événements « log » et « error »)."""

    level: LogLevel
    message: str
    timestamp: datetime


@dataclass(frozen=True)
class SiteSummary:
    """Bilan d'un site (payload de l'événement « site_done »)."""

    site: str
    pages_visited: int
    emails_found: int
    errors: int
    completed: bool  # False si le traitement a été interrompu par l'utilisateur


@dataclass(frozen=True)
class RunSummary:
    """Bilan de la session (payload de l'événement « done »)."""

    stats: CrawlStats
    stopped: bool
    duration_seconds: float


@dataclass(frozen=True)
class Event:
    """Message envoyé par le thread de fond à l'interface via la file d'événements.

    Payload selon le type : « progress » → CrawlStats, « email » → EmailResult,
    « log » / « error » → LogMessage, « site_done » → SiteSummary, « done » → RunSummary.
    """

    type: EventType
    payload: Any = None
