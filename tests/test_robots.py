"""Tests du cache robots.txt."""

from __future__ import annotations

from app.core.robots import RobotsCache, robots_url
from tests.fakes import FakeSession, Route

UA = "EmailScraperDesktop/1.0 (+contact@votre-domaine.fr)"


def make_cache(routes: dict[str, Route]) -> tuple[RobotsCache, FakeSession]:
    session = FakeSession(dict(routes))
    return RobotsCache(lambda url: session.get(url, timeout=5), UA), session


def test_robots_url() -> None:
    assert robots_url("https://site.fr/a/b?c=1#d") == "https://site.fr/robots.txt"
    assert robots_url("http://site.fr:8080/x") == "http://site.fr:8080/robots.txt"


def test_one_robots_file_per_host() -> None:
    cache, session = make_cache({})
    cache.can_fetch("https://site.fr/a")
    cache.can_fetch("https://site.fr/b")
    cache.can_fetch("https://blog.site.fr/c")
    assert session.calls == ["https://site.fr/robots.txt", "https://blog.site.fr/robots.txt"]


def test_crawl_delay_does_not_download() -> None:
    cache, session = make_cache(
        {
            "https://site.fr/robots.txt": Route(body="User-agent: *\nCrawl-delay: 2\n"),
        }
    )
    assert cache.crawl_delay("https://site.fr") is None
    assert session.calls == []
    cache.can_fetch("https://site.fr")
    assert cache.crawl_delay("https://site.fr/page") == 2.0


def test_allow_overrides_disallow() -> None:
    cache, _ = make_cache(
        {
            "https://site.fr/robots.txt": Route(
                body="User-agent: *\nAllow: /prive/contact\nDisallow: /prive\n"
            ),
        }
    )
    assert cache.can_fetch("https://site.fr/prive/contact")
    assert not cache.can_fetch("https://site.fr/prive/annuaire")
    assert cache.can_fetch("https://site.fr/")
