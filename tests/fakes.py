"""Substituts de test : session HTTP simulée et horloge simulée (aucun accès réseau)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import requests
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers

HTML = {"Content-Type": "text/html; charset=utf-8"}


@dataclass
class Route:
    """Réponse simulée pour une URL."""

    status: int = 200
    body: str | bytes = ""
    headers: dict[str, str] = field(default_factory=lambda: dict(HTML))
    final_url: str | None = None  # URL finale après redirection


# Une route peut aussi être une fonction appelée au moment de la requête
# (pour déclencher un arrêt, synchroniser des threads…).
RouteSpec = Route | list[Route] | Exception | Callable[[], "Route | Exception"]


def page(text: str = "", links: tuple[str, ...] | list[str] = (), head: str = "") -> str:
    """Construit une page HTML minimale avec du texte et des liens."""
    anchors = "".join(f'<a href="{link}">lien</a> ' for link in links)
    return f"<html><head>{head}</head><body><p>{text}</p>{anchors}</body></html>"


class FakeSession:
    """Session HTTP simulée : répond selon `routes`, 404 pour les URL inconnues."""

    def __init__(self, routes: dict[str, RouteSpec]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get(self, url: str, *, timeout: float, allow_redirects: bool = True) -> requests.Response:
        self.calls.append(url)
        spec = self.routes.get(url, Route(status=404, body="introuvable"))
        if callable(spec):
            spec = spec()
        if isinstance(spec, Exception):
            raise spec
        route = spec if isinstance(spec, Route) else (spec.pop(0) if len(spec) > 1 else spec[0])
        body = route.body
        response = requests.Response()
        response.status_code = route.status
        response._content = body.encode("utf-8") if isinstance(body, str) else body
        response.headers = CaseInsensitiveDict(route.headers)
        response.url = route.final_url or url
        response.encoding = get_encoding_from_headers(response.headers)
        return response

    @property
    def page_calls(self) -> list[str]:
        """Requêtes hors robots.txt."""
        return [url for url in self.calls if not url.endswith("/robots.txt")]


class FakeClock:
    """Horloge simulée : `sleep` avance le temps au lieu d'attendre."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds
