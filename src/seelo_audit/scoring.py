"""Score de maturité du tunnel (0-100), température du lead, flags commerciaux."""

from __future__ import annotations

from typing import Literal

from seelo_audit.models import CheckResult, PageSpeedResult

Temperature = Literal["CHAUD", "TIEDE", "FROID"]

AXIS_WEIGHTS: dict[str, int] = {
    "online_booking": 25,
    "online_payment": 15,
    "pricing_visible": 12,
    "contact_form": 12,
    "mobile_experience": 12,
    "cancellation_policy": 8,
    "trust_signals": 10,
    "structured_data": 6,
}

STATUS_FRACTION = {"present": 1.0, "partial": 0.5, "absent": 0.0, "error": 0.0}

COMPETITOR_PROVIDERS = {"doctolib", "planity", "treatwell", "fresha", "booksy"}
DIY_TOOLING_PROVIDERS = {"calendly", "cal_com"}


def _fraction(check: CheckResult) -> float:
    if check.id == "trust_signals":
        return float(check.detail.get("score", STATUS_FRACTION[check.status]))
    return STATUS_FRACTION[check.status]


def compute_score(checks: list[CheckResult]) -> int:
    by_id = {c.id: c for c in checks}
    total = 0.0
    for check_id, weight in AXIS_WEIGHTS.items():
        check = by_id.get(check_id)
        if check is None:
            continue
        total += _fraction(check) * weight
    return round(total)


def compute_temperature(score: int, booking_check: CheckResult | None) -> Temperature:
    """CHAUD > TIÈDE > FROID, dans cet ordre de priorité (la spec définit des
    conditions qui se recoupent ; on applique l'ordre littéral de la spec)."""
    booking_status = booking_check.status if booking_check else "absent"

    if score < 40 and booking_status == "absent":
        return "CHAUD"
    if (40 <= score < 70) or booking_status == "partial":
        return "TIEDE"
    return "FROID"


def compute_flags(booking_check: CheckResult | None) -> tuple[bool, bool]:
    if booking_check is None or booking_check.status != "present":
        return False, False
    provider = booking_check.provider or ""
    return provider in COMPETITOR_PROVIDERS, provider in DIY_TOOLING_PROVIDERS


def performance_score(pagespeed: PageSpeedResult | None) -> int | None:
    if pagespeed is None or pagespeed.performance_score is None or pagespeed.seo_score is None:
        return None
    return round((pagespeed.performance_score + pagespeed.seo_score) / 2)


def top_frictions(checks: list[CheckResult], limit: int = 3) -> list[str]:
    by_id = {c.id: c for c in checks}
    ranked = [
        (_fraction(by_id[check_id]), check_id) for check_id in AXIS_WEIGHTS if check_id in by_id
    ]
    ranked.sort(key=lambda item: item[0])
    return [check_id for _fraction_value, check_id in ranked[:limit]]
