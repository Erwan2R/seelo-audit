from __future__ import annotations

import pytest

from seelo_audit.security import UnsafeUrlError, normalize_domain, robots_allows, validate_url

UNSAFE_URLS = [
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/admin",
    "https://localhost/",
    "http://10.0.0.1/",
    "http://172.16.5.4/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",  # métadonnées cloud
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[fc00::1]/",
    "http://[fe80::1]/",
    "ftp://example.com/",
    "file:///etc/passwd",
    "http://example.com:22/",
    "http://example.com:8022/",
    "javascript:alert(1)",
    "http://0x7f000001/",  # 127.0.0.1 encodé en hexa
    "http://2130706433/",  # 127.0.0.1 encodé en décimal
    "http://this-domain-does-not-exist-seelo-audit-test.invalid/",
    "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6 loopback
]


@pytest.mark.parametrize("raw", UNSAFE_URLS)
async def test_unsafe_urls_rejected(raw: str) -> None:
    with pytest.raises(UnsafeUrlError):
        await validate_url(raw)


async def test_safe_public_url_accepted() -> None:
    validated = await validate_url("example.com")
    assert validated.url.startswith("https://")
    assert validated.domain == "example.com"


def test_domain_normalization_strips_www() -> None:
    assert normalize_domain("www.cabinet-zen.fr") == normalize_domain("cabinet-zen.fr")
    assert normalize_domain("cabinet-zen.fr") == "cabinet-zen.fr"


def test_robots_allows_defaults_to_true_when_absent() -> None:
    assert robots_allows(None, "https://example.com/", "SeeloAuditBot") is True


def test_robots_disallow_all() -> None:
    robots_txt = "User-agent: *\nDisallow: /"
    assert robots_allows(robots_txt, "https://example.com/tarifs", "SeeloAuditBot") is False


def test_robots_allows_specific_path() -> None:
    robots_txt = "User-agent: *\nDisallow: /admin"
    assert robots_allows(robots_txt, "https://example.com/tarifs", "SeeloAuditBot") is True
    assert robots_allows(robots_txt, "https://example.com/admin/x", "SeeloAuditBot") is False
