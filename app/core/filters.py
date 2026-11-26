"""Listes d'exclusion et règles de détection des faux positifs.

Toutes les listes de ce module peuvent être modifiées sans toucher au reste du code.
"""

from __future__ import annotations

from collections.abc import Collection

# --- Limites de longueur (RFC 5321) -------------------------------------------------

MAX_EMAIL_LENGTH = 254
MAX_LOCAL_PART_LENGTH = 64

# --- Faux positifs sur les e-mails ---------------------------------------------------

# Une « adresse » dont la dernière extension est l'une de celles-ci est en fait un fichier
# (ex. : logo@2x.png).
FILE_LIKE_EXTENSIONS: frozenset[str] = frozenset(
    {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "bmp",
        "ico",
        "tif",
        "tiff",
        "avif",
        "css",
        "js",
        "mjs",
        "map",
        "json",
        "woff",
        "woff2",
        "ttf",
        "eot",
    }
)

# Domaines d'exemple ou techniques (les sous-domaines sont aussi exclus).
EXCLUDED_DOMAINS: frozenset[str] = frozenset(
    {
        "example.com",
        "example.org",
        "example.net",
        "example.fr",
        "exemple.com",
        "exemple.fr",
        "domain.com",
        "domaine.fr",
        "domaine.com",
        "email.com",
        "yourdomain.com",
        "votredomaine.fr",
        "votre-domaine.fr",
        "sentry.io",
        "wixpress.com",
        "sentry-next.wixpress.com",
    }
)

# Parties locales génériques non exploitables.
EXCLUDED_LOCAL_PARTS: frozenset[str] = frozenset(
    {"noreply", "no-reply", "no_reply", "donotreply", "do-not-reply", "do_not_reply"}
)

# Mots courants pouvant suivre « point » / « dot » dans une phrase (« point de vente ») :
# après un séparateur écrit en toutes lettres, ils ne sont pas pris pour une extension de
# domaine. Les formes entre crochets (« [dot] de ») ne sont pas concernées.
OBFUSCATION_STOPWORDS: tuple[str, ...] = (
    "de",
    "du",
    "des",
    "la",
    "le",
    "les",
    "et",
    "en",
    "au",
    "aux",
    "sur",
    "pour",
    "par",
    "avec",
    "ou",
    "of",
    "and",
    "in",
    "on",
    "to",
    "is",
    "the",
)

# --- Crawl --------------------------------------------------------------------------

# Extensions de fichiers non HTML à ne jamais télécharger.
SKIPPED_URL_EXTENSIONS: frozenset[str] = frozenset(
    {
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "odt",
        "ods",
        "odp",
        "rtf",
        "csv",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "svg",
        "webp",
        "bmp",
        "ico",
        "tif",
        "tiff",
        "avif",
        "zip",
        "rar",
        "7z",
        "gz",
        "tar",
        "bz2",
        "mp3",
        "mp4",
        "avi",
        "mov",
        "wmv",
        "webm",
        "wav",
        "ogg",
        "flv",
        "mkv",
        "css",
        "js",
        "mjs",
        "json",
        "xml",
        "rss",
        "atom",
        "woff",
        "woff2",
        "ttf",
        "eot",
        "otf",
        "exe",
        "msi",
        "dmg",
        "apk",
        "iso",
        "bin",
    }
)

# Mots-clés des pages à visiter en priorité (comparés au chemin de l'URL en minuscules,
# avec « _ » remplacé par « - »).
PRIORITY_KEYWORDS: tuple[str, ...] = (
    "contact",
    "mentions-legales",
    "mention-legale",
    "mentions-légales",
    "legal",
    "about",
    "a-propos",
    "à-propos",
    "apropos",
    "qui-sommes-nous",
    "equipe",
    "équipe",
    "team",
    "impressum",
    "coordonnees",
    "coordonnées",
)


def _matches_domain(domain: str, domains: Collection[str]) -> bool:
    """Indique si `domain` est l'un des `domains` ou l'un de leurs sous-domaines."""
    return any(domain == d or domain.endswith("." + d) for d in domains)


def is_excluded_email(
    email: str,
    *,
    excluded_domains: Collection[str] = EXCLUDED_DOMAINS,
    excluded_local_parts: Collection[str] = EXCLUDED_LOCAL_PARTS,
) -> bool:
    """Indique si une adresse (déjà nettoyée, en minuscules) est un faux positif à exclure."""
    local, sep, domain = email.rpartition("@")
    if not sep or not local or not domain:
        return True
    if len(email) > MAX_EMAIL_LENGTH or len(local) > MAX_LOCAL_PART_LENGTH:
        return True
    if local.startswith(".") or local.endswith(".") or ".." in local or ".." in domain:
        return True
    if domain.rsplit(".", 1)[-1] in FILE_LIKE_EXTENSIONS:
        return True
    if _matches_domain(domain, excluded_domains):
        return True
    return local in excluded_local_parts
