"""Fenêtre des paramètres (Outils > Paramètres…)."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import fields
from tkinter import messagebox, ttk

from app.config import LIMITS, PLACEHOLDER_CONTACT, validate_settings
from app.models import Settings

# (paramètre, libellé, aide, pas du sélecteur)
NUMERIC_FIELDS: tuple[tuple[str, str, str, float], ...] = (
    ("max_depth", "Profondeur", "Nombre de clics depuis la page de départ.", 1),
    ("max_pages_per_site", "Pages max par site", "Limite le temps passé sur chaque site.", 1),
    ("delay_seconds", "Délai entre requêtes (s)", "Au moins 1 s recommandé.", 0.5),
    ("timeout_seconds", "Délai max d'une requête (s)", "Au-delà, la page est abandonnée.", 1),
    ("max_workers", "Sites en parallèle", "Sites différents traités en même temps.", 1),
)

BOOLEAN_FIELDS: tuple[tuple[str, str], ...] = (
    ("respect_robots", "Respecter le fichier robots.txt des sites (recommandé)"),
    ("include_subdomains", "Inclure les sous-domaines (blog.site.fr pour site.fr)"),
    ("debug_logging", "Journal technique détaillé (logs/app.log)"),
)


class SettingsDialog(tk.Toplevel):
    """Fenêtre modale : `on_save` reçoit les nouveaux paramètres validés."""

    def __init__(
        self, master: tk.Misc, settings: Settings, on_save: Callable[[Settings], None]
    ) -> None:
        super().__init__(master)
        self._initial = settings
        self._on_save = on_save
        self.title("Paramètres")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.number_vars = {name: tk.StringVar(self) for name, *_ in NUMERIC_FIELDS}
        self.bool_vars = {name: tk.BooleanVar(self) for name, _ in BOOLEAN_FIELDS}
        self.user_agent_var = tk.StringVar(self)
        self._build()
        self.load(settings)

        self.bind("<Escape>", lambda _e: self.cancel())
        self.bind("<Return>", lambda _e: self.save())
        self._center_on(master.winfo_toplevel())
        self.grab_set()
        self.focus_set()

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        crawl = ttk.LabelFrame(frame, text="Exploration", padding=10)
        crawl.grid(row=0, column=0, columnspan=2, sticky="ew")
        for row, (name, label, hint, step) in enumerate(NUMERIC_FIELDS):
            low, high = LIMITS[name]
            ttk.Label(crawl, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(
                crawl,
                from_=low,
                to=high,
                increment=step,
                width=8,
                textvariable=self.number_vars[name],
            ).grid(row=row, column=1, sticky="w", padx=8)
            ttk.Label(crawl, text=hint, foreground="gray").grid(row=row, column=2, sticky="w")

        options = ttk.LabelFrame(frame, text="Options", padding=10)
        options.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        for row, (name, label) in enumerate(BOOLEAN_FIELDS):
            ttk.Checkbutton(options, text=label, variable=self.bool_vars[name]).grid(
                row=row, column=0, sticky="w", pady=2
            )

        identity = ttk.LabelFrame(frame, text="Identification auprès des sites", padding=10)
        identity.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        identity.columnconfigure(0, weight=1)
        ttk.Label(identity, text="User-Agent").grid(row=0, column=0, sticky="w")
        ttk.Entry(identity, textvariable=self.user_agent_var, width=60).grid(
            row=1, column=0, sticky="ew", pady=(2, 2)
        )
        ttk.Label(
            identity,
            text="Indiquez une adresse de contact réelle pour que les sites puissent vous joindre.",
            foreground="gray",
        ).grid(row=2, column=0, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        ttk.Button(buttons, text="Valeurs par défaut", command=self.reset_defaults).pack(
            side="left"
        )
        ttk.Button(buttons, text="Enregistrer", command=self.save).pack(side="right")
        ttk.Button(buttons, text="Annuler", command=self.cancel).pack(side="right", padx=(0, 6))

    # --- actions ----------------------------------------------------------------------

    def load(self, settings: Settings) -> None:
        """Remplit les champs avec `settings`."""
        for name, *_ in NUMERIC_FIELDS:
            value = getattr(settings, name)
            self.number_vars[name].set(f"{value:g}" if isinstance(value, float) else str(value))
        for name, _ in BOOLEAN_FIELDS:
            self.bool_vars[name].set(getattr(settings, name))
        self.user_agent_var.set(settings.user_agent)

    def reset_defaults(self) -> None:
        """Remet les valeurs par défaut (sans enregistrer), en gardant le User-Agent saisi
        s'il ne s'agit plus de l'exemple."""
        user_agent = self.user_agent_var.get()
        self.load(Settings())
        if PLACEHOLDER_CONTACT not in user_agent and user_agent.strip():
            self.user_agent_var.set(user_agent)

    def read(self) -> tuple[Settings | None, list[str]]:
        """Paramètres saisis et liste des erreurs (paramètres None s'il y a des erreurs)."""
        values: dict[str, object] = {}
        errors: list[str] = []
        types = {f.name: f.type for f in fields(Settings)}
        for name, label, *_ in NUMERIC_FIELDS:
            text = self.number_vars[name].get().strip().replace(",", ".")
            try:
                values[name] = int(text) if types[name] in ("int", int) else float(text)
            except ValueError:
                errors.append(f"« {label} » doit être un nombre.")
        if errors:
            return None, errors
        for name, _ in BOOLEAN_FIELDS:
            values[name] = self.bool_vars[name].get()
        values["user_agent"] = self.user_agent_var.get().strip()
        settings = Settings(**values)  # type: ignore[arg-type]
        errors = validate_settings(settings)
        return (None, errors) if errors else (settings, [])

    def save(self) -> None:
        """Valide, demande confirmation si robots.txt est désactivé, puis enregistre."""
        settings, errors = self.read()
        if settings is None:
            messagebox.showerror("Paramètres invalides", "\n".join(errors), parent=self)
            return
        if (
            self._initial.respect_robots
            and not settings.respect_robots
            and not messagebox.askyesno(
                "robots.txt",
                "Ignorer robots.txt revient à visiter des pages que les sites demandent de ne "
                "pas explorer.\n\nDésactiver quand même ?",
                parent=self,
            )
        ):
            return
        self._on_save(settings)
        self.destroy()

    def cancel(self) -> None:
        """Ferme sans enregistrer."""
        self.destroy()

    def _center_on(self, parent: tk.Misc) -> None:
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
