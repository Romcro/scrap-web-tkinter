"""Point d'entrée : lance l'application de bureau.

python main.py              lance l'interface
python main.py --selftest   vérifie que l'exécutable embarque tout le nécessaire
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import APP_NAME, __version__
from app.config import load_settings
from app.core.controller import ScraperController
from app.ui.main_window import MainWindow

LOG_MAX_BYTES = 1_000_000
LOG_BACKUP_COUNT = 3


def app_dir() -> Path:
    """Dossier de l'application (à côté du .exe une fois packagé)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def setup_logging(log_dir: Path, level: int = logging.INFO) -> None:
    """Journal technique dans logs/app.log avec rotation (3 fichiers de 1 Mo)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(threadName)s %(name)s : %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


def enable_high_dpi() -> None:
    """Texte net sur les écrans Windows à mise à l'échelle (125 %, 150 %…)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass


def run_self_test() -> int:
    """Vérifie les dépendances embarquées (lxml, tldextract, openpyxl, Tk) ; 0 si tout va bien."""
    import tempfile
    from datetime import datetime

    from app.core.extractor import extract_emails
    from app.core.url_utils import registered_domain
    from app.io.exporter import export_xlsx
    from app.models import EmailResult

    logger = logging.getLogger("selftest")
    try:
        found = extract_emails(
            '<a href="mailto:test@autotest.fr">x</a> info [at] autotest [dot] fr'
        )
        assert [e.email for e in found] == ["test@autotest.fr", "info@autotest.fr"], found
        assert registered_domain("a.b.site.co.uk") == "site.co.uk"
        with tempfile.TemporaryDirectory() as folder:
            result = EmailResult("a@b.fr", "b.fr", "https://b.fr", datetime.now(), "regex")
            assert export_xlsx([result], Path(folder) / "test.xlsx") == 1
        root = tk.Tk()
        root.destroy()
    except Exception:
        logger.exception("Autotest en échec")
        return 1
    logger.info("Autotest réussi")
    return 0


def main() -> int:
    """Lance la fenêtre principale (ou l'autotest)."""
    base = app_dir()
    settings_path = base / "config" / "settings.json"
    settings = load_settings(settings_path)
    setup_logging(base / "logs", logging.DEBUG if settings.debug_logging else logging.INFO)
    logging.getLogger(__name__).info("Démarrage de %s %s", APP_NAME, __version__)
    if "--selftest" in sys.argv[1:]:
        return run_self_test()

    enable_high_dpi()
    root = tk.Tk()
    MainWindow(
        root,
        ScraperController(settings),
        settings_path=settings_path,
        export_dir=base / "exports",
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
