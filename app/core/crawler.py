"""Parcours des pages d'un site et collecte des adresses e-mail."""

from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

from app.core.extractor import ExtractedEmail, extract_emails_from_soup
from app.core.robots import RobotsCache
from app.core.url_utils import (
    is_same_site,
    normalize_url,
    priority_score,
    resolve_link,
    site_label,
)
from app.models import Settings

logger = logging.getLogger(__name__)

# Statuts HTTP donnant droit à une seule nouvelle tentative.
RETRY_STATUSES: frozenset[int] = frozenset({429, 503})
# Attente avant la nouvelle tentative si le serveur n'indique pas de « Retry-After ».
DEFAULT_RETRY_SECONDS = 5.0
# Au-delà de cette attente demandée par le serveur, on abandonne la page.
MAX_RETRY_AFTER_SECONDS = 60.0
# Types de contenu analysés.
HTML_CONTENT_TYPES: tuple[str, ...] = ("text/html", "application/xhtml+xml")

PageStatus = Literal["ok", "error", "skipped"]


class HttpSession(Protocol):
    """Ce dont le crawler a besoin d'une session HTTP (requests.Session ou substitut de test)."""

    def get(self, url: str, *, timeout: float, allow_redirects: bool = ...) -> requests.Response:
        """Envoie une requête GET."""
        ...


@dataclass(frozen=True)
class PageOutcome:
    """Résultat de la visite d'une page."""

    url: str
    depth: int
    status: PageStatus
    emails: tuple[ExtractedEmail, ...] = ()
    message: str = ""


class CrawlStopped(Exception):
    """Levée en interne quand l'arrêt est demandé pendant une attente."""


def build_session(settings: Settings) -> requests.Session:
    """Crée une session HTTP identifiable (User-Agent avec contact, pas d'usurpation)."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": settings.user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
        }
    )
    return session


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Convertit un en-tête Retry-After (secondes ou date HTTP) en secondes d'attente."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - (now or datetime.now(UTC))).total_seconds())


def describe_request_error(exc: requests.RequestException) -> str:
    """Message court et compréhensible pour une erreur réseau."""
    if isinstance(exc, requests.exceptions.SSLError):
        return "erreur SSL (certificat invalide)"
    if isinstance(exc, requests.Timeout):
        return "délai dépassé"
    if isinstance(exc, requests.TooManyRedirects):
        return "trop de redirections"
    if isinstance(exc, requests.ConnectionError):
        return "connexion impossible"
    return f"erreur réseau ({type(exc).__name__})"


class SiteCrawler:
    """Explore un site à partir de son URL de départ et produit un PageOutcome par page.

    Parcours en largeur, pages de contact en priorité, limité au même site,
    à `max_depth` et à `max_pages_per_site`. Respecte le délai entre requêtes,
    le robots.txt (si activé) et l'arrêt demandé via `stop_event`.
    Aucune exception réseau ne sort du crawler.
    """

    def __init__(
        self,
        start_url: str,
        settings: Settings,
        session: HttpSession,
        *,
        stop_event: threading.Event | None = None,
        include_subdomains: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self.start_url = normalize_url(start_url)
        self.settings = settings
        self.pages_fetched = 0
        self._session = session
        self._stop = stop_event if stop_event is not None else threading.Event()
        self._include_subdomains = include_subdomains
        self._clock = clock
        # Par défaut, l'attente est interrompue immédiatement si l'arrêt est demandé.
        self._sleep = sleep if sleep is not None else self._stop.wait
        self._base_url = self.start_url
        self._last_request: float | None = None
        self._robots = (
            RobotsCache(self._polite_get, settings.user_agent) if settings.respect_robots else None
        )

    @property
    def site(self) -> str:
        """Libellé du site de référence (ex. : « site1.fr »)."""
        return site_label(self.start_url)

    def crawl(self) -> Iterator[PageOutcome]:
        """Parcourt le site ; s'arrête proprement dès que `stop_event` est levé."""
        counter = itertools.count()
        frontier: list[tuple[int, int, int, str]] = [(0, 0, next(counter), self.start_url)]
        seen: set[str] = {self.start_url}
        try:
            while frontier and self.pages_fetched < self.settings.max_pages_per_site:
                if self._stop.is_set():
                    return
                _, depth, _, url = heapq.heappop(frontier)
                if self._robots is not None and not self._robots.can_fetch(url):
                    yield PageOutcome(url, depth, "skipped", message="interdit par robots.txt")
                    continue
                outcome, links = self._safe_visit(url, depth)
                seen.add(outcome.url)
                yield outcome
                if depth >= self.settings.max_depth:
                    continue
                for link in links:
                    if link not in seen:
                        seen.add(link)
                        heapq.heappush(
                            frontier, (priority_score(link), depth + 1, next(counter), link)
                        )
        except CrawlStopped:
            return

    # --- visite d'une page -----------------------------------------------------------

    def _safe_visit(self, url: str, depth: int) -> tuple[PageOutcome, list[str]]:
        try:
            return self._visit(url, depth)
        except CrawlStopped:
            raise
        except Exception:
            logger.exception("Erreur inattendue sur %s", url)
            return PageOutcome(
                url, depth, "error", message="erreur inattendue (voir le journal)"
            ), []

    def _visit(self, url: str, depth: int) -> tuple[PageOutcome, list[str]]:
        self.pages_fetched += 1
        try:
            response = self._get_with_retry(url)
        except requests.RequestException as exc:
            return PageOutcome(url, depth, "error", message=describe_request_error(exc)), []

        final_url = normalize_url(response.url) if response.url else url
        if not self._is_internal(final_url):
            if depth > 0:
                return PageOutcome(
                    final_url, depth, "skipped", message="redirection hors du site"
                ), []
            # La page d'accueil redirige vers un autre domaine : c'est le nouveau site de référence.
            self._base_url = final_url

        if response.status_code >= 400:
            return PageOutcome(
                final_url, depth, "error", message=f"HTTP {response.status_code}"
            ), []

        content_type = response.headers.get("Content-Type", "").lower()
        if not content_type.startswith(HTML_CONTENT_TYPES):
            label = content_type.split(";", 1)[0] or "inconnu"
            return PageOutcome(
                final_url, depth, "skipped", message=f"contenu non HTML ({label})"
            ), []

        encoding = response.encoding if "charset=" in content_type else None
        soup = BeautifulSoup(response.content, "lxml", from_encoding=encoding)
        links = self._extract_links(soup, final_url)
        emails = tuple(extract_emails_from_soup(soup))
        return PageOutcome(final_url, depth, "ok", emails), links

    def _extract_links(self, soup: BeautifulSoup, page_url: str) -> list[str]:
        base = page_url
        base_tag = soup.find("base", href=True)
        if isinstance(base_tag, Tag):
            base_href = base_tag.get("href")
            if isinstance(base_href, str):
                base = urljoin(page_url, base_href)
        links: list[str] = []
        for tag in soup.find_all(["a", "area"], href=True):
            if not isinstance(tag, Tag):
                continue
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            link = resolve_link(href, base)
            if link is not None and self._is_internal(link):
                links.append(link)
        return links

    def _is_internal(self, url: str) -> bool:
        return is_same_site(url, self._base_url, include_subdomains=self._include_subdomains)

    # --- requêtes polies ---------------------------------------------------------------

    def _get_with_retry(self, url: str) -> requests.Response:
        response = self._polite_get(url)
        if response.status_code not in RETRY_STATUSES:
            return response
        wait = parse_retry_after(response.headers.get("Retry-After"))
        if wait is None:
            wait = DEFAULT_RETRY_SECONDS
        if wait > MAX_RETRY_AFTER_SECONDS:
            logger.debug("%s : Retry-After de %.0f s, abandon", url, wait)
            return response
        logger.debug(
            "%s : HTTP %s, nouvelle tentative dans %.1f s", url, response.status_code, wait
        )
        self._pause(wait)
        return self._polite_get(url)

    def _polite_get(self, url: str) -> requests.Response:
        """GET en respectant le délai minimal depuis la requête précédente."""
        if self._last_request is not None:
            remaining = self._delay() - (self._clock() - self._last_request)
            if remaining > 0:
                self._pause(remaining)
        if self._stop.is_set():
            raise CrawlStopped
        try:
            return self._session.get(
                url, timeout=self.settings.timeout_seconds, allow_redirects=True
            )
        finally:
            self._last_request = self._clock()

    def _delay(self) -> float:
        delay = self.settings.delay_seconds
        if self._robots is not None:
            robots_delay = self._robots.crawl_delay(self._base_url)
            if robots_delay is not None:
                delay = max(delay, robots_delay)
        return delay

    def _pause(self, seconds: float) -> None:
        self._sleep(seconds)
        if self._stop.is_set():
            raise CrawlStopped
