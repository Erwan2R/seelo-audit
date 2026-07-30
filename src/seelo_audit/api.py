"""Service HTTP interne (FastAPI) — expose `pipeline.audit_one` pour le lead
magnet public `/audit-site` de landing-leadmagnets.

N'est JAMAIS exposé publiquement (pas de règle Traefik publique) — appelé
uniquement en réseau interne par le conteneur Next.js. Le rate-limiting par
IP visiteur se fait côté Next.js (qui seul connaît l'IP réelle du visiteur).

Zéro changement au cœur de l'audit : réutilise `pipeline.audit_one` tel quel,
exactement comme le CLI.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from playwright.async_api import Browser, async_playwright
from pydantic import BaseModel

from seelo_audit.config import OUT_DIR, settings
from seelo_audit.models import Audit
from seelo_audit.pipeline import audit_one
from seelo_audit.security import UnsafeUrlError, validate_url

logger = logging.getLogger("seelo_audit.api")

MAX_CONCURRENT_AUDITS = 2
JOB_RETENTION_S = 3600
CLEANUP_INTERVAL_S = 600

JobStatus = Literal["queued", "running", "done", "failed"]


@dataclass
class JobRecord:
    id: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    audit: Audit | None = None
    error: str | None = None


class State:
    http_client: httpx.AsyncClient
    playwright: Any
    browser: Browser
    semaphore: asyncio.Semaphore
    jobs: dict[str, JobRecord]


state = State()


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_S)
        cutoff = time.time() - JOB_RETENTION_S
        stale = [
            job_id
            for job_id, job in state.jobs.items()
            if job.finished_at is not None and job.finished_at < cutoff
        ]
        for job_id in stale:
            del state.jobs[job_id]
        if stale:
            logger.info("Purge de %d job(s) terminé(s) depuis > 1h", len(stale))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    state.http_client = httpx.AsyncClient(http2=True, follow_redirects=False)
    state.playwright = await async_playwright().start()
    state.browser = await state.playwright.chromium.launch(
        args=["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"]
    )
    state.semaphore = asyncio.Semaphore(MAX_CONCURRENT_AUDITS)
    state.jobs = {}
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        await state.browser.close()
        await state.playwright.stop()
        await state.http_client.aclose()


app = FastAPI(title="seelo-audit-api", lifespan=lifespan)


class AuditRequest(BaseModel):
    url: str


class JobCreatedResponse(BaseModel):
    id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    id: str
    status: JobStatus
    audit: Audit | None = None
    error: str | None = None


async def _run_job(job_id: str, url: str) -> None:
    job = state.jobs[job_id]
    async with state.semaphore:
        job.status = "running"
        try:
            audit = await audit_one(url, state.http_client, state.browser, settings)
            job.audit = audit
            job.status = "done"
        except Exception as exc:  # isolation stricte : un job qui plante ne touche pas les autres
            logger.exception("Audit échoué pour job %s", job_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/audits", response_model=JobCreatedResponse, status_code=202)
async def create_audit(payload: AuditRequest) -> JobCreatedResponse:
    try:
        await validate_url(payload.url)
    except UnsafeUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = str(uuid.uuid4())
    state.jobs[job_id] = JobRecord(id=job_id)
    asyncio.create_task(_run_job(job_id, payload.url))
    return JobCreatedResponse(id=job_id, status="queued")


@app.get("/audits/{job_id}", response_model=JobStatusResponse)
async def get_audit(job_id: str) -> JobStatusResponse:
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job inconnu ou expiré")
    return JobStatusResponse(id=job.id, status=job.status, audit=job.audit, error=job.error)


@app.get("/audits/{job_id}/screenshots/{which}")
async def get_screenshot(job_id: str, which: Literal["desktop", "mobile"]) -> FileResponse:
    job = state.jobs.get(job_id)
    if job is None or job.audit is None:
        raise HTTPException(status_code=404, detail="Job inconnu, expiré ou pas encore terminé")
    path = OUT_DIR / "screenshots" / job.audit.domain / f"{which}.jpg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Capture indisponible")
    return FileResponse(path, media_type="image/jpeg")
