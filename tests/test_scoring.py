from __future__ import annotations

import pytest

from seelo_audit.models import CheckResult
from seelo_audit.scoring import compute_flags, compute_temperature

pytestmark = pytest.mark.filterwarnings("ignore")


def _booking(status: str, provider: str | None = None) -> CheckResult:
    return CheckResult(id="online_booking", status=status, evidence="test", provider=provider)  # type: ignore[arg-type]


# Table de vérité — voir §11.2 de la spec. L'ordre de priorité retenu est
# CHAUD > TIÈDE > FROID (les conditions de la spec se recoupent, voir
# scoring.compute_temperature pour la justification).
@pytest.mark.parametrize(
    ("score", "booking_status", "expected"),
    [
        (10, "absent", "CHAUD"),
        (39, "absent", "CHAUD"),
        (40, "absent", "TIEDE"),  # score n'est plus < 40
        (10, "partial", "TIEDE"),  # booking partial force TIEDE quel que soit le score
        (69, "partial", "TIEDE"),
        (50, "absent", "TIEDE"),
        (69, "absent", "TIEDE"),
        (70, "absent", "FROID"),
        (90, "present", "FROID"),
        (0, "present", "FROID"),  # booking present -> jamais CHAUD, ni TIEDE ici
    ],
)
def test_temperature_truth_table(score: int, booking_status: str, expected: str) -> None:
    booking_check = _booking(booking_status)
    assert compute_temperature(score, booking_check) == expected


def test_temperature_none_booking_check_treated_as_absent() -> None:
    assert compute_temperature(10, None) == "CHAUD"


def test_flags_competitor_locked_for_doctolib() -> None:
    booking_check = _booking("present", provider="doctolib")
    competitor_locked, diy_tooling = compute_flags(booking_check)
    assert competitor_locked is True
    assert diy_tooling is False


def test_flags_diy_tooling_for_calendly() -> None:
    booking_check = _booking("present", provider="calendly")
    competitor_locked, diy_tooling = compute_flags(booking_check)
    assert competitor_locked is False
    assert diy_tooling is True


def test_flags_absent_booking_never_flagged() -> None:
    booking_check = _booking("absent")
    competitor_locked, diy_tooling = compute_flags(booking_check)
    assert (competitor_locked, diy_tooling) == (False, False)
