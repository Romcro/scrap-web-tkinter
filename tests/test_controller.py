"""Tests de l'orchestration multi-sites (vrais threads, réponses HTTP simulées)."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime
from typing import Any

import pytest
import requests

from app.core.controller import ScraperController, group_by_site
from app.core.crawler import SiteCrawler
from app.models import CrawlStats, EmailResult, Event, RunSummary, Settings, SiteSummary
from tests.fakes import FakeSession, Route, RouteSpec, page

NOW = datetime(2026, 11, 26, 12, 0, 0)
FAST = Settings(delay_seconds=0, respect_robots=False, max_workers=1)
TIMEOUT = 5.0


class Harness:
    """Contrôleur branché sur des sessions simulées partageant les mêmes routes."""

    def __init__(
        self, routes: dict[str, RouteSpec], settings: Settings = FAST, **kwargs: Any
    ) -> None:
        self.routes = routes
        self.sessions: list[FakeSession] = []
        self.controller = ScraperController(
            settings, session_factory=self._new_session, now=lambda: NOW, **kwargs
        )

    def _new_session(self, _settings: Settings) -> FakeSession:
        session = FakeSession(self.routes)
        self.sessions.append(session)
        return session

    def run(self, urls: list[str]) -> list[Event]:
        self.controller.start(urls)
        assert self.controller.join(timeout=TIMEOUT), "la session ne s'est pas terminée"
        return self.controller.drain_events()


def payloads(events: list[Event], event_type: str) -> list[Any]:
    return [event.payload for event in events if event.type == event_type]


def summary(events: list[Event]) -> RunSummary:
    assert events[-1].type == "done"
    result: RunSummary = events[-1].payload
    return result


def messages(events: list[Event]) -> list[str]:
    return [p.message for p in payloads(events, "log") + payloads(events, "error")]


# --- regroupement --------------------------------------------------------------------


def test_group_by_site() -> None:
    urls = ["site.fr/a", "www.site.fr/b", "", "autre.fr", "site.fr/a", "pas une url"]
    assert group_by_site(urls) == [
        ("site.fr", ["https://site.fr/a", "https://www.site.fr/b"]),
        ("autre.fr", ["https://autre.fr"]),
    ]


def test_urls_of_same_site_share_one_worker() -> None:
    harness = Harness({})
    events = harness.run(["site.fr/a", "www.site.fr/b", "autre.fr"])
    assert summary(events).stats.sites_total == 2
    assert [s.calls for s in harness.sessions] == [
        ["https://site.fr/a", "https://www.site.fr/b"],
        ["https://autre.fr"],
    ]


# --- déroulement normal --------------------------------------------------------------


def test_runs_all_sites_and_emits_results() -> None:
    harness = Harness(
        {
            "https://a.fr": Route(body=page("contact@a.fr", ["/contact"])),
            "https://a.fr/contact": Route(body=page("direction [at] a [dot] fr")),
            "https://b.fr": Route(body=page(links=["mailto:Info@B.fr"])),
        }
    )
    events = harness.run(["a.fr", "b.fr"])

    assert payloads(events, "email") == [
        EmailResult("contact@a.fr", "a.fr", "https://a.fr", NOW, "regex"),
        EmailResult("direction@a.fr", "a.fr", "https://a.fr/contact", NOW, "obfuscated"),
        EmailResult("info@b.fr", "b.fr", "https://b.fr", NOW, "mailto"),
    ]
    assert payloads(events, "site_done") == [
        SiteSummary("a.fr", 2, 2, 0, True),
        SiteSummary("b.fr", 1, 1, 0, True),
    ]
    result = summary(events)
    assert result.stats == CrawlStats(
        sites_total=2, sites_done=2, pages_visited=3, emails_found=3, errors=0
    )
    assert not result.stopped
    assert harness.controller.stats == result.stats


def test_log_messages() -> None:
    harness = Harness({"https://a.fr": Route(body=page("contact@a.fr"))})
    events = harness.run(["a.fr"])
    assert events[0].type == "log"
    assert events[0].payload.message == "Démarrage : 1 site(s) à traiter."
    assert "a.fr : 1 page(s) visitée(s), 1 e-mail(s)" in messages(events)
    assert messages(events)[-1].startswith("Terminé en ")


def test_progress_events_carry_stats() -> None:
    harness = Harness({"https://a.fr": Route(body=page("contact@a.fr", ["/x"]))})
    progress = payloads(harness.run(["a.fr"]), "progress")
    assert all(isinstance(p, CrawlStats) for p in progress)
    assert progress[0] == CrawlStats(sites_total=1)
    assert progress[-1].sites_done == 1
    assert [p.pages_visited for p in progress] == sorted(p.pages_visited for p in progress)


def test_duplicate_emails_across_sites_are_reported_once() -> None:
    harness = Harness(
        {
            "https://a.fr": Route(body=page("commun@groupe.fr")),
            "https://b.fr": Route(body=page("commun@groupe.fr, autre@b.fr")),
        }
    )
    events = harness.run(["a.fr", "b.fr"])
    assert [(e.email, e.site) for e in payloads(events, "email")] == [
        ("commun@groupe.fr", "a.fr"),
        ("autre@b.fr", "b.fr"),
    ]
    assert summary(events).stats.emails_found == 2


def test_skipped_pages_are_logged_but_not_counted() -> None:
    harness = Harness(
        {
            "https://a.fr/robots.txt": Route(body="User-agent: *\nDisallow: /prive\n"),
            "https://a.fr": Route(body=page(links=["/prive"])),
        },
        replace(FAST, respect_robots=True),
    )
    events = harness.run(["a.fr"])
    assert summary(events).stats.pages_visited == 1
    assert "a.fr : page ignorée (interdit par robots.txt) https://a.fr/prive" in messages(events)


def test_sessions_are_closed() -> None:
    harness = Harness({})
    harness.run(["a.fr", "b.fr", "c.fr"])
    assert len(harness.sessions) == 3
    assert all(s.closed for s in harness.sessions)


def test_restart_after_completion_resets_counters() -> None:
    harness = Harness({"https://a.fr": Route(body=page("contact@a.fr"))})
    first = summary(harness.run(["a.fr"]))
    second_events = harness.run(["a.fr"])
    assert summary(second_events).stats == first.stats
    assert len(payloads(second_events, "email")) == 1


# --- erreurs -------------------------------------------------------------------------


def test_failing_site_does_not_stop_the_others() -> None:
    harness = Harness(
        {
            "https://a.fr": requests.ConnectionError(),
            "https://b.fr": Route(body=page("info@b.fr")),
        }
    )
    events = harness.run(["a.fr", "b.fr"])
    stats = summary(events).stats
    assert (stats.sites_done, stats.errors, stats.emails_found) == (2, 1, 1)
    assert "a.fr : connexion impossible sur https://a.fr" in messages(events)


def test_unexpected_crash_of_a_site_is_contained() -> None:
    def factory(url: str, *args: Any, **kwargs: Any) -> SiteCrawler:
        if "a.fr" in url:
            raise RuntimeError("panne")
        return SiteCrawler(url, *args, **kwargs)

    harness = Harness({"https://b.fr": Route(body=page("info@b.fr"))}, crawler_factory=factory)
    events = harness.run(["a.fr", "b.fr"])
    errors = payloads(events, "error")
    assert [e.message for e in errors] == [
        "a.fr : erreur inattendue, site abandonné (voir le journal)."
    ]
    assert [e.email for e in payloads(events, "email")] == ["info@b.fr"]
    assert summary(events).stats.errors == 1


def test_start_without_valid_url() -> None:
    with pytest.raises(ValueError, match="Aucune URL valide"):
        ScraperController(FAST).start(["", "  ", "pas une url"])


def test_start_while_running_is_refused() -> None:
    gate = threading.Event()

    def slow() -> Route:
        gate.wait(TIMEOUT)
        return Route(body=page())

    harness = Harness({"https://a.fr": slow})
    harness.controller.start(["a.fr"])
    try:
        assert harness.controller.is_running
        with pytest.raises(RuntimeError, match="déjà en cours"):
            harness.controller.start(["b.fr"])
    finally:
        gate.set()
    assert harness.controller.join(timeout=TIMEOUT)
    assert not harness.controller.is_running


# --- arrêt et parallélisme -----------------------------------------------------------


def test_stop_interrupts_waiting_and_skips_remaining_sites() -> None:
    first_page_served = threading.Event()

    def home() -> Route:
        first_page_served.set()
        return Route(body=page("contact@a.fr", ["/suite", "/encore"]))

    # Délai réel de 30 s entre deux requêtes : l'arrêt doit l'interrompre immédiatement.
    harness = Harness({"https://a.fr": home}, replace(FAST, delay_seconds=30))
    harness.controller.start(["a.fr", "b.fr"])
    assert first_page_served.wait(TIMEOUT)
    harness.controller.stop()
    assert harness.controller.join(timeout=2.0), "l'arrêt a pris plus de 2 s"

    events = harness.controller.drain_events()
    result = summary(events)
    assert result.stopped
    assert [s.calls for s in harness.sessions] == [["https://a.fr"]]  # b.fr jamais démarré
    assert payloads(events, "site_done") == [SiteSummary("a.fr", 1, 1, 0, False)]
    assert [e.email for e in payloads(events, "email")] == ["contact@a.fr"]
    assert "Arrêt demandé : traitement interrompu." in messages(events)


def test_sites_are_processed_in_parallel() -> None:
    # Chaque page attend que l'autre site soit aussi en cours : échoue si traitement séquentiel.
    barrier = threading.Barrier(2, timeout=TIMEOUT)

    def meet(email: str) -> RouteSpec:
        def respond() -> Route:
            barrier.wait()
            return Route(body=page(email))

        return respond

    harness = Harness(
        {"https://a.fr": meet("a@a.fr"), "https://b.fr": meet("b@b.fr")},
        replace(FAST, max_workers=2),
    )
    events = harness.run(["a.fr", "b.fr"])
    assert summary(events).stats.errors == 0
    assert {e.email for e in payloads(events, "email")} == {"a@a.fr", "b@b.fr"}
