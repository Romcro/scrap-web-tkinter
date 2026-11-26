"""Tests des fonctions de l'interface des étapes 5 et 6 : import, export, paramètres, tri,
filtre, copie, ouverture de la page source, confirmations."""

from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.models import EmailResult, Event, Settings
from app.ui import main_window
from app.ui.main_window import MainWindow
from tests.fakes import Route, page
from tests.test_main_window import NOW, Dialogs, make_window, pump_until, type_urls


def result(email: str, site: str = "a.fr", minutes: int = 0) -> EmailResult:
    return EmailResult(
        email, site, f"https://{site}/contact", NOW + timedelta(minutes=minutes), "regex"
    )


def fill(window: MainWindow, *results: EmailResult) -> None:
    for item in results:
        window.handle_event(Event("email", item))


def emails(window: MainWindow) -> list[str]:
    return [r.email for r in window.table.visible_results()]


# --- tri -----------------------------------------------------------------------------


def test_sort_by_column_and_reverse(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    fill(window, result("b@a.fr", minutes=2), result("C@a.fr", minutes=0), result("a@a.fr", 1))
    table = window.table
    table.sort_by("email")
    assert emails(window) == ["a@a.fr", "b@a.fr", "C@a.fr"]  # sans tenir compte des majuscules
    assert table.tree.heading("email", "text") == "E-mail ▲"
    table.sort_by("email")
    assert emails(window) == ["C@a.fr", "b@a.fr", "a@a.fr"]
    assert table.tree.heading("email", "text") == "E-mail ▼"
    table.sort_by("date")
    assert emails(window) == ["C@a.fr", "a@a.fr", "b@a.fr"]
    assert table.tree.heading("email", "text") == "E-mail"


@pytest.mark.parametrize("descending", [False, True])
def test_new_results_keep_sort_order(root: tk.Toplevel, descending: bool) -> None:
    window = make_window(root, {})
    fill(window, result("d@a.fr"), result("b@a.fr"))
    window.table.sort_by("email")
    if descending:
        window.table.sort_by("email")
    fill(window, result("c@a.fr"), result("a@a.fr"), result("e@a.fr"))
    expected = ["a@a.fr", "b@a.fr", "c@a.fr", "d@a.fr", "e@a.fr"]
    assert emails(window) == (expected[::-1] if descending else expected)


# --- filtre --------------------------------------------------------------------------


def test_filter_and_counter(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    fill(window, result("contact@a.fr"), result("info@b.fr", "b.fr"), result("rh@a.fr"))
    assert window.result_count_var.get() == "3 résultats"
    window.filter_var.set("B.FR")
    assert emails(window) == ["info@b.fr"]
    assert window.result_count_var.get() == "3 résultats · 1 affiché"
    fill(window, result("compta@b.fr", "b.fr"), result("x@c.fr", "c.fr"))
    assert emails(window) == ["info@b.fr", "compta@b.fr"]
    window.filter_var.set("")
    assert len(emails(window)) == 5


def test_filter_on_source_page(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    fill(window, result("a@a.fr"))
    window.filter_var.set("/contact")
    assert emails(window) == ["a@a.fr"]
    window.filter_var.set("mentions")
    assert emails(window) == []


# --- copie et ouverture --------------------------------------------------------------


def test_copy_selection(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    fill(window, result("a@a.fr"), result("b@a.fr"), result("c@a.fr"))
    window.copy_selection()
    assert dialogs.kinds() == ["showinfo"]  # rien de sélectionné

    tree = window.table.tree
    tree.selection_set([tree.get_children()[0], tree.get_children()[2]])
    window.copy_selection()
    assert root.clipboard_get() == "a@a.fr\nc@a.fr"
    assert window.status_var.get() == "2 adresses copiée(s)."

    window.table.select_all()
    window.copy_selection()
    assert root.clipboard_get() == "a@a.fr\nb@a.fr\nc@a.fr"


def test_open_source_page(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(main_window.webbrowser, "open", opened.append)
    window = make_window(root, {})
    fill(window, result("a@a.fr"))
    window.table._open(window.table.tree.get_children()[0])
    window.open_source_page(EmailResult("x@y.fr", "y.fr", "javascript:alert(1)", NOW, "regex"))
    assert opened == ["https://a.fr/contact"]


# --- import --------------------------------------------------------------------------


def test_import_appends_to_list(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Dialogs(monkeypatch)
    path = tmp_path / "communes.csv"
    path.write_text("commune;url\nA;a.fr\nB;b.fr\n", encoding="utf-8")
    monkeypatch.setattr(main_window.filedialog, "askopenfilename", lambda **_k: str(path))
    window = make_window(root, {})
    type_urls(window, "deja.fr")
    window.import_urls()
    assert window.url_text.get("1.0", "end-1c") == "deja.fr\na.fr\nb.fr"
    assert window.url_count_var.get() == "3 sites valides"
    assert window.status_var.get() == "2 lignes importée(s) depuis communes.csv."


def test_import_errors(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    chosen = {"path": ""}
    monkeypatch.setattr(main_window.filedialog, "askopenfilename", lambda **_k: chosen["path"])
    window.import_urls()  # annulé
    assert dialogs.calls == []
    chosen["path"] = str(tmp_path / "liste.pdf")
    window.import_urls()
    empty = tmp_path / "vide.txt"
    empty.write_text("\n\n", encoding="utf-8")
    chosen["path"] = str(empty)
    window.import_urls()
    assert dialogs.kinds() == ["showerror", "showwarning"]


# --- export --------------------------------------------------------------------------


@pytest.mark.parametrize("export_format", ["csv", "xlsx"])
def test_export_visible_results(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, export_format: str
) -> None:
    Dialogs(monkeypatch)
    target = tmp_path / f"emails.{export_format}"
    seen: dict[str, object] = {}

    def ask(**kwargs: object) -> str:
        seen.update(kwargs)
        return str(target)

    monkeypatch.setattr(main_window.filedialog, "asksaveasfilename", ask)
    window = make_window(root, {}, export_dir=tmp_path / "exports")
    fill(window, result("a@a.fr"), result("b@b.fr", "b.fr"))
    window.filter_var.set("a.fr")
    window.export(export_format)  # type: ignore[arg-type]

    assert seen["initialdir"] == str(tmp_path / "exports")
    assert str(seen["initialfile"]).endswith(f".{export_format}")
    if export_format == "csv":
        lines = target.read_text("utf-8-sig").splitlines()
        assert len(lines) == 2 and lines[1].startswith("a@a.fr;")
    else:
        sheet = load_workbook(target).active
        assert sheet is not None and sheet.max_row == 2
    assert window.status_var.get() == f"1 e-mail exporté(s) dans {target}"
    assert window._unsaved_results  # export partiel (filtre) : il reste des résultats


def test_full_export_clears_unsaved_flag(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dialogs = Dialogs(monkeypatch, answer=False)
    monkeypatch.setattr(
        main_window.filedialog, "asksaveasfilename", lambda **_k: str(tmp_path / "e.csv")
    )
    window = make_window(root, {})
    fill(window, result("a@a.fr"))
    window.on_close()
    assert dialogs.kinds() == ["askyesno"]  # résultats non exportés
    assert root.winfo_exists()
    window.export("csv")
    window.on_close()
    assert dialogs.kinds() == ["askyesno"]  # pas de nouvelle question
    assert not root.winfo_exists()


def test_export_errors(root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    window.export("csv")
    assert dialogs.calls[-1] == ("showinfo", "Aucun résultat à exporter.")

    fill(window, result("a@a.fr"))
    monkeypatch.setattr(
        main_window.filedialog, "asksaveasfilename", lambda **_k: str(tmp_path / "e.csv")
    )

    def locked(*_args: object) -> int:
        raise PermissionError("verrouillé")

    monkeypatch.setattr(main_window, "export_csv", locked)
    window.export("csv")
    kind, message = dialogs.calls[-1]
    assert kind == "showerror" and "ouvert dans Excel" in message


# --- paramètres ----------------------------------------------------------------------


def test_settings_dialog_saves_and_persists(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Dialogs(monkeypatch)
    settings_path = tmp_path / "config" / "settings.json"
    window = make_window(root, {}, settings_path=settings_path)
    window.depth_var.set("3")
    dialog = window.open_settings()
    assert dialog is not None
    assert dialog.number_vars["max_depth"].get() == "3"  # reprend la saisie de la fenêtre
    dialog.number_vars["delay_seconds"].set("2,5")
    dialog.number_vars["max_pages_per_site"].set("80")
    dialog.bool_vars["include_subdomains"].set(True)
    dialog.user_agent_var.set("Outil/1.0 (+moi@exemple-reel.fr)")
    dialog.save()

    settings = window.controller.settings
    assert (settings.max_depth, settings.max_pages_per_site, settings.delay_seconds) == (3, 80, 2.5)
    assert settings.include_subdomains
    assert window.pages_var.get() == "80"
    assert json.loads(settings_path.read_text("utf-8"))["delay_seconds"] == 2.5
    assert window.status_var.get() == "Paramètres enregistrés."
    assert not dialog.winfo_exists()


def test_settings_dialog_rejects_invalid_values(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs = Dialogs(monkeypatch)
    window = make_window(root, {})
    window.controller.settings = Settings()  # les tests utilisent sinon un délai de 0 s
    dialog = window.open_settings()
    assert dialog is not None
    dialog.number_vars["timeout_seconds"].set("abc")
    dialog.save()
    dialog.number_vars["timeout_seconds"].set("500")
    dialog.save()
    assert [message for _, message in dialogs.calls] == [
        "« Délai max d'une requête (s) » doit être un nombre.",
        "Le délai maximal d'une requête doit être compris entre 1 et 120.",
    ]
    assert dialog.winfo_exists()
    assert window.controller.settings.timeout_seconds == 10
    dialog.cancel()


def test_disabling_robots_requires_confirmation(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs = Dialogs(monkeypatch, answer=False)
    window = make_window(root, {})
    window.controller.settings = Settings()
    dialog = window.open_settings()
    assert dialog is not None
    dialog.bool_vars["respect_robots"].set(False)
    dialog.save()
    assert dialogs.kinds() == ["askyesno"]
    assert window.controller.settings.respect_robots
    dialog.cancel()


def test_reset_defaults_keeps_custom_user_agent(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    window.controller.settings = Settings(max_depth=5, user_agent="Outil (+moi@reel.fr)")
    window.depth_var.set("5")
    dialog = window.open_settings()
    assert dialog is not None
    dialog.reset_defaults()
    assert dialog.number_vars["max_depth"].get() == "2"
    assert dialog.user_agent_var.get() == "Outil (+moi@reel.fr)"
    dialog.cancel()


# --- démarrage -----------------------------------------------------------------------


def test_start_saves_limits_and_warns_about_placeholder_contact(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    Dialogs(monkeypatch)
    settings_path = tmp_path / "settings.json"
    window = make_window(
        root, {"https://a.fr": Route(body=page("x@a.fr"))}, settings_path=settings_path
    )
    window.controller.settings = Settings(delay_seconds=0.5, respect_robots=False)
    type_urls(window, "a.fr")
    window.pages_var.set("7")
    window.start()
    assert window.open_settings() is None  # indisponible pendant le traitement
    pump_until(root, lambda: not window._running)
    assert json.loads(settings_path.read_text("utf-8"))["max_pages_per_site"] == 7
    assert "indiquez votre contact dans Outils > Paramètres" in window.log_panel.get_text()


def test_new_run_mentions_unexported_results(
    root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
) -> None:
    dialogs = Dialogs(monkeypatch, answer=False)
    window = make_window(root, {})
    fill(window, result("a@a.fr"))
    type_urls(window, "a.fr")
    window.start()
    assert "sans avoir été exportés" in dialogs.calls[-1][1]


def test_found_at_column_format(root: tk.Toplevel) -> None:
    window = make_window(root, {})
    fill(
        window, EmailResult("a@a.fr", "a.fr", "https://a.fr", datetime(2026, 1, 2, 3, 4), "mailto")
    )
    values = window.table.tree.item(window.table.tree.get_children()[0], "values")
    assert values[3:] == ("mailto", "02/01/2026 03:04")
