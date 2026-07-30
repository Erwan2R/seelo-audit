from __future__ import annotations

from pathlib import Path

from seelo_audit.checks.base import CrawlResult, PageDocument

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "html"


def load_fixture(name: str, url: str = "https://exemple-test.fr/") -> PageDocument:
    html = (FIXTURES_DIR / name).read_text(encoding="utf-8")
    return PageDocument(url=url, html=html)


def crawl_from_home(name: str, url: str = "https://exemple-test.fr/") -> CrawlResult:
    return CrawlResult(home=load_fixture(name, url))
