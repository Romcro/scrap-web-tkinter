"""Lecture et mise en cache des fichiers robots.txt."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

Fetcher = Callable[[str], requests.Response]

_ALLOW_ALL: list[str] = []
_DISALLOW_ALL: list[str] = ["User-agent: *", "Disallow: /"]


def robots_url(url: str) -> str:
    """URL du robots.txt qui s'applique à `url`."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))


class RobotsCache:
    """Télécharge chaque robots.txt une seule fois et répond aux questions d'autorisation.

    Règles (RFC 9309) :
    - 2xx : le fichier est appliqué ;
    - 4xx : pas de règle, tout est autorisé ;
    - 5xx : serveur indisponible, tout est interdit par prudence ;
    - erreur réseau : tout est autorisé, l'erreur réelle apparaîtra sur la page elle-même.
    """

    def __init__(self, fetch: Fetcher, user_agent: str) -> None:
        self._fetch = fetch
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}
        self._lock = threading.Lock()

    def can_fetch(self, url: str) -> bool:
        """Indique si le robots.txt autorise la visite de `url` (le télécharge si besoin)."""
        return self._parser_for(url).can_fetch(self._user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        """Délai « Crawl-delay » demandé, si le robots.txt a déjà été lu (aucun téléchargement)."""
        parser = self._parsers.get(robots_url(url))
        if parser is None:
            return None
        delay = parser.crawl_delay(self._user_agent)
        if delay is None:
            return None
        try:
            return float(delay)
        except (TypeError, ValueError):
            return None

    def _parser_for(self, url: str) -> RobotFileParser:
        key = robots_url(url)
        with self._lock:
            parser = self._parsers.get(key)
            if parser is None:
                parser = self._load(key)
                self._parsers[key] = parser
        return parser

    def _load(self, url: str) -> RobotFileParser:
        parser = RobotFileParser(url)
        lines: list[str] = _ALLOW_ALL
        try:
            response = self._fetch(url)
        except requests.RequestException as exc:
            logger.debug("robots.txt injoignable (%s) : %s", url, exc)
        else:
            if response.status_code >= 500:
                logger.debug("robots.txt en erreur %s (%s)", response.status_code, url)
                lines = _DISALLOW_ALL
            elif response.status_code < 400:
                lines = response.content.decode("utf-8", errors="replace").splitlines()
        parser.parse(lines)
        return parser
