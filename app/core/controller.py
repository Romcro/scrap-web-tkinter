"""Orchestration d'une session : threads, file d'événements, arrêt et statistiques.

L'interface appelle `start()` / `stop()` et lit `events` depuis son propre thread
(via `root.after`). Le contrôleur ne touche jamais aux widgets.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from typing import Any, Protocol

from app.core.crawler import HttpSession, PageOutcome, SiteCrawler, build_session
from app.core.url_utils import host_key, normalize_input_urls
from app.models import (
    CrawlStats,
    EmailResult,
    Event,
    EventType,
    LogLevel,
    LogMessage,
    RunSummary,
    Settings,
    SiteSummary,
)

logger = logging.getLogger(__name__)

_LOGGING_LEVELS: dict[LogLevel, int] = {
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "ERROR": logging.ERROR,
}


class ClosableSession(HttpSession, Protocol):
    """Session HTTP que le contrôleur ferme à la fin de chaque site."""

    def close(self) -> None:
        """Libère les connexions."""
        ...


SessionFactory = Callable[[Settings], ClosableSession]
CrawlerFactory = Callable[..., SiteCrawler]


def group_by_site(urls: Iterable[str]) -> list[tuple[str, list[str]]]:
    """Normalise les URL et les regroupe par site (« site.fr » et « www.site.fr » ensemble).

    Les URL d'un même site seront traitées l'une après l'autre par un seul worker,
    pour respecter le délai entre requêtes sur ce domaine.
    """
    groups: dict[str, list[str]] = {}
    for url in normalize_input_urls(urls):
        groups.setdefault(host_key(url), []).append(url)
    return list(groups.items())


class ScraperController:
    """Lance le traitement de plusieurs sites dans des threads de fond."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: SessionFactory = build_session,
        crawler_factory: CrawlerFactory = SiteCrawler,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.settings = settings if settings is not None else Settings()
        self.events: queue.Queue[Event] = queue.Queue()
        self._session_factory = session_factory
        self._crawler_factory = crawler_factory
        self._now = now
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stats = CrawlStats()
        self._seen_emails: set[str] = set()

    # --- API pour l'interface ---------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Vrai tant que la session n'est pas terminée."""
        return self._thread is not None and self._thread.is_alive()

    @property
    def stats(self) -> CrawlStats:
        """Copie des compteurs actuels."""
        with self._lock:
            return replace(self._stats)

    def start(self, urls: Iterable[str]) -> int:
        """Démarre une session et retourne le nombre de sites à traiter.

        Lève RuntimeError si une session est déjà en cours, ValueError si aucune URL
        n'est valide.
        """
        if self.is_running:
            raise RuntimeError("Une session est déjà en cours.")
        groups = group_by_site(urls)
        if not groups:
            raise ValueError("Aucune URL valide dans la liste.")
        settings = replace(self.settings)  # les modifications pendant la session sont ignorées
        self._stop = threading.Event()
        with self._lock:
            self._stats = CrawlStats(sites_total=len(groups))
            self._seen_emails = set()
        self._thread = threading.Thread(
            target=self._run, args=(groups, settings), name="scraper-controller", daemon=True
        )
        self._thread.start()
        return len(groups)

    def stop(self) -> None:
        """Demande l'arrêt : les crawlers s'interrompent avant leur prochaine requête."""
        self._stop.set()

    def join(self, timeout: float | None = None) -> bool:
        """Attend la fin de la session ; retourne True si elle est terminée."""
        if self._thread is not None:
            self._thread.join(timeout)
        return not self.is_running

    def drain_events(self) -> list[Event]:
        """Retire et retourne tous les événements en attente, sans bloquer."""
        drained: list[Event] = []
        while True:
            try:
                drained.append(self.events.get_nowait())
            except queue.Empty:
                return drained

    # --- thread de fond ---------------------------------------------------------------

    def _run(self, groups: list[tuple[str, list[str]]], settings: Settings) -> None:
        started = time.monotonic()
        self._log("INFO", f"Démarrage : {len(groups)} site(s) à traiter.")
        self._emit("progress", self.stats)
        try:
            workers = max(1, min(settings.max_workers, len(groups)))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="crawler") as pool:
                for site, urls in groups:
                    pool.submit(self._crawl_site, site, urls, settings)
        except Exception:
            logger.exception("Erreur inattendue du contrôleur")
            self._error("Erreur inattendue du traitement (voir le journal).")
        finally:
            duration = time.monotonic() - started
            stopped = self._stop.is_set()
            stats = self.stats
            if stopped:
                self._log("WARN", "Arrêt demandé : traitement interrompu.")
            else:
                self._log(
                    "INFO",
                    f"Terminé en {duration:.0f} s : {stats.sites_done} site(s), "
                    f"{stats.pages_visited} page(s), {stats.emails_found} e-mail(s), "
                    f"{stats.errors} erreur(s).",
                )
            self._emit("done", RunSummary(stats, stopped, duration))

    def _crawl_site(self, site: str, urls: list[str], settings: Settings) -> None:
        """Traite toutes les URL d'un site, l'une après l'autre. Ne lève jamais d'exception."""
        if self._stop.is_set():
            return
        pages = emails = errors = 0
        session: ClosableSession | None = None
        try:
            session = self._session_factory(settings)
            for index, url in enumerate(urls):
                if index > 0 and self._stop.wait(settings.delay_seconds):
                    break
                crawler = self._crawler_factory(
                    url,
                    settings,
                    session,
                    stop_event=self._stop,
                    include_subdomains=settings.include_subdomains,
                )
                for outcome in crawler.crawl():
                    fetched, new_emails, failed = self._handle_outcome(site, outcome)
                    pages += fetched
                    emails += new_emails
                    errors += failed
        except Exception:
            logger.exception("Erreur inattendue sur %s", site)
            errors += 1
            with self._lock:
                self._stats.errors += 1
            self._error(f"{site} : erreur inattendue, site abandonné (voir le journal).")
        finally:
            self._close(session)
            completed = not self._stop.is_set()
            with self._lock:
                self._stats.sites_done += 1
                snapshot = replace(self._stats)
            suffix = "" if completed else " (interrompu)"
            self._log("INFO", f"{site} : {pages} page(s) visitée(s), {emails} e-mail(s){suffix}")
            self._emit("site_done", SiteSummary(site, pages, emails, errors, completed))
            self._emit("progress", snapshot)

    def _handle_outcome(self, site: str, outcome: PageOutcome) -> tuple[int, int, int]:
        """Met à jour les compteurs et émet les événements d'une page.

        Retourne (page visitée, nouveaux e-mails, erreur) pour le bilan du site.
        """
        fetched = int(outcome.status != "skipped")
        failed = int(outcome.status == "error")
        with self._lock:
            new = [item for item in outcome.emails if item.email not in self._seen_emails]
            self._seen_emails.update(item.email for item in new)
            self._stats.pages_visited += fetched
            self._stats.errors += failed
            self._stats.emails_found += len(new)
            snapshot = replace(self._stats)

        found_at = self._now().replace(microsecond=0)
        for item in new:
            self._emit("email", EmailResult(item.email, site, outcome.url, found_at, item.method))
        if outcome.status == "error":
            self._log("WARN", f"{site} : {outcome.message} sur {outcome.url}")
        elif outcome.status == "skipped":
            self._log("INFO", f"{site} : page ignorée ({outcome.message}) {outcome.url}")
        self._emit("progress", snapshot)
        return fetched, len(new), failed

    # --- utilitaires ------------------------------------------------------------------

    def _emit(self, event_type: EventType, payload: Any) -> None:
        self.events.put(Event(event_type, payload))

    def _log(self, level: LogLevel, message: str) -> None:
        logger.log(_LOGGING_LEVELS[level], message)
        self._emit("log", LogMessage(level, message, self._now().replace(microsecond=0)))

    def _error(self, message: str) -> None:
        logger.error(message)
        self._emit("error", LogMessage("ERROR", message, self._now().replace(microsecond=0)))

    @staticmethod
    def _close(session: ClosableSession | None) -> None:
        if session is None:
            return
        try:
            session.close()
        except Exception:
            logger.debug("Fermeture de session impossible", exc_info=True)
