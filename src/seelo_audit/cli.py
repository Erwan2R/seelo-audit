"""CLI Typer — `seelo-audit run <fichier>` et `seelo-audit purge`."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import time
from pathlib import Path

import httpx
import typer
from playwright.async_api import Browser, async_playwright
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from seelo_audit.config import CACHE_DIR, OUT_DIR, settings
from seelo_audit.models import Audit
from seelo_audit.outputs import write_audit_json, write_report_csv
from seelo_audit.pipeline import audit_one
from seelo_audit.security import normalize_domain

app = typer.Typer(
    add_completion=False, help="Auditeur de tunnel de réservation (praticiens bien-être)."
)
console = Console()
logger = logging.getLogger("seelo_audit")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logging() -> None:
    log_path = OUT_DIR / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(RichHandler(console=console, show_path=False, rich_tracebacks=True))
    root.addHandler(file_handler)


def _read_urls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        rows = [row for row in csv.reader(text.splitlines()) if row]
        if not rows:
            return []
        start = 1 if "." not in rows[0][0] else 0
        return [row[0].strip() for row in rows[start:] if row[0].strip()]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def _guess_cache_path(raw_url: str) -> Path | None:
    try:
        host = raw_url.split("//")[-1].split("/")[0]
        domain = normalize_domain(host)
    except Exception:
        return None
    return OUT_DIR / "audits" / f"{domain}.json"


def _is_recent(path: Path, ttl_days: int) -> bool:
    return (time.time() - path.stat().st_mtime) < ttl_days * 86400


def _load_all_audits() -> list[Audit]:
    audits_dir = OUT_DIR / "audits"
    if not audits_dir.exists():
        return []
    audits: list[Audit] = []
    for json_path in audits_dir.glob("*.json"):
        try:
            audits.append(Audit.model_validate_json(json_path.read_text(encoding="utf-8")))
        except Exception:
            logger.warning("JSON illisible ignoré : %s", json_path)
    return audits


async def _run_batch(urls: list[str], force: bool, no_browser: bool) -> None:
    semaphore = asyncio.Semaphore(settings.max_concurrency)
    succeeded = 0
    failed = 0
    skipped = 0

    async with httpx.AsyncClient(http2=True, follow_redirects=False) as client:
        browser: Browser | None = None
        playwright_ctx = None
        if not no_browser:
            playwright_ctx = await async_playwright().start()
            browser = await playwright_ctx.chromium.launch(
                args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
            )

        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("Audit en cours...", total=len(urls))

                async def _one(raw_url: str) -> None:
                    nonlocal succeeded, failed, skipped
                    async with semaphore:
                        cache_path = _guess_cache_path(raw_url)
                        if not force and cache_path is not None and cache_path.exists():
                            if _is_recent(cache_path, settings.cache_ttl_days):
                                skipped += 1
                                progress.advance(task_id)
                                return
                        try:
                            audit = await audit_one(raw_url, client, browser)
                            write_audit_json(audit)
                        except Exception:
                            logger.exception("Audit inattendu échoué pour %s", raw_url)
                            failed += 1
                            progress.advance(task_id)
                            return
                        if audit.status in ("ok", "partial"):
                            succeeded += 1
                        else:
                            failed += 1
                        progress.advance(task_id)

                await asyncio.gather(*(_one(u) for u in urls))
        finally:
            if browser is not None:
                await browser.close()
            if playwright_ctx is not None:
                await playwright_ctx.stop()

    all_audits = _load_all_audits()
    csv_path = write_report_csv(all_audits)
    console.print(
        f"[green]{succeeded} succès[/green], [red]{failed} échec(s)[/red], "
        f"{skipped} déjà en cache — voir {csv_path}"
    )


@app.command()
def run(
    input_file: Path = typer.Argument(  # noqa: B008
        ..., help="Fichier CSV ou TXT listant les URLs à auditer."
    ),
    force: bool = typer.Option(
        False, "--force", help="Réaudite même si un résultat récent existe déjà."
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="Désactive Playwright (checks HTML seuls, plus rapide, moins complet).",
    ),
) -> None:
    """Audite une liste d'URLs et produit out/audits/*.json + out/report.csv."""
    _setup_logging()
    if not input_file.exists():
        console.print(f"[red]Fichier introuvable : {input_file}[/red]")
        raise typer.Exit(code=1)

    urls = _read_urls(input_file)
    if not urls:
        console.print("[red]Aucune URL trouvée dans le fichier d'entrée.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"[bold]{len(urls)} URL(s) à auditer[/bold] (concurrence max : {settings.max_concurrency})"
    )
    asyncio.run(_run_batch(urls, force=force, no_browser=no_browser))


@app.command()
def purge(
    older_than: str = typer.Option("90d", "--older-than", help="Ex : 90d, 30d."),
) -> None:
    """Vide cache/, out/screenshots/ et les audits JSON plus anciens que --older-than."""
    if not older_than.endswith("d"):
        console.print("[red]Format attendu : <N>d, ex. 90d[/red]")
        raise typer.Exit(code=1)
    days = int(older_than[:-1])
    cutoff = time.time() - days * 86400

    removed = 0
    for base in (CACHE_DIR, OUT_DIR / "screenshots", OUT_DIR / "audits"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
    console.print(f"[green]{removed} fichier(s) supprimé(s).[/green]")


if __name__ == "__main__":
    app()
