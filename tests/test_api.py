from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from seelo_audit import api as api_module
from seelo_audit.models import Audit, CheckResult


class _FakeBrowser:
    async def close(self) -> None:
        return None


class _FakeChromium:
    async def launch(self, **kwargs: object) -> _FakeBrowser:
        return _FakeBrowser()


class _FakePlaywright:
    chromium = _FakeChromium()

    async def stop(self) -> None:
        return None


class _FakePlaywrightManager:
    async def start(self) -> _FakePlaywright:
        return _FakePlaywright()


def _fake_async_playwright() -> _FakePlaywrightManager:
    return _FakePlaywrightManager()


def _make_audit(domain: str) -> Audit:
    return Audit(
        domain=domain,
        url=f"https://{domain}/",  # type: ignore[arg-type]
        audited_at=datetime.now(UTC),
        status="ok",
        checks=[
            CheckResult(id="online_booking", status="present", evidence="test", provider="calendly")
        ],
        score_tunnel=42,
        temperature="TIEDE",
        outreach_hook="Bonjour {prenom}...",
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Le vrai navigateur Playwright et le vrai `audit_one` sont remplacés par
    des doublures — ce test valide le cycle de vie des jobs, pas l'audit lui-même
    (déjà couvert par les autres tests)."""
    monkeypatch.setattr(api_module, "async_playwright", _fake_async_playwright)

    async def _fake_audit_one(
        url: str, client: object, browser: object, settings: object, prenom: str | None = None
    ) -> Audit:
        await asyncio.sleep(0)
        return _make_audit("example.com")

    monkeypatch.setattr(api_module, "audit_one", _fake_audit_one)

    with TestClient(api_module.app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_audit_job_lifecycle(client: TestClient) -> None:
    created = client.post("/audits", json={"url": "https://example.com/"})
    assert created.status_code == 202
    body = created.json()
    assert body["status"] == "queued"
    job_id = body["id"]

    status_body = None
    for _ in range(50):
        response = client.get(f"/audits/{job_id}")
        assert response.status_code == 200
        status_body = response.json()
        if status_body["status"] == "done":
            break
        time.sleep(0.05)
    else:
        pytest.fail("Le job ne s'est jamais terminé")

    assert status_body is not None
    assert status_body["audit"]["domain"] == "example.com"
    assert status_body["audit"]["score_tunnel"] == 42
    assert status_body["audit"]["temperature"] == "TIEDE"


def test_unknown_job_returns_404(client: TestClient) -> None:
    response = client.get("/audits/does-not-exist")
    assert response.status_code == 404


def test_unsafe_url_rejected(client: TestClient) -> None:
    response = client.post("/audits", json={"url": "http://127.0.0.1/"})
    assert response.status_code == 400


def test_screenshot_404_when_job_unknown(client: TestClient) -> None:
    response = client.get("/audits/does-not-exist/screenshots/desktop")
    assert response.status_code == 404
