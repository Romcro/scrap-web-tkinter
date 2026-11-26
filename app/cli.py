"""Traitement de plusieurs sites en ligne de commande, pour tester le cœur sans l'interface.

Exemples :
    python -m app.cli site1.fr site2.com --depth 1 --pages 10
    python -m app.cli --file sites.txt
"""

from __future__ import annotations

import argparse
import logging
import queue
import sys
from pathlib import Path

from app.core.controller import ScraperController
from app.models import EmailResult, LogMessage, RunSummary, Settings


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    defaults = Settings()
    parser = argparse.ArgumentParser(description="Extrait les e-mails publiés sur des sites.")
    parser.add_argument("urls", nargs="*", help="URL des sites (ex. : site.fr)")
    parser.add_argument("-f", "--file", type=Path, help="fichier texte, une URL par ligne")
    parser.add_argument("--depth", type=int, default=defaults.max_depth, help="profondeur max")
    parser.add_argument(
        "--pages", type=int, default=defaults.max_pages_per_site, help="pages max par site"
    )
    parser.add_argument(
        "--delay", type=float, default=defaults.delay_seconds, help="délai entre requêtes (s)"
    )
    parser.add_argument(
        "--timeout", type=int, default=defaults.timeout_seconds, help="délai max d'une requête (s)"
    )
    parser.add_argument(
        "--workers", type=int, default=defaults.max_workers, help="sites traités en parallèle"
    )
    parser.add_argument("--no-robots", action="store_true", help="ignorer robots.txt")
    parser.add_argument("--subdomains", action="store_true", help="inclure les sous-domaines")
    parser.add_argument("-v", "--verbose", action="store_true", help="journal technique détaillé")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée de la ligne de commande."""
    args = _parse_args(argv)
    urls: list[str] = list(args.urls)
    if args.file is not None:
        urls += args.file.read_text(encoding="utf-8-sig").splitlines()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.CRITICAL,
        format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
        datefmt="%H:%M:%S",
    )
    settings = Settings(
        max_depth=args.depth,
        max_pages_per_site=args.pages,
        delay_seconds=args.delay,
        timeout_seconds=args.timeout,
        max_workers=args.workers,
        respect_robots=not args.no_robots,
        include_subdomains=args.subdomains,
    )
    controller = ScraperController(settings)
    try:
        controller.start(urls)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    results: list[EmailResult] = []
    while True:
        try:
            event = controller.events.get(timeout=0.2)
        except queue.Empty:
            continue
        except KeyboardInterrupt:
            print("Arrêt demandé, patientez…")
            controller.stop()
            continue
        if event.type in ("log", "error"):
            log: LogMessage = event.payload
            print(f"{log.timestamp:%H:%M:%S}  [{log.level:5}]  {log.message}")
        elif event.type == "email":
            result: EmailResult = event.payload
            results.append(result)
            print(f"          ✉ {result.email} ({result.method}) ← {result.source_url}")
        elif event.type == "done":
            summary: RunSummary = event.payload
            break

    print(f"\n{len(results)} e-mail(s) :")
    for result in results:
        print(f"  {result.email:40} {result.site:25} {result.source_url}")
    return 1 if summary.stopped else 0


if __name__ == "__main__":
    sys.exit(main())
