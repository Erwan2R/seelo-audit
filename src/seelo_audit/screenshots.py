"""Captures desktop + mobile, utilisées par le diagnostic visuel (détection de
visage, analyse de palette). Ferme les bandeaux cookies avant capture, sinon
ils faussent l'analyse (masquent la moitié du visuel)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image
from playwright.async_api import Browser, BrowserContext, Page, ViewportSize

from seelo_audit.config import Settings

logger = logging.getLogger(__name__)

DESKTOP_VIEWPORT: ViewportSize = {"width": 1440, "height": 900}
MOBILE_FULL_PAGE_MAX_HEIGHT = 2400
MAX_LONG_SIDE = 1400
JPEG_QUALITY = 80

# Descripteur "iPhone 13" (viewport + DPR 2 comme demandé par la spec — le
# descripteur natif Playwright utilise un DPR de 3, mais §9 impose 2).
IPHONE_13_VIEWPORT: ViewportSize = {"width": 390, "height": 844}
IPHONE_13_DEVICE_SCALE_FACTOR = 2
IPHONE_13_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

COOKIE_BANNER_SELECTORS: tuple[str, ...] = (
    "text=Tout accepter",
    "text=Accepter tout",
    "text=Tout autoriser",
    "text=Autoriser",
    "text=Accepter",
    "text=J'accepte",
    "text=J'accepte tout",
    "text=OK",
    "text=Accept all",
    "text=Continuer sans accepter",
    "#tarteaucitronPersonalize2",
    "#axeptio_btn_acceptAll",
    ".cc-allow",
    "#onetrust-accept-btn-handler",
    "[id*=didomi-notice-agree]",
)


@dataclass
class ScreenshotSet:
    desktop_path: Path
    mobile_path: Path


async def new_iphone13_context(browser: Browser) -> BrowserContext:
    """Contexte mobile partagé par les captures et le check §7.8 (mobile.py)."""
    return await browser.new_context(
        viewport=IPHONE_13_VIEWPORT,
        device_scale_factor=IPHONE_13_DEVICE_SCALE_FACTOR,
        is_mobile=True,
        has_touch=True,
        user_agent=IPHONE_13_USER_AGENT,
    )


async def _dismiss_cookie_banner(page: Page) -> None:
    for selector in COOKIE_BANNER_SELECTORS:
        try:
            locator = page.locator(selector).first
            await locator.click(timeout=2000)
            return
        except Exception:  # jamais bloquant — au pire le bandeau reste visible
            continue


async def _settle_page(page: Page) -> None:
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    await _dismiss_cookie_banner(page)
    await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(500)
    await page.evaluate("() => window.scrollTo(0, 0)")
    await page.wait_for_timeout(500)


def _postprocess(raw_bytes: bytes, out_path: Path, max_height_px: int | None = None) -> None:
    with Image.open(BytesIO(raw_bytes)) as opened:
        img: Image.Image = opened.convert("RGB")

    if max_height_px is not None and img.height > max_height_px:
        img = img.crop((0, 0, img.width, max_height_px))
    long_side = max(img.width, img.height)
    if long_side > MAX_LONG_SIDE:
        ratio = MAX_LONG_SIDE / long_side
        img = img.resize((max(1, int(img.width * ratio)), max(1, int(img.height * ratio))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=JPEG_QUALITY)


async def capture(browser: Browser, url: str, out_dir: Path, settings: Settings) -> ScreenshotSet:
    desktop_path = out_dir / "desktop.jpg"
    mobile_path = out_dir / "mobile.jpg"

    desktop_context = await browser.new_context(
        viewport=DESKTOP_VIEWPORT, user_agent=settings.user_agent
    )
    try:
        page = await desktop_context.new_page()
        await page.goto(url, timeout=settings.playwright_timeout_s * 1000)
        await _settle_page(page)
        raw = await page.screenshot(full_page=False)
        _postprocess(raw, desktop_path)
    finally:
        await desktop_context.close()

    mobile_context = await new_iphone13_context(browser)
    try:
        page = await mobile_context.new_page()
        await page.goto(url, timeout=settings.playwright_timeout_s * 1000)
        await _settle_page(page)
        raw = await page.screenshot(full_page=True)
        # Le screenshot sort en pixels physiques (DPR 2) — on coupe donc à
        # MOBILE_FULL_PAGE_MAX_HEIGHT * DPR avant le redimensionnement final.
        max_height_physical = MOBILE_FULL_PAGE_MAX_HEIGHT * IPHONE_13_DEVICE_SCALE_FACTOR
        _postprocess(raw, mobile_path, max_height_px=max_height_physical)
    finally:
        await mobile_context.close()

    return ScreenshotSet(desktop_path=desktop_path, mobile_path=mobile_path)
