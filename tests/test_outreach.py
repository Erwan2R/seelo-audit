from __future__ import annotations

from seelo_audit.models import CheckResult
from seelo_audit.outreach import select_hook


def _check(
    check_id: str, status: str, provider: str | None = None, **detail: object
) -> CheckResult:
    return CheckResult(
        id=check_id, status=status, evidence="test", provider=provider, detail=detail
    )  # type: ignore[arg-type]


def test_no_booking_mailto_hook() -> None:
    checks = [
        _check("online_booking", "absent"),
        _check("contact_form", "absent", contact_is_mailto_only=True),
    ]
    hook = select_hook("cabinet-zen.fr", checks, competitor_locked=False, diy_tooling=False)
    assert hook is not None
    assert "cabinet-zen.fr" in hook
    assert "{prenom}" in hook  # littéral, jamais deviné
    assert hook.count("?") == 1  # une seule question ouverte
    assert "Seelo" not in hook


def test_diy_calendly_hook_mentions_provider() -> None:
    checks = [_check("online_booking", "present", provider="calendly")]
    hook = select_hook("cabinet-zen.fr", checks, competitor_locked=False, diy_tooling=True)
    assert hook is not None
    assert "Calendly" in hook


def test_competitor_locked_hook_mentions_provider() -> None:
    checks = [_check("online_booking", "present", provider="doctolib")]
    hook = select_hook("cabinet-zen.fr", checks, competitor_locked=True, diy_tooling=False)
    assert hook is not None
    assert "Doctolib" in hook


def test_prenom_is_used_when_provided() -> None:
    checks = [_check("pricing_visible", "absent")]
    hook = select_hook(
        "cabinet-zen.fr", checks, competitor_locked=False, diy_tooling=False, prenom="Julie"
    )
    assert hook is not None
    assert hook.startswith("Bonjour Julie")


def test_no_hook_when_nothing_dominant() -> None:
    checks = [
        _check("online_booking", "present", provider="acuity"),
        _check("pricing_visible", "present"),
        _check("mobile_experience", "present"),
    ]
    hook = select_hook("cabinet-zen.fr", checks, competitor_locked=False, diy_tooling=False)
    assert hook is None
