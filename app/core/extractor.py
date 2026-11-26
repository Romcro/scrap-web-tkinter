"""Extraction et nettoyage des adresses e-mail contenues dans une page HTML."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from app.core.filters import OBFUSCATION_STOPWORDS, is_excluded_email
from app.models import EmailMethod

# --- Expressions régulières ---------------------------------------------------------

_LOCAL = r"[A-Za-z0-9._%+\-]+"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
_TLD = r"[A-Za-z]{2,}"
_DOMAIN = rf"(?:{_LABEL}\.)+{_TLD}"
_BEFORE = r"(?<![A-Za-z0-9._%+\-])"
_AFTER = r"(?![A-Za-z0-9\-])"

EMAIL_RE = re.compile(rf"{_BEFORE}{_LOCAL}@{_DOMAIN}{_AFTER}")
EMAIL_FULL_RE = re.compile(rf"{_LOCAL}@{_DOMAIN}")

# Formes obfusquées : « nom [at] domaine [dot] fr », « nom(at)domaine.fr »,
# « nom arobase domaine point fr »…
_OPEN = r"[\[\(\{<]"
_CLOSE = r"[\]\)\}>]"
_AT = rf"(?:\s*{_OPEN}\s*(?:at|arobase|@)\s*{_CLOSE}\s*|\s+arobase\s+)"
_STOPWORDS = "|".join(re.escape(word) for word in OBFUSCATION_STOPWORDS)
# « point » en toutes lettres, sauf s'il est suivi d'un mot courant (« point de vente »).
_WORD_DOT = rf"\s+(?:dot|point)\s+(?!(?:{_STOPWORDS})\b)"
_DOT = rf"(?:\s*{_OPEN}\s*(?:dot|point|\.)\s*{_CLOSE}\s*|{_WORD_DOT}|\.)"
OBFUSCATED_RE = re.compile(
    rf"{_BEFORE}({_LOCAL}){_AT}((?:{_LABEL}{_DOT})+{_TLD}){_AFTER}", re.IGNORECASE
)
_DOT_TOKEN_RE = re.compile(_DOT, re.IGNORECASE)

# Ponctuation parasite collée à une adresse dans un texte.
_LEADING_PUNCTUATION = "(<[{'\"«"
_TRAILING_PUNCTUATION = ".,;:!?)>]}'\"»"

# Balises dont le contenu n'est pas du texte visible.
_INVISIBLE_TAGS = ("script", "style", "noscript", "template")

# Données structurées (schema.org) : <script type="application/ld+json">{"email": …}</script>
_JSON_LD_TYPE = "application/ld+json"
_JSON_LD_EMAIL_KEY = "email"
_JSON_MAX_DEPTH = 30


@dataclass(frozen=True)
class ExtractedEmail:
    """Adresse extraite d'une page, avec la méthode qui l'a trouvée."""

    email: str
    method: EmailMethod


def clean_email(raw: str) -> str | None:
    """Nettoie une adresse candidate ; None si elle est invalide ou est un faux positif.

    Décode les entités HTML, retire « mailto: » et la ponctuation en bordure,
    passe en minuscules.
    """
    candidate = html.unescape(raw).strip()
    if candidate.lower().startswith("mailto:"):
        candidate = candidate[len("mailto:") :]
    candidate = candidate.lstrip(_LEADING_PUNCTUATION).rstrip(_TRAILING_PUNCTUATION).lower()
    if not EMAIL_FULL_RE.fullmatch(candidate) or is_excluded_email(candidate):
        return None
    return candidate


def _mailto_candidates(soup: BeautifulSoup) -> Iterator[str]:
    """Adresses brutes des liens « mailto: » (décodage %40, sans ?subject=…)."""
    for tag in soup.find_all(["a", "area"]):
        if not isinstance(tag, Tag):
            continue
        href = tag.get("href")
        if not isinstance(href, str) or not href.strip().lower().startswith("mailto:"):
            continue
        target = unquote(href.strip()[len("mailto:") :]).split("?", 1)[0]
        yield from re.split(r"[,;]", target)


def _json_ld_candidates(soup: BeautifulSoup) -> Iterator[str]:
    """Adresses déclarées dans les blocs JSON-LD (clés « email », à toute profondeur).

    Si le JSON est mal formé (fréquent), les adresses sont cherchées dans le texte du bloc.
    """
    for tag in soup.find_all("script"):
        if not isinstance(tag, Tag):
            continue
        script_type = tag.get("type")
        if not isinstance(script_type, str) or script_type.strip().lower() != _JSON_LD_TYPE:
            continue
        text = tag.get_text()
        try:
            data = json.loads(text)
        except ValueError:
            yield from (match.group(0) for match in EMAIL_RE.finditer(text))
            continue
        yield from _emails_in_json(data, 0)


def _emails_in_json(node: object, depth: int) -> Iterator[str]:
    if depth > _JSON_MAX_DEPTH:
        return
    if isinstance(node, list):
        for item in node:
            yield from _emails_in_json(item, depth + 1)
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and key.lower() == _JSON_LD_EMAIL_KEY:
                values = value if isinstance(value, list) else [value]
                yield from (v for v in values if isinstance(v, str))
            else:
                yield from _emails_in_json(value, depth + 1)


def _deobfuscate(match: re.Match[str]) -> str:
    """Reconstitue une adresse à partir d'une forme obfusquée."""
    return f"{match.group(1)}@{_DOT_TOKEN_RE.sub('.', match.group(2))}"


def _visible_text(soup: BeautifulSoup) -> str:
    """Texte visible de la page (sans scripts ni styles)."""
    for tag in soup.find_all(_INVISIBLE_TAGS):
        if isinstance(tag, Tag):
            tag.decompose()
    return soup.get_text(" ")


def extract_emails_from_text(text: str) -> list[ExtractedEmail]:
    """Extrait les adresses d'un texte brut : forme classique puis formes obfusquées."""
    found: dict[str, ExtractedEmail] = {}
    candidates: list[tuple[str, EmailMethod]] = [
        (m.group(0), "regex") for m in EMAIL_RE.finditer(text)
    ]
    candidates += [(_deobfuscate(m), "obfuscated") for m in OBFUSCATED_RE.finditer(text)]
    for raw, method in candidates:
        email = clean_email(raw)
        if email is not None and email not in found:
            found[email] = ExtractedEmail(email, method)
    return list(found.values())


def extract_emails(page_html: str | bytes) -> list[ExtractedEmail]:
    """Extrait les adresses d'une page HTML (texte, ou octets bruts dont l'encodage est détecté)."""
    return extract_emails_from_soup(BeautifulSoup(page_html, "lxml"))


def extract_emails_from_soup(soup: BeautifulSoup) -> list[ExtractedEmail]:
    """Extrait les adresses d'une page déjà analysée, sans doublon.

    Ordre de fiabilité : liens mailto, données structurées JSON-LD, texte visible, formes
    obfusquées. Une adresse trouvée par plusieurs méthodes garde la plus fiable.
    Les autres scripts sont ignorés (nombreux faux positifs : Sentry, Wix…).
    Attention : les balises invisibles (scripts, styles) sont retirées de `soup`.
    """
    found: dict[str, ExtractedEmail] = {}
    sources: tuple[tuple[Iterator[str], EmailMethod], ...] = (
        (_mailto_candidates(soup), "mailto"),
        (_json_ld_candidates(soup), "structured"),
    )
    for candidates, method in sources:
        for raw in candidates:
            email = clean_email(raw)
            if email is not None and email not in found:
                found[email] = ExtractedEmail(email, method)
    for item in extract_emails_from_text(_visible_text(soup)):
        found.setdefault(item.email, item)
    return list(found.values())
