"""Fixtures partagées : fenêtres Tkinter de test."""

from __future__ import annotations

import contextlib
import gc
import tkinter as tk
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session")
def tk_app() -> Iterator[tk.Tk]:
    """Une seule racine Tk pour toute la session : sous Windows, créer et détruire beaucoup
    de Tk() dans un même processus échoue parfois (« Can't find a usable tk.tcl »)."""
    try:
        app = tk.Tk()
    except tk.TclError as exc:  # pas d'affichage disponible
        pytest.skip(f"Tkinter indisponible : {exc}")
    app.withdraw()
    yield app
    app.destroy()
    del app
    gc.collect()


@pytest.fixture
def root(tk_app: tk.Tk) -> Iterator[tk.Toplevel]:
    """Fenêtre de test (cachée), détruite après chaque test."""
    window = tk.Toplevel(tk_app)
    window.withdraw()
    yield window
    with contextlib.suppress(tk.TclError):  # déjà fermée par le test
        window.destroy()
    # Les objets Tkinter doivent être libérés dans le thread principal : sinon le ramasse-miettes
    # peut les détruire depuis un thread de crawl d'un test suivant.
    del window
    gc.collect()
