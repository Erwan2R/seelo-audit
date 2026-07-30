"""Appel PageSpeed Insights — jamais bloquant : échec => pagespeed: null."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
import tenacity
from tenacity import retry, retry_if_exception_type, stop_after_attempt

from seelo_audit.config import CACHE_DIR, Settings
from seelo_audit.models import PageSpeedResult

logger = logging.getLogger(__name__)

PAGESPEED_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
BACKOFFS_S = (2.0, 8.0, 20.0)


class PageSpeedError(Exception):
    pass


def _wait_from_spec(retry_state: tenacity.RetryCallState) -> float:
    idx = retry_state.attempt_number - 1
    return BACKOFFS_S[min(idx, len(BACKOFFS_S) - 1)]


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"pagespeed_{key}.json"


def _read_cache(url: str, ttl_days: int) -> PageSpeedResult | None:
    path = _cache_path(url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    fetched_at = payload.get("fetched_at", 0.0)
    if time.time() - fetched_at > ttl_days * 86400:
        return None
    return PageSpeedResult.model_validate(payload["result"])


def _write_cache(url: str, result: PageSpeedResult) -> None:
    path = _cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "result": result.model_dump()}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _score(categories: dict[str, Any], name: str) -> int | None:
    cat = categories.get(name)
    if not cat or cat.get("score") is None:
        return None
    return int(round(float(cat["score"]) * 100))


def _numeric(audits: dict[str, Any], audit_id: str) -> float | None:
    audit = audits.get(audit_id)
    if not audit:
        return None
    value = audit.get("numericValue")
    return float(value) if value is not None else None


def _extract(data: dict[str, Any]) -> PageSpeedResult:
    lighthouse = data.get("lighthouseResult", {})
    categories = lighthouse.get("categories", {})
    audits = lighthouse.get("audits", {})

    opportunities = [
        {
            "id": audit.get("id"),
            "title": audit.get("title"),
            "savings_ms": audit.get("details", {}).get("overallSavingsMs", 0),
        }
        for audit in audits.values()
        if audit.get("details", {}).get("type") == "opportunity"
    ]
    opportunities.sort(key=lambda o: o["savings_ms"], reverse=True)

    return PageSpeedResult(
        performance_score=_score(categories, "performance"),
        seo_score=_score(categories, "seo"),
        lcp_ms=_numeric(audits, "largest-contentful-paint"),
        cls=_numeric(audits, "cumulative-layout-shift"),
        tbt_ms=_numeric(audits, "total-blocking-time"),
        speed_index_ms=_numeric(audits, "speed-index"),
        top_opportunities=opportunities[:3],
    )


@retry(
    stop=stop_after_attempt(3),
    wait=_wait_from_spec,
    retry=retry_if_exception_type(PageSpeedError),
    reraise=True,
)
async def _request_once(
    client: httpx.AsyncClient, url: str, api_key: str, timeout: float
) -> dict[str, Any]:
    try:
        response = await client.get(
            PAGESPEED_ENDPOINT,
            params={
                "url": url,
                "key": api_key,
                "strategy": "mobile",
                "category": ["performance", "seo"],
            },
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        raise PageSpeedError(str(exc)) from exc

    if response.status_code >= 500:
        raise PageSpeedError(f"PageSpeed a répondu {response.status_code}")
    if response.status_code != 200:
        raise PageSpeedError(
            f"PageSpeed erreur non retryable {response.status_code} : {response.text[:200]}"
        )
    data: dict[str, Any] = response.json()
    return data


async def run(client: httpx.AsyncClient, url: str, settings: Settings) -> PageSpeedResult | None:
    """3 tentatives (backoff 2/8/20s). Après échec : None, jamais bloquant."""
    cached = _read_cache(url, settings.cache_ttl_days)
    if cached is not None:
        return cached

    if not settings.pagespeed_api_key:
        logger.info("PAGESPEED_API_KEY absente — pagespeed ignoré pour %s", url)
        return None

    try:
        data = await _request_once(
            client, url, settings.pagespeed_api_key, settings.pagespeed_timeout_s
        )
    except PageSpeedError as exc:
        logger.warning("PageSpeed a échoué après 3 tentatives pour %s : %s", url, exc)
        return None

    result = _extract(data)
    _write_cache(url, result)
    return result
