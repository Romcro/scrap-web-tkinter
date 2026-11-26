"""Fenêtre principale : saisie des sites, contrôle, progression, résultats et journal.

Règle : aucun appel réseau ici. Le travail est fait par ScraperController dans des
threads de fond ; la fenêtre lit sa file d'événements toutes les 100 ms (root.after).
"""

from __future__ import annotations

import logging
import queue
import time
import tkinter as tk
import webbrowser
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import TracebackType
from typing import Literal

from app import APP_NAME, __version__
from app.config import LIMITS, PLACEHOLDER_CONTACT, field_error, save_settings
from app.core.controller import ScraperController, group_by_site
from app.io.exporter import default_export_name, export_csv, export_xlsx
from app.io.importer import ImportFileError, read_url_file
from app.models import CrawlStats, EmailResult, Event, LogLevel, LogMessage, RunSummary, Settings
from app.ui.settings_dialog import SettingsDialog
from app.ui.widgets import LogPanel, ResultsTable

logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 100
MAX_EVENTS_PER_POLL = 500  # garde l'interface fluide même si beaucoup d'événements arrivent
CLOSE_GRACE_SECONDS = 3.0  # marge après le timeout réseau avant de forcer la fermeture

TEXT_BG_EDITABLE = "#ffffff"
TEXT_BG_READONLY = "#f0f0f0"

ExportFormat = Literal["csv", "xlsx"]
EXPORT_FILETYPES: dict[str, list[tuple[str, str]]] = {
    "csv": [("Fichier CSV (Excel)", "*.csv")],
    "xlsx": [("Classeur Excel", "*.xlsx")],
}
IMPORT_FILETYPES = [("Listes de sites", "*.txt *.csv"), ("Tous les fichiers", "*.*")]

LEGAL_NOTICE = (
    "Cet outil collecte des adresses e-mail publiées sur les sites que vous indiquez. "
    "Une adresse nominative est une donnée personnelle : le RGPD et les recommandations "
    "de la CNIL s'appliquent, même si l'adresse est publique.\n\n"
    "• Vérifiez les conditions générales d'utilisation des sites ciblés.\n"
    "• La prospection par e-mail de particuliers exige en principe leur consentement "
    "préalable. En B2B, elle est possible si le message concerne la fonction de la "
    "personne et qu'un droit d'opposition simple est proposé.\n"
    "• Informez les personnes, limitez la durée de conservation, tenez un registre de "
    "traitement et supprimez les données sur demande.\n\n"
    "Ce rappel n'est pas un avis juridique : en cas de doute, référez-vous aux fiches "
    "de la CNIL ou à un juriste."
)


def format_duration(seconds: float) -> str:
    """Durée lisible : « 45 s », « 2 min 05 s »."""
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    return f"{minutes} min {secs:02d} s"


def format_stats(stats: CrawlStats) -> str:
    """Texte du compteur de progression."""
    text = (
        f"{stats.sites_done}/{stats.sites_total} sites · {stats.pages_visited} pages · "
        f"{stats.emails_found} e-mails"
    )
    if stats.errors:
        text += f" · {stats.errors} erreur{'s' if stats.errors > 1 else ''}"
    return text


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count > 1 else ''}"


class MainWindow:
    """Fenêtre principale de l'application."""

    def __init__(
        self,
        root: tk.Tk | tk.Toplevel,
        controller: ScraperController | None = None,
        *,
        settings_path: Path | None = None,
        export_dir: Path | None = None,
    ) -> None:
        self.root = root
        self.controller = controller if controller is not None else ScraperController()
        self.settings_path = settings_path  # None : les paramètres ne sont pas enregistrés
        self.export_dir = export_dir if export_dir is not None else Path("exports")
        self._running = False
        self._closing = False
        self._unsaved_results = False  # des résultats n'ont pas encore été exportés
        self._poll_id: str | None = None

        root.title(APP_NAME)
        root.geometry("1100x760")
        root.minsize(820, 560)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if isinstance(root, tk.Tk):
            root.report_callback_exception = self._report_exception

        settings = self.controller.settings
        self.depth_var = tk.StringVar(root, value=str(settings.max_depth))
        self.pages_var = tk.StringVar(root, value=str(settings.max_pages_per_site))
        self.progress_var = tk.StringVar(root, value=format_stats(CrawlStats()))
        self.status_var = tk.StringVar(
            root, value="Prêt. Saisissez les sites puis cliquez sur Démarrer."
        )
        self.url_count_var = tk.StringVar(root)
        self.filter_var = tk.StringVar(root)
        self.result_count_var = tk.StringVar(root)

        self._build_menu()
        self._build_layout()
        self._bind_shortcuts()
        self.filter_var.trace_add("write", self._on_filter_changed)
        self._set_running(False)
        self._update_url_count()
        self._update_result_count()
        self.url_text.focus_set()
        self._poll_id = root.after(POLL_INTERVAL_MS, self._poll)

    # --- construction ---------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        self.file_menu = tk.Menu(menubar, tearoff=False)
        self.file_menu.add_command(
            label="Importer une liste…", command=self.import_urls, accelerator="Ctrl+O"
        )
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Exporter en CSV…", command=lambda: self.export("csv"), accelerator="Ctrl+S"
        )
        self.file_menu.add_command(label="Exporter en XLSX…", command=lambda: self.export("xlsx"))
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Quitter", command=self.on_close)
        menubar.add_cascade(label="Fichier", menu=self.file_menu)

        self.tools_menu = tk.Menu(menubar, tearoff=False)
        self.tools_menu.add_command(label="Paramètres…", command=self.open_settings)
        menubar.add_cascade(label="Outils", menu=self.tools_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="À propos…", command=self.show_about)
        menubar.add_cascade(label="Aide", menu=help_menu)

        self.root.configure(menu=menubar)

    def _build_layout(self) -> None:
        self.main = ttk.Frame(self.root, padding=10)
        self.main.pack(fill="both", expand=True)
        self.main.columnconfigure(0, weight=1)
        self.main.rowconfigure(2, weight=3)
        self.main.rowconfigure(3, weight=1)

        self._build_sites_section().grid(row=0, column=0, sticky="nsew")
        self._build_progress_section().grid(row=1, column=0, sticky="ew", pady=10)
        self._build_results_section().grid(row=2, column=0, sticky="nsew")
        self.log_panel = LogPanel(self.main, on_toggle=self._on_log_toggle)
        self.log_panel.grid(row=3, column=0, sticky="nsew", pady=(10, 0))

    def _build_sites_section(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.main, text="Sites de référence (1 URL par ligne)", padding=8)
        frame.columnconfigure(0, weight=1)

        text_frame = ttk.Frame(frame)
        text_frame.grid(row=0, column=0, sticky="nsew")
        text_frame.columnconfigure(0, weight=1)
        self.url_text = tk.Text(text_frame, height=6, wrap="none", undo=True, font="TkFixedFont")
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.url_text.yview)
        self.url_text.configure(yscrollcommand=scrollbar.set)
        self.url_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.url_text.bind("<<Modified>>", self._on_urls_modified)
        self.url_text.bind("<Control-Return>", self._on_ctrl_return)
        self.url_text.bind("<Control-o>", self._on_ctrl_o)  # sinon Tk insère une ligne vide

        side = ttk.Frame(frame)
        side.grid(row=0, column=1, sticky="n", padx=(8, 0))
        self.import_button = ttk.Button(side, text="Importer…", command=self.import_urls)
        self.import_button.pack(fill="x")
        self.clear_button = ttk.Button(side, text="Vider", command=self.clear_urls)
        self.clear_button.pack(fill="x", pady=(4, 0))

        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.start_button = ttk.Button(controls, text="▶ Démarrer", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="■ Arrêter", command=self.stop)
        self.stop_button.pack(side="left", padx=(6, 0))
        ttk.Label(controls, textvariable=self.url_count_var, foreground="gray").pack(
            side="left", padx=(12, 0)
        )

        pages_low, pages_high = LIMITS["max_pages_per_site"]
        self.pages_spin = ttk.Spinbox(
            controls, from_=pages_low, to=pages_high, width=6, textvariable=self.pages_var
        )
        self.pages_spin.pack(side="right")
        ttk.Label(controls, text="Pages max/site").pack(side="right", padx=(12, 4))
        depth_low, depth_high = LIMITS["max_depth"]
        self.depth_spin = ttk.Spinbox(
            controls, from_=depth_low, to=depth_high, width=4, textvariable=self.depth_var
        )
        self.depth_spin.pack(side="right")
        ttk.Label(controls, text="Profondeur").pack(side="right", padx=(0, 4))
        return frame

    def _build_progress_section(self) -> ttk.Frame:
        frame = ttk.Frame(self.main)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="Progression").grid(row=0, column=0, sticky="w")
        self.progressbar = ttk.Progressbar(frame, mode="determinate", maximum=1)
        self.progressbar.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(frame, textvariable=self.progress_var).grid(row=0, column=2, sticky="e")
        ttk.Label(frame, textvariable=self.status_var, foreground="gray").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0)
        )
        return frame

    def _build_results_section(self) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(self.main, text="Résultats", padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(header, textvariable=self.result_count_var, foreground="gray").pack(side="left")
        self.filter_entry = ttk.Entry(header, width=30, textvariable=self.filter_var)
        self.filter_entry.pack(side="right")
        ttk.Label(header, text="Filtre :").pack(side="right", padx=(0, 4))

        self.table = ResultsTable(
            frame, on_open=self.open_source_page, on_change=self._update_result_count
        )
        self.table.grid(row=1, column=0, sticky="nsew")
        self.table.tree.bind("<Control-c>", lambda _e: self.copy_selection())

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(buttons, text="Copier la sélection", command=self.copy_selection).pack(
            side="left"
        )
        ttk.Button(buttons, text="Exporter CSV", command=lambda: self.export("csv")).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="Exporter XLSX", command=lambda: self.export("xlsx")).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            buttons,
            text="Double-clic : ouvrir la page source · clic sur un en-tête : trier",
            foreground="gray",
        ).pack(side="right")
        return frame

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _e: self.import_urls())
        self.root.bind("<Control-s>", lambda _e: self.export("csv"))
        self.root.bind("<Control-f>", lambda _e: self.filter_entry.focus_set())

    # --- traitement -------------------------------------------------------------------

    def start(self) -> None:
        """Démarre le traitement des sites saisis."""
        if self.controller.is_running:
            return
        lines = self._url_lines()
        if not group_by_site(lines):
            messagebox.showwarning(
                APP_NAME,
                "Aucune adresse de site valide.\n\n"
                "Saisissez une adresse par ligne, par exemple :\nsite.fr\nhttps://www.site2.com",
                parent=self.root,
            )
            return
        settings = self._read_limits()
        if settings is None:
            return
        if len(self.table) and not messagebox.askyesno(
            APP_NAME,
            f"Les {_plural(len(self.table), 'résultat')} affiché(s) seront effacés"
            + (" sans avoir été exportés" if self._unsaved_results else "")
            + ".\nLancer une nouvelle recherche ?",
            parent=self.root,
        ):
            return

        self.table.clear()
        self._unsaved_results = False
        self._persist_settings(settings)
        try:
            total = self.controller.start(lines)
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        if PLACEHOLDER_CONTACT in settings.user_agent:
            self._log(
                "WARN",
                "Le User-Agent contient encore l'adresse d'exemple : indiquez votre contact "
                "dans Outils > Paramètres.",
            )
        self.progressbar.configure(maximum=total, value=0)
        self.progress_var.set(format_stats(CrawlStats(sites_total=total)))
        self._set_running(True)
        self.status_var.set(f"Traitement en cours ({_plural(total, 'site')})…")

    def stop(self) -> None:
        """Demande l'arrêt propre du traitement."""
        if not self.controller.is_running:
            return
        self.controller.stop()
        self.stop_button.state(["disabled"])
        self.status_var.set("Arrêt en cours… (fin des requêtes déjà envoyées)")

    # --- liste des sites --------------------------------------------------------------

    def clear_urls(self) -> None:
        """Vide la zone de saisie des sites."""
        self.url_text.delete("1.0", "end")
        self._update_url_count()

    def import_urls(self) -> None:
        """Ajoute les adresses d'un fichier .txt ou .csv à la liste des sites."""
        if self._running:
            return
        filename = filedialog.askopenfilename(
            parent=self.root, title="Importer une liste de sites", filetypes=IMPORT_FILETYPES
        )
        if not filename:
            return
        path = Path(filename)
        try:
            urls = read_url_file(path)
        except ImportFileError as exc:
            messagebox.showerror(APP_NAME, str(exc), parent=self.root)
            return
        if not urls:
            messagebox.showwarning(
                APP_NAME, f"Aucune adresse trouvée dans {path.name}.", parent=self.root
            )
            return
        existing = self.url_text.get("1.0", "end-1c").rstrip("\n")
        self.url_text.delete("1.0", "end")
        self.url_text.insert("1.0", (existing + "\n" if existing else "") + "\n".join(urls))
        self._update_url_count()
        message = f"{_plural(len(urls), 'ligne')} importée(s) depuis {path.name}."
        self.status_var.set(message)
        self._log("INFO", message)

    # --- résultats --------------------------------------------------------------------

    def export(self, export_format: ExportFormat) -> None:
        """Exporte les résultats affichés (filtre appliqué) en CSV ou XLSX."""
        results = self.table.visible_results()
        if not results:
            messagebox.showinfo(APP_NAME, "Aucun résultat à exporter.", parent=self.root)
            return
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("Dossier d'export %s impossible à créer", self.export_dir)
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            title=f"Exporter en {export_format.upper()}",
            initialdir=str(self.export_dir),
            initialfile=default_export_name(export_format),
            defaultextension=f".{export_format}",
            filetypes=EXPORT_FILETYPES[export_format],
        )
        if not filename:
            return
        path = Path(filename)
        writer = export_csv if export_format == "csv" else export_xlsx
        try:
            count = writer(results, path)
        except PermissionError:
            messagebox.showerror(
                APP_NAME,
                f"Impossible d'écrire {path.name}.\n\n"
                "Le fichier est peut-être ouvert dans Excel : fermez-le puis réessayez.",
                parent=self.root,
            )
            return
        except OSError as exc:
            logger.exception("Export impossible vers %s", path)
            messagebox.showerror(
                APP_NAME, f"Impossible d'écrire {path.name} :\n{exc}", parent=self.root
            )
            return
        if count == len(self.table):
            self._unsaved_results = False
        message = f"{_plural(count, 'e-mail')} exporté(s) dans {path}"
        self.status_var.set(message)
        self._log("INFO", message)

    def copy_selection(self) -> None:
        """Copie les e-mails sélectionnés dans le presse-papiers, un par ligne."""
        selected = self.table.selected_results()
        if not selected:
            messagebox.showinfo(
                APP_NAME,
                "Sélectionnez une ou plusieurs lignes du tableau.\n"
                "(Ctrl+A dans le tableau pour tout sélectionner)",
                parent=self.root,
            )
            return
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(result.email for result in selected))
        self.status_var.set(f"{_plural(len(selected), 'adresse')} copiée(s).")

    def open_source_page(self, result: EmailResult) -> None:
        """Ouvre la page où l'e-mail a été trouvé dans le navigateur."""
        if result.source_url.startswith(("http://", "https://")):
            webbrowser.open(result.source_url)

    # --- paramètres -------------------------------------------------------------------

    def open_settings(self) -> SettingsDialog | None:
        """Ouvre la fenêtre des paramètres (indisponible pendant un traitement)."""
        if self._running:
            return None
        settings = self._read_limits(quiet=True) or self.controller.settings
        return SettingsDialog(self.root, settings, self.apply_settings)

    def apply_settings(self, settings: Settings) -> None:
        """Applique et enregistre de nouveaux paramètres."""
        self.depth_var.set(str(settings.max_depth))
        self.pages_var.set(str(settings.max_pages_per_site))
        logging.getLogger().setLevel(logging.DEBUG if settings.debug_logging else logging.INFO)
        if self._persist_settings(settings):
            self.status_var.set("Paramètres enregistrés.")

    # --- divers -----------------------------------------------------------------------

    def show_about(self) -> None:
        """Affiche la version et le rappel légal."""
        messagebox.showinfo(
            f"À propos — {APP_NAME}",
            f"{APP_NAME} — version {__version__}\n\n{LEGAL_NOTICE}",
            parent=self.root,
        )

    def on_close(self) -> None:
        """Fermeture : confirmation si un traitement est en cours ou si des résultats n'ont
        pas été exportés ; arrêt propre des threads avant de fermer."""
        if self._closing:
            return
        if self.controller.is_running:
            question = "Un traitement est en cours.\nL'arrêter et quitter ?"
        elif self._unsaved_results and len(self.table):
            question = (
                f"{_plural(len(self.table), 'résultat')} n'ont pas été exportés.\n"
                "Quitter quand même ?"
            )
        else:
            self._destroy()
            return
        if not messagebox.askyesno(APP_NAME, question, parent=self.root):
            return
        self._closing = True
        self.controller.stop()
        self.status_var.set("Fermeture de l'application…")
        deadline = time.monotonic() + self.controller.settings.timeout_seconds + CLOSE_GRACE_SECONDS
        self._close_when_idle(deadline)

    # --- file d'événements ------------------------------------------------------------

    def _poll(self) -> None:
        """Vide la file d'événements du contrôleur (thread principal uniquement)."""
        for _ in range(MAX_EVENTS_PER_POLL):
            try:
                event = self.controller.events.get_nowait()
            except queue.Empty:
                break
            self.handle_event(event)
        self._poll_id = self.root.after(POLL_INTERVAL_MS, self._poll)

    def handle_event(self, event: Event) -> None:
        """Met à jour l'interface pour un événement du contrôleur."""
        if event.type == "email":
            self.table.add(event.payload)
            self._unsaved_results = True
        elif event.type in ("log", "error"):
            self.log_panel.append(event.payload)
        elif event.type == "progress":
            self._show_progress(event.payload)
        elif event.type == "done":
            self._on_done(event.payload)

    def _show_progress(self, stats: CrawlStats) -> None:
        self.progressbar.configure(maximum=max(stats.sites_total, 1), value=stats.sites_done)
        self.progress_var.set(format_stats(stats))

    def _on_done(self, summary: RunSummary) -> None:
        self._show_progress(summary.stats)
        self._set_running(False)
        emails = _plural(summary.stats.emails_found, "e-mail")
        if summary.stopped:
            self.status_var.set(f"Arrêté par l'utilisateur. {emails} trouvé(s).")
        else:
            self.status_var.set(
                f"Terminé en {format_duration(summary.duration_seconds)}. {emails} trouvé(s)."
            )

    # --- utilitaires ------------------------------------------------------------------

    def _url_lines(self) -> list[str]:
        return self.url_text.get("1.0", "end-1c").splitlines()

    def _read_limits(self, *, quiet: bool = False) -> Settings | None:
        """Paramètres actuels avec la profondeur et les pages saisies dans la fenêtre.

        Affiche une erreur (sauf si `quiet`) et retourne None si une valeur est invalide.
        """
        fields = (
            ("max_depth", self.depth_var, "La profondeur"),
            ("max_pages_per_site", self.pages_var, "Le nombre de pages par site"),
        )
        values: dict[str, int] = {}
        for name, variable, label in fields:
            try:
                value = int(variable.get().strip())
            except ValueError:
                error: str | None = f"{label} doit être un nombre entier."
            else:
                error = field_error(name, value)
                values[name] = value
            if error is not None:
                if not quiet:
                    messagebox.showerror(APP_NAME, error, parent=self.root)
                return None
        return replace(
            self.controller.settings,
            max_depth=values["max_depth"],
            max_pages_per_site=values["max_pages_per_site"],
        )

    def _persist_settings(self, settings: Settings) -> bool:
        """Applique les paramètres et les enregistre dans settings.json si un chemin est
        configuré ; retourne False (après avoir prévenu l'utilisateur) si l'écriture échoue."""
        self.controller.settings = settings
        if self.settings_path is None:
            return True
        try:
            save_settings(settings, self.settings_path)
        except OSError as exc:
            logger.exception("Enregistrement des paramètres impossible")
            messagebox.showerror(
                APP_NAME,
                f"Les paramètres n'ont pas pu être enregistrés :\n{exc}\n\n"
                "Ils restent actifs jusqu'à la fermeture de l'application.",
                parent=self.root,
            )
            return False
        return True

    def _log(self, level: LogLevel, message: str) -> None:
        logger.log(logging.WARNING if level == "WARN" else logging.INFO, message)
        self.log_panel.append(LogMessage(level, message, datetime.now().replace(microsecond=0)))

    def _set_running(self, running: bool) -> None:
        self._running = running
        idle_state = ["disabled"] if running else ["!disabled"]
        for widget in (
            self.start_button,
            self.clear_button,
            self.import_button,
            self.depth_spin,
            self.pages_spin,
        ):
            widget.state(idle_state)
        self.stop_button.state(["!disabled"] if running else ["disabled"])
        self.url_text.configure(
            state="disabled" if running else "normal",
            background=TEXT_BG_READONLY if running else TEXT_BG_EDITABLE,
        )
        menu_state = "disabled" if running else "normal"
        self.file_menu.entryconfigure("Importer une liste…", state=menu_state)
        self.tools_menu.entryconfigure("Paramètres…", state=menu_state)

    def _update_url_count(self) -> None:
        count = len(group_by_site(self._url_lines()))
        self.url_count_var.set(
            "Aucun site valide"
            if count == 0
            else f"{_plural(count, 'site')} valide{'s' if count > 1 else ''}"
        )

    def _update_result_count(self) -> None:
        total, visible = len(self.table), self.table.visible_count
        text = _plural(total, "résultat")
        if visible != total:
            text += f" · {visible} affiché{'s' if visible > 1 else ''}"
        self.result_count_var.set(text)

    def _on_filter_changed(self, *_args: object) -> None:
        self.table.set_filter(self.filter_var.get())
        self._update_result_count()

    def _on_urls_modified(self, _event: tk.Event[tk.Misc]) -> None:
        self._update_url_count()
        self.url_text.edit_modified(False)

    def _on_ctrl_return(self, _event: tk.Event[tk.Misc]) -> str:
        self.start()
        return "break"

    def _on_ctrl_o(self, _event: tk.Event[tk.Misc]) -> str:
        self.import_urls()
        return "break"

    def _on_log_toggle(self, expanded: bool) -> None:
        self.main.rowconfigure(3, weight=1 if expanded else 0)

    def _close_when_idle(self, deadline: float) -> None:
        if not self.controller.is_running or time.monotonic() >= deadline:
            self._destroy()
        else:
            self.root.after(POLL_INTERVAL_MS, self._close_when_idle, deadline)

    def _destroy(self) -> None:
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self.root.destroy()

    def _report_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        logger.error("Erreur dans l'interface", exc_info=(exc_type, exc_value, traceback))
        messagebox.showerror(
            APP_NAME,
            "Une erreur inattendue s'est produite.\nLes détails techniques sont dans logs/app.log.",
            parent=self.root,
        )
