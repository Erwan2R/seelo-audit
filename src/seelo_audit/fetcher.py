"""Fetch HTTP en deux temps : httpx d'abord, Playwright si rendu JS nécessaire.

Toute redirection est revalidée (anti-SSRF) à chaque saut — un domaine public
qui redirige vers 127.0.0.1 est le piège classique.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from selectolax.parser import HTMLParser

from seelo_audit.config import Settings
from seelo_audit.security import UnsafeUrlError, validate_url

logger = logging.getLogger(__name__)

SPA_MARKERS: tuple[str, ...] = (
    'id="root"',
    'id="__next"',
    "<app-root",
    "ng-version=",
    "data-reactroot",
    "wix-",
    "_next/static",
)

MIN_VISIBLE_TEXT_CHARS = 500


@dataclass
class FetchResult:
    final_url: str
    domain: str
    html: str
    status_code: int
    rendered_with_js: bool


class FetchError(Exception):
    pass


def _visible_text_len(html: str) -> int:
    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript"):
        tag.decompose()
    text = tree.body.text(separator=" ", strip=True) if tree.body else ""
    return len(text)


def needs_js_render(html: str) -> bool:
    if _visible_text_len(html) < MIN_VISIBLE_TEXT_CHARS:
        return True
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in SPA_MARKERS)


async def fetch_httpx(client: httpx.AsyncClient, start_url: str, settings: Settings) -> FetchResult:
    """GET avec suivi manuel des redirections, revalidées à chaque saut."""
    current = await validate_url(start_url)
    hops = 0

    while True:
        try:
            response = await client.get(
                current.url,
                headers={"User-Agent": settings.user_agent},
                follow_redirects=False,
                timeout=settings.fetch_timeout_s,
            )
        except httpx.HTTPError as exc:
            raise FetchError(f"Échec réseau sur {current.url} : {exc}") from exc

        if response.is_redirect:
            hops += 1
            if hops > settings.max_redirects:
                raise FetchError(f"Trop de redirections depuis {start_url}")
            location = response.headers.get("location")
            if not location:
                raise FetchError("Redirection sans en-tête Location")
            target = httpx.URL(current.url).join(location)
            try:
                current = await validate_url(str(target))
            except UnsafeUrlError as exc:
                raise FetchError(f"Redirection vers une cible refusée : {exc}") from exc
            continue

        body = response.content[: settings.max_response_bytes]
        html = body.decode(response.encoding or "utf-8", errors="replace")
        return FetchResult(
            final_url=current.url,
            domain=current.domain,
            html=html,
            status_code=response.status_code,
            rendered_with_js=False,
        )


BLOCKED_RESOURCE_TYPES = {"font", "media"}
BLOCKED_URL_SUBSTRINGS = (
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "hotjar.com",
    "doubleclick.net",
)


async def fetch_playwright(browser: object, url: str, settings: Settings) -> str:
    """Rendu JS via Playwright. `browser` est une instance chromium partagée."""
    from playwright.async_api import Browser  # import local, dépendance lourde

    assert isinstance(browser, Browser)
    context = await browser.new_context(user_agent=settings.user_agent)
    try:
        page = await context.new_page()

        async def _route(route: object) -> None:
            request = route.request  # type: ignore[attr-defined]
            if request.resource_type in BLOCKED_RESOURCE_TYPES or any(
                s in request.url for s in BLOCKED_URL_SUBSTRINGS
            ):
                await route.abort()  # type: ignore[attr-defined]
            else:
                await route.continue_()  # type: ignore[attr-defined]

        await page.route("**/*", _route)
        await page.goto(url, wait_until="networkidle", timeout=settings.playwright_timeout_s * 1000)
        html: str = await page.content()
        return html
    finally:
        await context.close()
