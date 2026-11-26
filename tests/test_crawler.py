"""Tests du crawler avec réponses HTTP simulées (aucun accès réseau réel)."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest
import requests

from app.core.crawler import (
    DEFAULT_RETRY_SECONDS,
    PageOutcome,
    SiteCrawler,
    parse_retry_after,
)
from app.models import Settings
from tests.fakes import FakeClock, FakeSession, Route, RouteSpec, page

START = "https://site.fr"
FAST = Settings(delay_seconds=0, max_depth=2, max_pages_per_site=50)


def run(
    routes: dict[str, RouteSpec],
    settings: Settings = FAST,
    *,
    start: str = START,
    include_subdomains: bool = False,
) -> tuple[list[PageOutcome], FakeSession, FakeClock]:
    session = FakeSession(routes)
    clock = FakeClock()
    crawler = SiteCrawler(
        start,
        settings,
        session,
        include_subdomains=include_subdomains,
        clock=clock.time,
        sleep=clock.sleep,
    )
    return list(crawler.crawl()), session, clock


def all_emails(outcomes: list[PageOutcome]) -> set[str]:
    return {item.email for outcome in outcomes for item in outcome.emails}


# --- parcours ------------------------------------------------------------------------


def test_collects_emails_across_pages() -> None:
    outcomes, _, _ = run(
        {
            START: Route(body=page("accueil@site.fr", ["/contact", "/blog"])),
            f"{START}/contact": Route(body=page("direction [at] site [dot] fr")),
            f"{START}/blog": Route(body=page("Aucune adresse ici")),
        }
    )
    assert [o.url for o in outcomes] == [START, f"{START}/contact", f"{START}/blog"]
    assert all(o.status == "ok" for o in outcomes)
    assert all_emails(outcomes) == {"accueil@site.fr", "direction@site.fr"}


def test_contact_pages_are_visited_first() -> None:
    _, session, _ = run(
        {
            START: Route(
                body=page(links=["/blog", "/produits", "/nous-contacter", "/mentions-legales"])
            ),
        }
    )
    assert session.page_calls == [
        START,
        f"{START}/nous-contacter",
        f"{START}/mentions-legales",
        f"{START}/blog",
        f"{START}/produits",
    ]


@pytest.mark.parametrize(("max_depth", "expected"), [(0, 1), (1, 2), (2, 3), (5, 4)])
def test_max_depth_is_respected(max_depth: int, expected: int) -> None:
    routes: dict[str, RouteSpec] = {
        START: Route(body=page(links=["/a"])),
        f"{START}/a": Route(body=page(links=["/b"])),
        f"{START}/b": Route(body=page(links=["/c"])),
        f"{START}/c": Route(body=page()),
    }
    _, session, _ = run(routes, replace(FAST, max_depth=max_depth))
    assert len(session.page_calls) == expected


def test_max_pages_is_respected() -> None:
    links = [f"/page-{i}" for i in range(10)]
    _, session, _ = run({START: Route(body=page(links=links))}, replace(FAST, max_pages_per_site=3))
    assert len(session.page_calls) == 3


def test_errors_count_towards_max_pages() -> None:
    links = [f"/page-{i}" for i in range(10)]
    routes: dict[str, RouteSpec] = {START: Route(body=page(links=links))}
    _, session, _ = run(routes, replace(FAST, max_pages_per_site=4))  # les sous-pages sont en 404
    assert len(session.page_calls) == 4


def test_only_same_site_links_are_followed() -> None:
    links = ["https://autre.fr/contact", "https://blog.site.fr/x", "https://www.site.fr/equipe"]
    _, session, _ = run({START: Route(body=page(links=links))})
    assert session.page_calls == [START, "https://www.site.fr/equipe"]


def test_subdomains_are_followed_when_enabled() -> None:
    links = ["https://autre.fr/contact", "https://blog.site.fr/x"]
    _, session, _ = run({START: Route(body=page(links=links))}, include_subdomains=True)
    assert session.page_calls == [START, "https://blog.site.fr/x"]


def test_ignored_links_are_not_fetched() -> None:
    links = [
        "#haut",
        "javascript:void(0)",
        "mailto:info@site.fr",
        "tel:+33123456789",
        "/plaquette.pdf",
        "/logo.png",
        "/archive.zip",
    ]
    outcomes, session, _ = run({START: Route(body=page(links=links))})
    assert session.page_calls == [START]
    assert all_emails(outcomes) == {"info@site.fr"}


def test_pages_are_visited_only_once() -> None:
    links = [
        "/contact",
        "/contact/",
        "/contact#formulaire",
        "https://site.fr/contact",
        "HTTPS://SITE.FR/contact",
        "/",
        START,
    ]
    _, session, _ = run(
        {
            START: Route(body=page(links=links)),
            f"{START}/contact": Route(body=page(links=["/", "/contact"])),
        }
    )
    assert session.page_calls == [START, f"{START}/contact"]


def test_base_href_is_respected() -> None:
    head = '<base href="https://site.fr/sous-dossier/">'
    _, session, _ = run({START: Route(body=page(links=["page"], head=head))})
    assert session.page_calls == [START, f"{START}/sous-dossier/page"]


# --- redirections --------------------------------------------------------------------


def test_redirect_within_site() -> None:
    outcomes, session, _ = run(
        {
            START: Route(body=page(links=["contact"]), final_url="https://www.site.fr/accueil/"),
            "https://www.site.fr/contact": Route(body=page("info@site.fr")),
        }
    )
    assert outcomes[0].url == "https://www.site.fr/accueil"
    assert session.page_calls == [START, "https://www.site.fr/contact"]
    assert all_emails(outcomes) == {"info@site.fr"}


def test_redirect_outside_site_is_skipped() -> None:
    outcomes, session, _ = run(
        {
            START: Route(body=page(links=["/partenaire"])),
            f"{START}/partenaire": Route(
                body=page("pub@autre.fr", ["/x"]), final_url="https://autre.fr"
            ),
        }
    )
    assert outcomes[1].status == "skipped"
    assert outcomes[1].message == "redirection hors du site"
    assert all_emails(outcomes) == set()
    assert session.page_calls == [START, f"{START}/partenaire"]


def test_start_page_redirecting_to_new_domain_becomes_reference() -> None:
    outcomes, session, _ = run(
        {
            "https://ancien.fr": Route(
                body=page(links=["/contact"]), final_url="https://nouveau.fr/"
            ),
            "https://nouveau.fr/contact": Route(body=page("contact@nouveau.fr")),
        },
        start="https://ancien.fr",
    )
    assert session.page_calls == ["https://ancien.fr", "https://nouveau.fr/contact"]
    assert all_emails(outcomes) == {"contact@nouveau.fr"}


# --- contenus et erreurs -------------------------------------------------------------


def test_non_html_content_is_skipped() -> None:
    outcomes, session, _ = run(
        {
            START: Route(body=page(links=["/fichier", "/sans-type"])),
            f"{START}/fichier": Route(
                body=b"%PDF info@site.fr", headers={"Content-Type": "application/pdf"}
            ),
            f"{START}/sans-type": Route(body=page("x@site.fr", ["/suite"]), headers={}),
        }
    )
    assert [o.status for o in outcomes] == ["ok", "skipped", "skipped"]
    assert outcomes[1].message == "contenu non HTML (application/pdf)"
    assert all_emails(outcomes) == set()
    assert f"{START}/suite" not in session.page_calls


def test_http_errors_do_not_stop_the_crawl() -> None:
    outcomes, _, _ = run(
        {
            START: Route(body=page(links=["/a", "/b", "/c"])),
            f"{START}/a": Route(status=404),
            f"{START}/b": Route(status=500),
            f"{START}/c": Route(body=page("ok@site.fr")),
        }
    )
    assert [(o.status, o.message) for o in outcomes] == [
        ("ok", ""),
        ("error", "HTTP 404"),
        ("error", "HTTP 500"),
        ("ok", ""),
    ]
    assert all_emails(outcomes) == {"ok@site.fr"}


@pytest.mark.parametrize(
    ("exc", "message"),
    [
        (requests.Timeout(), "délai dépassé"),
        (requests.exceptions.ConnectTimeout(), "délai dépassé"),
        (requests.exceptions.SSLError(), "erreur SSL (certificat invalide)"),
        (requests.ConnectionError(), "connexion impossible"),
        (requests.TooManyRedirects(), "trop de redirections"),
        (requests.exceptions.ChunkedEncodingError(), "erreur réseau (ChunkedEncodingError)"),
    ],
)
def test_network_errors_do_not_stop_the_crawl(exc: Exception, message: str) -> None:
    outcomes, _, _ = run(
        {
            START: Route(body=page(links=["/a", "/b"])),
            f"{START}/a": exc,
            f"{START}/b": Route(body=page("ok@site.fr")),
        }
    )
    assert (outcomes[1].status, outcomes[1].message) == ("error", message)
    assert all_emails(outcomes) == {"ok@site.fr"}


def test_unreachable_site() -> None:
    outcomes, _, _ = run({START: requests.ConnectionError()})
    assert [(o.status, o.message) for o in outcomes] == [("error", "connexion impossible")]


def test_unexpected_error_is_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object) -> list[object]:
        raise RuntimeError("analyse impossible")

    monkeypatch.setattr("app.core.crawler.extract_emails_from_soup", boom)
    outcomes, _, _ = run({START: Route(body=page("x@site.fr"))})
    assert [o.status for o in outcomes] == ["error"]


# --- nouvelle tentative (429 / 503) --------------------------------------------------


def test_retry_after_429() -> None:
    outcomes, session, clock = run(
        {
            START: [
                Route(status=429, headers={"Retry-After": "2"}),
                Route(body=page("ok@site.fr")),
            ],
        }
    )
    assert session.page_calls == [START, START]
    assert clock.sleeps == [2.0]
    assert outcomes[0].status == "ok"


def test_retry_without_retry_after_uses_default_wait() -> None:
    _, _, clock = run({START: [Route(status=503), Route(body=page())]})
    assert clock.sleeps == [DEFAULT_RETRY_SECONDS]


def test_only_one_retry() -> None:
    outcomes, session, _ = run({START: Route(status=503, headers={"Retry-After": "1"})})
    assert session.page_calls == [START, START]
    assert (outcomes[0].status, outcomes[0].message) == ("error", "HTTP 503")


def test_no_retry_when_server_asks_too_long_a_wait() -> None:
    outcomes, session, clock = run({START: Route(status=429, headers={"Retry-After": "3600"})})
    assert session.page_calls == [START]
    assert clock.sleeps == []
    assert outcomes[0].message == "HTTP 429"


def test_parse_retry_after() -> None:
    now = datetime(2026, 11, 26, 12, 0, 0, tzinfo=UTC)
    assert parse_retry_after("120") == 120.0
    assert parse_retry_after("Thu, 26 Nov 2026 12:00:30 GMT", now) == 30.0
    assert parse_retry_after("Thu, 26 Nov 2026 11:00:00 GMT", now) == 0.0
    assert parse_retry_after("bientôt") is None
    assert parse_retry_after(None) is None


# --- délai entre requêtes ------------------------------------------------------------


def test_delay_between_requests() -> None:
    settings = replace(FAST, delay_seconds=1.5, respect_robots=False)
    _, session, clock = run({START: Route(body=page(links=["/a", "/b"]))}, settings)
    assert len(session.page_calls) == 3
    assert clock.sleeps == [1.5, 1.5]


def test_robots_crawl_delay_is_respected() -> None:
    robots = Route(body="User-agent: *\nCrawl-delay: 3\n", headers={"Content-Type": "text/plain"})
    _, _, clock = run(
        {
            f"{START}/robots.txt": robots,
            START: Route(body=page(links=["/a"])),
        }
    )
    assert clock.sleeps == [3.0, 3.0]


# --- arrêt ---------------------------------------------------------------------------


def test_stop_event_between_pages() -> None:
    stop = threading.Event()
    session = FakeSession({START: Route(body=page(links=["/a", "/b", "/c"]))})
    crawler = SiteCrawler(START, FAST, session, stop_event=stop)
    outcomes = []
    for outcome in crawler.crawl():
        outcomes.append(outcome)
        stop.set()
    assert len(outcomes) == 1
    assert session.page_calls == [START]


def test_stop_event_interrupts_waiting() -> None:
    stop = threading.Event()
    session = FakeSession({START: Route(body=page(links=["/a"]))})
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        stop.set()  # l'utilisateur clique sur « Arrêter » pendant l'attente

    settings = replace(FAST, delay_seconds=10, respect_robots=False)
    crawler = SiteCrawler(START, settings, session, stop_event=stop, sleep=sleep)
    outcomes = list(crawler.crawl())
    assert len(outcomes) == 1
    assert session.page_calls == [START]
    assert len(waits) == 1


def test_stop_before_start() -> None:
    stop = threading.Event()
    stop.set()
    session = FakeSession({START: Route(body=page())})
    assert list(SiteCrawler(START, FAST, session, stop_event=stop).crawl()) == []
    assert session.calls == []


# --- robots.txt ----------------------------------------------------------------------


def robots(body: str, status: int = 200) -> Route:
    return Route(status=status, body=body, headers={"Content-Type": "text/plain"})


def test_robots_disallowed_pages_are_skipped() -> None:
    outcomes, session, _ = run(
        {
            f"{START}/robots.txt": robots("User-agent: *\nDisallow: /prive\n"),
            START: Route(body=page(links=["/prive/annuaire", "/public"])),
        }
    )
    assert session.page_calls == [START, f"{START}/public"]
    skipped = [o for o in outcomes if o.status == "skipped"]
    assert [(o.url, o.message) for o in skipped] == [
        (f"{START}/prive/annuaire", "interdit par robots.txt")
    ]


def test_robots_rules_for_our_user_agent() -> None:
    outcomes, session, _ = run(
        {
            f"{START}/robots.txt": robots("User-agent: EmailScraperDesktop\nDisallow: /\n"),
            START: Route(body=page("x@site.fr")),
        }
    )
    assert session.page_calls == []
    assert [o.status for o in outcomes] == ["skipped"]


def test_robots_ignored_when_disabled() -> None:
    _, session, _ = run(
        {
            f"{START}/robots.txt": robots("User-agent: *\nDisallow: /\n"),
            START: Route(body=page(links=["/a"])),
        },
        replace(FAST, respect_robots=False),
    )
    assert session.calls == [START, f"{START}/a"]


def test_robots_fetched_once() -> None:
    _, session, _ = run({START: Route(body=page(links=["/a", "/b"]))})
    assert session.calls.count(f"{START}/robots.txt") == 1


@pytest.mark.parametrize(
    ("spec", "allowed"),
    [
        (robots("", status=404), True),
        (robots("", status=403), True),
        (robots("", status=500), False),
        (requests.ConnectionError(), True),
    ],
)
def test_robots_status_handling(spec: RouteSpec, allowed: bool) -> None:
    _, session, _ = run({f"{START}/robots.txt": spec, START: Route(body=page())})
    assert (session.page_calls == [START]) is allowed
