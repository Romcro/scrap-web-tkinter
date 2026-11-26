"""Tests de la fenêtre principale (fenêtre Tkinter réelle mais cachée, réseau simulé)."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest

from app.core.controller import ScraperController
from app.models import CrawlStats, EmailResult, Event, LogMessage, RunSummary, Settings
from app.ui import main_window
from app.ui.main_window import MainWindow, format_duration, format_stats
from tests.fakes import FakeSession, Route, RouteSpec, page

NOW = datetime(2026, 11, 26, 12, 0, 0)
FAST = Settings(delay_seconds=0, respect_robots=False, max_workers=2)


class Dialogs:
    """Remplace les boîtes de dialogue et mémorise les appels."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, answer: bool = True) -> None:
        self.calls: list[tuple[str, str]] = []
        self.answer = answer
        for name in ("showwarning", "showerror", "showinfo"):
            monkeypatch.setattr(main_window.messagebox, name, self._recorder(name))
        monkeypatch.setattr(main_window.messagebox, "askyesno", self._ask)

    def _recorder(self, name: str) -> Callable[..., None]:
        def record(_title: str, message: str, **_kwargs: Any) -> None:
            self.calls.append((name, message))

        return record

    def _ask(self, _title: str, message: str, **_kwargs: Any) -> bool:
        self.calls.append(("askyesno", message))
        return self.answer

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.calls]


def make_window(root: tk.Toplevel, routes: dict[str, RouteSpec], **kwargs: Any) -> MainWindow:
    controller = ScraperController(
        FAST, session_factory=lambda _s: FakeSession(routes), now=lambda: NOW
    )
    return MainWindow(root, controller, **kwargs)


def pump_until(root: tk.Misc, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("condition non atteinte à temps")
        root.update()
        time.sleep(0.01)


def type_urls(window: MainWindow, text: str) -> None:
    window.url_text.insert("1.0", text)
    window.root.update()


def disabled(widget: Any) -> bool:
    return "disabled" in widget.state()


# --- formatage -----------------------------------------------------------------------


def test_format_helpers() -> None:
    assert format_duration(42.4) == "42 s"
    assert format_duration(125) == "2 min 05 s"
    assert format_stats(CrawlStats(30, 12, 340, 87, 0)) == "12/30 sites · 340 pages · 87 e-mails"
    assert format_stats(CrawlStats(1, 1, 3, 0, 2)).endswith(" · 2 erreurs")


# --- état initial et saisie ----------------------------------------------------------


def test_initial_state(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    assert not disabled(window.start_button)
    assert disabled(window.stop_button)
    assert window.url_count_var.get() == "Aucun site valide"
    assert window.depth_var.get() == "2"
    assert window.pages_var.get() == "50"


def test_valid_site_counter(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    type_urls(window, "site.fr\nwww.site.fr\n\npas une url\nautre.com\n")
    assert window.url_count_var.get() == "2 sites valides"
    window.clear_urls()
    assert window.url_count_var.get() == "Aucun site valide"


def test_start_without_valid_url_warns(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    type_urls(window, "pas une url")
    window.start()
    assert dialogs.kinds() == ["showwarning"]
    assert not window.controller.is_running


@pytest.mark.parametrize(("depth", "pages"), [("abc", "50"), ("11", "50"), ("2", "0"), ("2", "")])
def test_invalid_limits_are_refused(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, depth: str, pages: str
) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    type_urls(window, "site.fr")
    window.depth_var.set(depth)
    window.pages_var.set(pages)
    window.start()
    assert dialogs.kinds() == ["showerror"]
    assert not window.controller.is_running


# --- traitement complet --------------------------------------------------------------


def test_full_run_fills_table_and_log(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> None:
    Dialogs(monkeypatch)
    window = make_window(
        root,
        {
            "https://a.fr": Route(body=page("contact@a.fr", ["/contact"])),
            "https://a.fr/contact": Route(body=page("direction [at] a [dot] fr")),
            "https://b.fr": Route(body=page(links=["mailto:info@b.fr"])),
        },
    )
    type_urls(window, "a.fr\nb.fr")
    window.depth_var.set("1")
    window.start()
    assert disabled(window.start_button)
    assert str(window.url_text.cget("state")) == "disabled"

    pump_until(root, lambda: not window._running)

    assert {r.email for r in window.table.results} == {
        "contact@a.fr",
        "direction@a.fr",
        "info@b.fr",
    }
    assert len(window.table.tree.get_children()) == 3
    assert window.progress_var.get() == "2/2 sites · 3 pages · 3 e-mails"
    assert window.status_var.get().startswith("Terminé en ")
    assert "Démarrage : 2 site(s) à traiter." in window.log_panel.get_text()
    assert window.controller.settings.max_depth == 1
    assert not disabled(window.start_button)
    assert disabled(window.stop_button)
    assert str(window.url_text.cget("state")) == "normal"


def test_new_run_asks_before_clearing_results(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs = Dialogs(monkeypatch, answer=False)
    window = make_window(root, {})
    window.handle_event(Event("email", EmailResult("x@a.fr", "a.fr", "https://a.fr", NOW, "regex")))
    type_urls(window, "a.fr")
    window.start()
    assert dialogs.kinds() == ["askyesno"]
    assert len(window.table) == 1
    assert not window.controller.is_running


def test_stop_button(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> None:
    Dialogs(monkeypatch)
    served = threading.Event()

    def home() -> Route:
        served.set()
        return Route(body=page("contact@a.fr", ["/a", "/b"]))

    window = make_window(root, {"https://a.fr": home})
    window.controller.settings = Settings(delay_seconds=30, respect_robots=False)
    type_urls(window, "a.fr")
    window.start()
    assert served.wait(5)
    window.stop()
    assert disabled(window.stop_button)
    pump_until(root, lambda: not window._running, timeout=3)
    assert window.status_var.get() == "Arrêté par l'utilisateur. 1 e-mail trouvé(s)."


# --- affichage des événements --------------------------------------------------------


def test_events_update_widgets(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    window.handle_event(
        Event("email", EmailResult("x@a.fr", "a.fr", "https://a.fr/c", NOW, "obfuscated"))
    )
    window.handle_event(Event("log", LogMessage("WARN", "a.fr : délai dépassé", NOW)))
    window.handle_event(Event("progress", CrawlStats(4, 1, 10, 1, 1)))
    row = window.table.tree.item(window.table.tree.get_children()[0], "values")
    assert list(row) == ["x@a.fr", "a.fr", "https://a.fr/c", "masqué", "26/11/2026 12:00"]
    assert "12:00:00  [WARN ]  a.fr : délai dépassé" in window.log_panel.get_text()
    assert window.progress_var.get() == "1/4 sites · 10 pages · 1 e-mails · 1 erreur"
    window.handle_event(Event("done", RunSummary(CrawlStats(4, 4, 20, 1, 1), False, 125)))
    assert window.status_var.get() == "Terminé en 2 min 05 s. 1 e-mail trouvé(s)."


def test_log_panel_toggle_and_limit(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    panel = window.log_panel
    panel.toggle()
    assert not panel.expanded
    panel.toggle()
    assert panel.expanded
    for i in range(panel.MAX_LINES + 50):
        panel.append(LogMessage("INFO", f"ligne {i}", NOW))
    lines = panel.get_text().splitlines()
    assert len(lines) == panel.MAX_LINES
    assert lines[-1].endswith(f"ligne {panel.MAX_LINES + 49}")


# --- fermeture -----------------------------------------------------------------------


def test_close_while_running_can_be_cancelled(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs = Dialogs(monkeypatch, answer=False)
    gate = threading.Event()

    def slow() -> Route:
        gate.wait(5)
        return Route(body=page())

    window = make_window(root, {"https://a.fr": slow})
    type_urls(window, "a.fr")
    window.start()
    try:
        window.on_close()
        assert dialogs.kinds() == ["askyesno"]
        assert window.controller.is_running
    finally:
        gate.set()
    pump_until(root, lambda: not window._running)


def test_close_while_running_stops_then_closes(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    Dialogs(monkeypatch, answer=True)
    served = threading.Event()

    def home() -> Route:
        served.set()
        return Route(body=page(links=["/a"]))

    window = make_window(root, {"https://a.fr": home})
    window.controller.settings = Settings(delay_seconds=30, respect_robots=False)
    type_urls(window, "a.fr")
    window.start()
    assert served.wait(5)
    window.on_close()
    pump_until(root.master, lambda: not root.winfo_exists(), timeout=3)
    assert not window.controller.is_running
