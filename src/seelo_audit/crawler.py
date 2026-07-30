"""Découverte des pages internes pertinentes depuis la page d'accueil."""

from __future__ import annotations

import asyncio
from urllib.parse import urljoin, urlsplit

import httpx
from selectolax.parser import HTMLParser

from seelo_audit.checks.base import CrawlResult, PageDocument, normalize_text
from seelo_audit.checks.platform import detect_platform
from seelo_audit.config import Settings
from seelo_audit.fetcher import FetchResult, fetch_httpx, fetch_playwright, needs_js_render
from seelo_audit.security import robots_allows

# Catégorie -> (priorité, mots-clés). Priorité basse = prioritaire.
CATEGORY_KEYWORDS: dict[str, tuple[int, tuple[str, ...]]] = {
    "booking": (
        1,
        (
            "rendez-vous",
            "rdv",
            "reserver",
            "reservation",
            "prendre-rdv",
            "booking",
            "agenda",
            "consultation",
        ),
    ),
    "pricing": (
        1,
        ("tarif", "tarifs", "prix", "honoraires", "formules", "forfaits", "investissement"),
    ),
    "contact": (2, ("contact", "me-contacter", "coordonnees")),
    "services": (
        3,
        ("prestations", "seances", "accompagnement", "offres", "services", "ce-que-je-propose"),
    ),
    "about": (4, ("a-propos", "qui-suis-je", "mon-parcours", "presentation")),
    "legal": (5, ("mentions-legales", "cgv", "conditions", "confidentialite", "politique")),
}


async def _fetch_document(
    client: httpx.AsyncClient, browser: object | None, url: str, settings: Settings
) -> tuple[PageDocument, str]:
    result = await fetch_httpx(client, url, settings)
    html = result.html
    if needs_js_render(html) and browser is not None:
        html = await fetch_playwright(browser, result.final_url, settings)
        result = FetchResult(result.final_url, result.domain, html, result.status_code, True)
    return PageDocument(url=result.final_url, html=html), result.domain


def _categorize_links(home_url: str, tree: HTMLParser) -> dict[str, str]:
    home_host = urlsplit(home_url).hostname or ""
    best: dict[str, tuple[int, str]] = {}
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(home_url, href)
        parts = urlsplit(absolute)
        if parts.scheme not in ("http", "https") or parts.hostname != home_host:
            continue
        anchor_text = a.text(separator=" ", strip=True) or ""
        haystack = normalize_text(f"{absolute} {anchor_text}")
        for category, (priority, keywords) in CATEGORY_KEYWORDS.items():
            if any(normalize_text(kw) in haystack for kw in keywords):
                current = best.get(category)
                if current is None or priority < current[0]:
                    best[category] = (priority, absolute)
                break
    return {category: url for category, (_priority, url) in best.items()}


async def crawl(
    client: httpx.AsyncClient,
    browser: object | None,
    start_url: str,
    settings: Settings,
) -> CrawlResult:
    home_doc, domain = await _fetch_document(client, browser, start_url, settings)

    robots_txt: str | None = None
    try:
        robots_response = await client.get(
            f"https://{domain}/robots.txt",
            headers={"User-Agent": settings.user_agent},
            timeout=settings.fetch_timeout_s,
        )
        if robots_response.status_code == 200:
            robots_txt = robots_response.text
    except httpx.HTTPError:
        robots_txt = None

    robots_restricted = robots_txt is not None and not robots_allows(
        robots_txt, home_doc.url, settings.user_agent
    )

    crawl_result = CrawlResult(home=home_doc, robots_restricted=robots_restricted)

    if robots_restricted:
        # On audite quand même la page d'accueil (consultation, pas indexation)
        # mais on ne crawle pas les pages internes.
        crawl_result.platform = detect_platform(crawl_result)
        return crawl_result

    categorized_links = list(_categorize_links(home_doc.url, home_doc.tree).items())
    pages: dict[str, PageDocument] = {}
    for category, url in categorized_links[: settings.max_pages_crawled]:
        await asyncio.sleep(settings.crawl_delay_s)
        try:
            doc, _ = await _fetch_document(client, browser, url, settings)
        except Exception:  # une page interne cassée ne doit pas faire échouer l'audit
            continue
        pages[category] = doc

    crawl_result.pages = pages
    crawl_result.platform = detect_platform(crawl_result)
    return crawl_result
