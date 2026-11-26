"""Normalisation, comparaison de domaines et priorisation des URL."""

from __future__ import annotations

from collections.abc import Iterable
from posixpath import splitext
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import tldextract

from app.core.filters import PRIORITY_KEYWORDS, SKIPPED_URL_EXTENSIONS

ALLOWED_SCHEMES: tuple[str, ...] = ("http", "https")
IGNORED_LINK_PREFIXES: tuple[str, ...] = (
    "#",
    "javascript:",
    "mailto:",
    "tel:",
    "sms:",
    "data:",
    "ftp:",
    "file:",
)
_DEFAULT_PORTS: dict[str, int] = {"http": 80, "https": 443}

# Liste des suffixes publics embarquée dans le paquet : aucun accès réseau.
_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def normalize_url(url: str) -> str:
    """Normalise une URL absolue pour comparer les pages visitées.

    Schéma et hôte en minuscules, port par défaut retiré, fragment retiré,
    slash final supprimé. Lève ValueError si l'URL est invalide (port incorrect…).
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    if ":" in host:  # IPv6
        host = f"[{host}]"
    port = parts.port
    netloc = host if port is None or port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def host_key(url: str) -> str:
    """Retourne l'hôte de l'URL en minuscules, sans le préfixe « www. »."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


def site_label(url: str) -> str:
    """Libellé du site affiché à l'utilisateur (ex. : « site1.fr »)."""
    return host_key(url)


def registered_domain(host: str) -> str:
    """Domaine racine enregistré (ex. : « blog.site.co.uk » → « site.co.uk »)."""
    return _TLD_EXTRACT(host).top_domain_under_public_suffix


def is_same_site(url: str, base_url: str, *, include_subdomains: bool = False) -> bool:
    """Indique si `url` appartient au même site que `base_url`.

    « www. » est toujours ignoré. Les autres sous-domaines ne sont acceptés que si
    `include_subdomains` est vrai.
    """
    host, base_host = host_key(url), host_key(base_url)
    if not host or not base_host:
        return False
    if host == base_host:
        return True
    if include_subdomains:
        root = registered_domain(host)
        return root != "" and root == registered_domain(base_host)
    return False


def has_skipped_extension(url: str) -> bool:
    """Indique si l'URL pointe vers un fichier non HTML (.pdf, .jpg, .zip…)."""
    path = urlsplit(url).path.lower()
    return splitext(path)[1].lstrip(".") in SKIPPED_URL_EXTENSIONS


def resolve_link(href: str, base_url: str) -> str | None:
    """Transforme un lien trouvé dans une page en URL absolue normalisée.

    Retourne None pour les ancres, liens javascript:/mailto:/tel:, schémas non HTTP
    et fichiers non HTML.
    """
    href = href.strip()
    if not href or href.lower().startswith(IGNORED_LINK_PREFIXES):
        return None
    try:
        absolute = urljoin(base_url, href)
        parts = urlsplit(absolute)
        if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
            return None
        if has_skipped_extension(absolute):
            return None
        return normalize_url(absolute)
    except ValueError:
        return None


def normalize_input_url(raw: str) -> str | None:
    """Normalise une URL saisie par l'utilisateur ; None si la ligne est vide ou invalide.

    Ajoute « https:// » si le schéma est absent. Les lignes commençant par « # »
    sont des commentaires.
    """
    candidate = raw.strip()
    if not candidate or candidate.startswith("#") or any(c.isspace() for c in candidate):
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate.lstrip("/")
    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        if parts.scheme.lower() not in ALLOWED_SCHEMES or not host:
            return None
        if "." not in host and host != "localhost":
            return None
        return normalize_url(candidate)
    except ValueError:
        return None


def normalize_input_urls(lines: Iterable[str]) -> list[str]:
    """Normalise une liste d'URL saisies, en retirant lignes vides, invalides et doublons.

    « site.fr » et « www.site.fr » sont considérés comme le même site ; l'ordre
    de première apparition est conservé.
    """
    result: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        url = normalize_input_url(line)
        if url is None:
            continue
        parts = urlsplit(url)
        key = (host_key(url), parts.path, parts.query)
        if key not in seen:
            seen.add(key)
            result.append(url)
    return result


def is_priority_url(url: str) -> bool:
    """Indique si l'URL ressemble à une page de contact, mentions légales, équipe…"""
    parts = urlsplit(url)
    target = unquote(f"{parts.path}?{parts.query}").lower().replace("_", "-")
    return any(keyword in target for keyword in PRIORITY_KEYWORDS)


def priority_score(url: str) -> int:
    """Clé de tri pour la file de crawl : 0 = page prioritaire, 1 = page normale."""
    return 0 if is_priority_url(url) else 1
