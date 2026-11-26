"""Composants d'interface réutilisables : tableau des résultats et journal repliable."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from typing import Any, Literal

from app.models import METHOD_LABELS, EmailResult, LogMessage

LOG_COLORS: dict[str, str] = {"WARN": "#b35c00", "ERROR": "#c00000"}

SORT_ASCENDING_MARK = " ▲"
SORT_DESCENDING_MARK = " ▼"

SortKey = tuple[Any, int]


def _sort_value(result: EmailResult, column: str) -> Any:
    """Valeur de tri d'une colonne (textes sans tenir compte des majuscules)."""
    if column == "date":
        return result.found_at
    text = {
        "email": result.email,
        "site": result.site,
        "source": result.source_url,
        "method": METHOD_LABELS.get(result.method, result.method),
    }[column]
    return text.lower()


class ResultsTable(ttk.Frame):
    """Tableau des e-mails trouvés : tri au clic sur l'en-tête, filtre texte, sélection.

    Les lignes restent triées et filtrées pendant l'arrivée de nouveaux résultats.
    """

    COLUMNS: tuple[tuple[str, str, int, bool], ...] = (
        # identifiant, titre, largeur, s'étire
        ("email", "E-mail", 260, True),
        ("site", "Site", 150, False),
        ("source", "Page source", 360, True),
        ("method", "Méthode", 80, False),
        ("date", "Date", 130, False),
    )

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_open: Callable[[EmailResult], None] | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self._on_open = on_open
        self._on_change = on_change
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self, columns=[c[0] for c in self.COLUMNS], show="headings", selectmode="extended"
        )
        for key, title, width, stretch in self.COLUMNS:
            self.tree.heading(key, text=title, anchor="w", command=partial(self.sort_by, key))
            self.tree.column(key, width=width, minwidth=60, anchor="w", stretch=stretch)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Return>", self._on_return)
        self.tree.bind("<Control-a>", self._on_select_all)

        self._results: list[EmailResult] = []  # tous les résultats, ordre d'arrivée
        self._filter = ""
        self._sort_column: str | None = None
        self._descending = False
        self._visible_keys: list[SortKey] = []  # clés des lignes affichées, ordre d'affichage

    # --- contenu ----------------------------------------------------------------------

    def add(self, result: EmailResult) -> None:
        """Ajoute un résultat, à sa place si le tableau est trié, s'il passe le filtre."""
        index = len(self._results)
        self._results.append(result)
        if self._matches(result):
            if self._sort_column:
                self._insert(index, self._insert_position(self._key(index)))
            else:
                self._insert(index, "end")
        self._changed()

    def clear(self) -> None:
        """Vide le tableau (le tri et le filtre sont conservés)."""
        self.tree.delete(*self.tree.get_children())
        self._results.clear()
        self._visible_keys.clear()
        self._changed()

    @property
    def results(self) -> list[EmailResult]:
        """Tous les résultats, dans l'ordre d'arrivée."""
        return list(self._results)

    def visible_results(self) -> list[EmailResult]:
        """Résultats affichés (filtrés), dans l'ordre d'affichage."""
        return [self._results[int(iid)] for iid in self.tree.get_children()]

    def selected_results(self) -> list[EmailResult]:
        """Résultats sélectionnés, dans l'ordre d'affichage."""
        selected = set(self.tree.selection())
        return [self._results[int(iid)] for iid in self.tree.get_children() if iid in selected]

    def select_all(self) -> None:
        """Sélectionne toutes les lignes affichées."""
        self.tree.selection_set(self.tree.get_children())

    def __len__(self) -> int:
        return len(self._results)

    @property
    def visible_count(self) -> int:
        """Nombre de lignes affichées."""
        return len(self.tree.get_children())

    # --- filtre et tri ----------------------------------------------------------------

    def set_filter(self, text: str) -> None:
        """N'affiche que les lignes dont l'e-mail, le site ou la page contient `text`."""
        needle = text.strip().lower()
        if needle != self._filter:
            self._filter = needle
            self._rebuild()

    def sort_by(self, column: str) -> None:
        """Trie par `column` ; un second clic sur la même colonne inverse l'ordre."""
        if self._sort_column == column:
            self._descending = not self._descending
        else:
            self._sort_column, self._descending = column, False
        for key, title, *_ in self.COLUMNS:
            mark = ""
            if key == column:
                mark = SORT_DESCENDING_MARK if self._descending else SORT_ASCENDING_MARK
            self.tree.heading(key, text=title + mark)
        self._rebuild()

    @property
    def sort_state(self) -> tuple[str | None, bool]:
        """(colonne triée, ordre décroissant)."""
        return self._sort_column, self._descending

    # --- interne ----------------------------------------------------------------------

    def _matches(self, result: EmailResult) -> bool:
        if not self._filter:
            return True
        return any(
            self._filter in value.lower()
            for value in (result.email, result.site, result.source_url)
        )

    def _key(self, index: int) -> SortKey:
        assert self._sort_column is not None
        return (_sort_value(self._results[index], self._sort_column), index)

    def _insert_position(self, key: SortKey) -> int:
        """Position d'insertion qui garde l'ordre (croissant ou décroissant) des lignes."""
        low, high = 0, len(self._visible_keys)
        while low < high:
            middle = (low + high) // 2
            current = self._visible_keys[middle]
            before = current <= key if not self._descending else current >= key
            if before:
                low = middle + 1
            else:
                high = middle
        return low

    def _insert(self, index: int, position: int | Literal["end"]) -> None:
        result = self._results[index]
        self.tree.insert(
            "",
            position,
            iid=str(index),
            values=(
                result.email,
                result.site,
                result.source_url,
                METHOD_LABELS.get(result.method, result.method),
                f"{result.found_at:%d/%m/%Y %H:%M}",
            ),
        )
        if self._sort_column:
            assert isinstance(position, int)
            self._visible_keys.insert(position, self._key(index))

    def _rebuild(self) -> None:
        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self._visible_keys.clear()
        indexes = [i for i, result in enumerate(self._results) if self._matches(result)]
        if self._sort_column:
            indexes.sort(key=self._key, reverse=self._descending)
        for position, index in enumerate(indexes):
            self._insert(index, position if self._sort_column else "end")
        self.tree.selection_set([iid for iid in self.tree.get_children() if iid in selection])
        self._changed()

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def _open(self, iid: str) -> None:
        if iid and self._on_open is not None:
            self._on_open(self._results[int(iid)])

    def _on_double_click(self, event: tk.Event[tk.Misc]) -> None:
        if self.tree.identify_region(event.x, event.y) == "cell":
            self._open(self.tree.identify_row(event.y))

    def _on_return(self, _event: tk.Event[tk.Misc]) -> None:
        self._open(self.tree.focus())

    def _on_select_all(self, _event: tk.Event[tk.Misc]) -> str:
        self.select_all()
        return "break"


class LogPanel(ttk.Frame):
    """Journal horodaté, repliable, limité aux dernières lignes."""

    MAX_LINES = 2000

    def __init__(self, master: tk.Misc, *, on_toggle: Callable[[bool], None] | None = None) -> None:
        super().__init__(master)
        self._on_toggle = on_toggle
        self._expanded = True
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        self.toggle_button = ttk.Button(
            header, text="▾ Journal", style="Toolbutton", command=self.toggle
        )
        self.toggle_button.pack(side="left")
        ttk.Button(header, text="Effacer", style="Toolbutton", command=self.clear).pack(
            side="right"
        )

        self.body = ttk.Frame(self)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.text = tk.Text(
            self.body, height=6, wrap="none", state="disabled", font="TkFixedFont", relief="flat"
        )
        scrollbar = ttk.Scrollbar(self.body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        for level, color in LOG_COLORS.items():
            self.text.tag_configure(level, foreground=color)

    @property
    def expanded(self) -> bool:
        """Vrai si le journal est déplié."""
        return self._expanded

    def toggle(self) -> None:
        """Replie ou déplie le journal."""
        self._expanded = not self._expanded
        if self._expanded:
            self.body.grid()
        else:
            self.body.grid_remove()
        self.toggle_button.configure(text=("▾" if self._expanded else "▸") + " Journal")
        if self._on_toggle is not None:
            self._on_toggle(self._expanded)

    def append(self, entry: LogMessage) -> None:
        """Ajoute une ligne ; défile vers le bas si l'utilisateur y était déjà."""
        at_bottom = self.text.yview()[1] >= 0.999
        line = f"{entry.timestamp:%H:%M:%S}  [{entry.level:5}]  {entry.message}\n"
        self.text.configure(state="normal")
        self.text.insert("end", line, (entry.level,))
        line_count = int(self.text.index("end-1c").split(".")[0]) - 1
        if line_count > self.MAX_LINES:
            self.text.delete("1.0", f"{line_count - self.MAX_LINES + 1}.0")
        self.text.configure(state="disabled")
        if at_bottom:
            self.text.see("end")

    def clear(self) -> None:
        """Efface le journal affiché (le fichier logs/app.log est conservé)."""
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def get_text(self) -> str:
        """Contenu affiché du journal."""
        return self.text.get("1.0", "end-1c")
