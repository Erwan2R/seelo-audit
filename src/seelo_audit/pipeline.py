"""Orchestration d'un audit unique. `audit_one` est appelable indépendamment
de la CLI et sans effet de bord sur out/ (compatible v2 — voir §18 de la spec)."""

from __future__ import annotations

import asyncio
import logging
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path

import httpx
from playwright.async_api import Browser

from seelo_audit.checks import run_html_checks
from seelo_audit.checks.base import CrawlResult
from seelo_audit.checks.mobile import run as run_mobile_check
from seelo_audit.config import OUT_DIR, Settings
from seelo_audit.config import settings as default_settings
from seelo_audit.crawler import crawl
from seelo_audit.models import Audit, CheckResult, VisualDiagnostic
from seelo_audit.outreach import select_hook
from seelo_audit.pagespeed import run as run_pagespeed
from seelo_audit.scoring import compute_flags, compute_score, compute_temperature
from seelo_audit.screenshots import DESKTOP_VIEWPORT, new_iphone13_context
from seelo_audit.screenshots import capture as capture_screenshots
from seelo_audit.security import UnsafeUrlError, normalize_domain, validate_url
from seelo_audit.visual_diagnostics import analyze as analyze_visual

logger = logging.getLogger(__name__)


def _placeholder_url(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", raw.strip().lower()).strip("-") or "invalide"
    return f"https://{slug[:60]}.invalid/"


async def _run_mobile_check(
    browser: Browser | None, url: str, settings: Settings, errors: list[str]
) -> CheckResult | None:
    if browser is None:
        return None
    context = await new_iphone13_context(browser)
    try:
        page = await context.new_page()
        await page.goto(url, timeout=settings.playwright_timeout_s * 1000, wait_until="networkidle")
        return await run_mobile_check(page)
    except Exception as exc:
        errors.append(f"check mobile échoué : {exc}")
        return None
    finally:
        await context.close()


async def _run_visual_diagnostic(
    crawl_result: CrawlResult,
    mobile_check: CheckResult | None,
    browser: Browser | None,
    desktop_screenshot_path: Path | None,
    settings: Settings,
    errors: list[str],
) -> VisualDiagnostic | None:
    context = None
    desktop_page = None
    try:
        if browser is not None:
            context = await browser.new_context(
                viewport=DESKTOP_VIEWPORT, user_agent=settings.user_agent
            )
            desktop_page = await context.new_page()
            await desktop_page.goto(
                crawl_result.home.url,
                timeout=settings.playwright_timeout_s * 1000,
                wait_until="networkidle",
            )
        return await analyze_visual(
            crawl_result, mobile_check, desktop_page, desktop_screenshot_path
        )
    except Exception as exc:
        errors.append(f"diagnostic visuel échoué : {exc}")
        return None
    finally:
        if context is not None:
            await context.close()


async def audit_one(
    url: str,
    client: httpx.AsyncClient,
    browser: Browser | None,
    settings: Settings = default_settings,
    prenom: str | None = None,
) -> Audit:
    try:
        validated = await validate_url(url)
    except UnsafeUrlError as exc:
        return Audit(
            domain=normalize_domain(url) if "." in url else url[:100],
            url=_placeholder_url(url),  # type: ignore[arg-type]
            audited_at=datetime.now(UTC),
            status="failed",
            temperature="EXCLU",
            errors=[f"URL refusée : {exc}"],
        )

    domain = validated.domain
    errors: list[str] = []

    try:
        async with asyncio.timeout(settings.audit_timeout_s):
            ps_task = asyncio.create_task(run_pagespeed(client, validated.url, settings))

            crawl_result = await crawl(client, browser, validated.url, settings)
            checks = run_html_checks(crawl_result)

            desktop_screenshot_path: Path | None = None
            if browser is not None:
                out_dir = OUT_DIR / "screenshots" / domain
                try:
                    shots = await capture_screenshots(
                        browser, crawl_result.home.url, out_dir, settings
                    )
                    desktop_screenshot_path = shots.desktop_path
                except Exception as exc:
                    errors.append(f"capture d'écran échouée : {exc}")

            mobile_check = await _run_mobile_check(browser, crawl_result.home.url, settings, errors)
            all_checks = [*checks, mobile_check] if mobile_check else checks

            visual_diagnostic = await _run_visual_diagnostic(
                crawl_result, mobile_check, browser, desktop_screenshot_path, settings, errors
            )

            pagespeed_result = await ps_task
    except TimeoutError:
        return Audit(
            domain=domain,
            url=validated.url,  # type: ignore[arg-type]
            audited_at=datetime.now(UTC),
            status="timeout",
            temperature="EXCLU",
            errors=[f"audit interrompu après {settings.audit_timeout_s}s"],
        )
    except Exception as exc:
        return Audit(
            domain=domain,
            url=validated.url,  # type: ignore[arg-type]
            audited_at=datetime.now(UTC),
            status="failed",
            temperature="EXCLU",
            errors=[str(exc), traceback.format_exc(limit=3)],
        )

    booking_check = next((c for c in all_checks if c.id == "online_booking"), None)
    score = compute_score(all_checks)
    temperature = compute_temperature(score, booking_check)
    competitor_locked, diy_tooling = compute_flags(booking_check)
    hook = select_hook(domain, all_checks, competitor_locked, diy_tooling, prenom)

    pages_crawled = {"home": crawl_result.home.url}
    pages_crawled.update({category: doc.url for category, doc in crawl_result.pages.items()})

    return Audit(
        domain=domain,
        url=validated.url,  # type: ignore[arg-type]
        audited_at=datetime.now(UTC),
        status="ok" if not errors else "partial",
        platform=crawl_result.platform,
        robots_restricted=crawl_result.robots_restricted,
        pages_crawled=pages_crawled,
        checks=all_checks,
        pagespeed=pagespeed_result,
        visual_diagnostic=visual_diagnostic,
        score_tunnel=score,
        temperature=temperature,
        competitor_locked=competitor_locked,
        diy_tooling=diy_tooling,
        outreach_hook=hook,
        errors=errors,
    )
