"""Tests de la normalisation et de la comparaison des URL."""

import pytest

from app.core.url_utils import (
    has_skipped_extension,
    is_priority_url,
    is_same_site,
    normalize_input_url,
    normalize_input_urls,
    normalize_url,
    priority_score,
    resolve_link,
    site_label,
)

# --- normalisation -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://Site.FR/contact/#formulaire", "https://site.fr/contact"),
        ("https://site.fr/", "https://site.fr"),
        ("https://site.fr", "https://site.fr"),
        ("https://site.fr:443/page", "https://site.fr/page"),
        ("http://site.fr:80/page", "http://site.fr/page"),
        ("https://site.fr:8443/page", "https://site.fr:8443/page"),
        ("https://site.fr/liste?page=2#haut", "https://site.fr/liste?page=2"),
        ("https://site.fr/Contact", "https://site.fr/Contact"),
    ],
)
def test_normalize_url(url: str, expected: str) -> None:
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("site.fr", "https://site.fr"),
        ("  www.Site.fr/  ", "https://www.site.fr"),
        ("http://site.fr", "http://site.fr"),
        ("https://site.fr/contact", "https://site.fr/contact"),
        ("", None),
        ("   ", None),
        ("# commentaire", None),
        ("ftp://site.fr", None),
        ("pas une url", None),
        ("motsansdomaine", None),
        ("https://site.fr:abc", None),
    ],
)
def test_normalize_input_url(raw: str, expected: str | None) -> None:
    assert normalize_input_url(raw) == expected


def test_normalize_input_urls_removes_empty_lines_and_duplicates() -> None:
    lines = ["site.fr", "", "https://site.fr/", "www.site.fr", "  autre.com  ", "site.fr/contact"]
    assert normalize_input_urls(lines) == [
        "https://site.fr",
        "https://autre.com",
        "https://site.fr/contact",
    ]


# --- même site -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "base", "expected"),
    [
        ("https://www.site.fr/contact", "https://site.fr", True),
        ("https://site.fr/contact", "https://www.site.fr", True),
        ("http://site.fr/page", "https://site.fr", True),
        ("https://blog.site.fr", "https://site.fr", False),
        ("https://autre.fr", "https://site.fr", False),
        ("https://site.fr.pirate.com", "https://site.fr", False),
        ("pas-une-url", "https://site.fr", False),
    ],
)
def test_is_same_site(url: str, base: str, expected: bool) -> None:
    assert is_same_site(url, base) is expected


@pytest.mark.parametrize(
    ("url", "base", "expected"),
    [
        ("https://blog.site.fr", "https://site.fr", True),
        ("https://a.site.co.uk", "https://b.site.co.uk", True),
        ("https://a.co.uk", "https://b.co.uk", False),
        ("https://site.fr.pirate.com", "https://site.fr", False),
    ],
)
def test_is_same_site_with_subdomains(url: str, base: str, expected: bool) -> None:
    assert is_same_site(url, base, include_subdomains=True) is expected


def test_site_label() -> None:
    assert site_label("https://www.Site.fr/contact") == "site.fr"


# --- liens ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/contact/", "https://site.fr/contact"),
        ("equipe.html", "https://site.fr/rubrique/equipe.html"),
        ("?page=2", "https://site.fr/rubrique/page?page=2"),
        ("//www.site.fr/a-propos#top", "https://www.site.fr/a-propos"),
        ("https://autre.com/x", "https://autre.com/x"),
        ("#haut", None),
        ("javascript:void(0)", None),
        ("JavaScript:ouvrir()", None),
        ("mailto:info@site.fr", None),
        ("tel:+33123456789", None),
        ("data:text/html,bonjour", None),
        ("ftp://site.fr/fichier", None),
        ("/docs/plaquette.pdf", None),
        ("/img/LOGO.PNG", None),
        ("/media/video.mp4?v=2", None),
        ("", None),
    ],
)
def test_resolve_link(href: str, expected: str | None) -> None:
    assert resolve_link(href, "https://site.fr/rubrique/page") == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://site.fr/fichier.ZIP", True),
        ("https://site.fr/style.css", True),
        ("https://site.fr/page.html", False),
        ("https://site.fr/page.php?id=3", False),
        ("https://site.fr/contact", False),
        ("https://site.fr/version-2.0", False),
    ],
)
def test_has_skipped_extension(url: str, expected: bool) -> None:
    assert has_skipped_extension(url) is expected


# --- priorisation --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://site.fr/contact",
        "https://site.fr/nous-contacter",
        "https://site.fr/mentions_legales",
        "https://site.fr/Mentions-Legales",
        "https://site.fr/qui-sommes-nous",
        "https://site.fr/a-propos",
        "https://site.fr/%C3%A9quipe",
        "https://site.fr/en/team",
        "https://site.de/impressum",
        "https://site.fr/index.php?page=contact",
    ],
)
def test_priority_urls(url: str) -> None:
    assert is_priority_url(url)


def test_non_priority_url() -> None:
    assert not is_priority_url("https://site.fr/blog/article-1")


def test_priority_score_sorts_contact_pages_first() -> None:
    urls = [
        "https://site.fr/blog",
        "https://site.fr/contact",
        "https://site.fr/produits",
        "https://site.fr/mentions-legales",
    ]
    assert sorted(urls, key=priority_score) == [
        "https://site.fr/contact",
        "https://site.fr/mentions-legales",
        "https://site.fr/blog",
        "https://site.fr/produits",
    ]
