from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from seelo_audit.models import Audit, CheckResult
from seelo_audit.outputs import CSV_COLUMNS, write_report_csv


def _audit(domain: str, score: int, temperature: str) -> Audit:
    return Audit(
        domain=domain,
        url=f"https://{domain}/",  # type: ignore[arg-type]
        audited_at=datetime.now(UTC),
        status="ok",
        checks=[CheckResult(id="online_booking", status="absent", evidence="test")],
        score_tunnel=score,
        temperature=temperature,  # type: ignore[arg-type]
    )


@pytest.fixture
def tmp_out_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("seelo_audit.outputs.OUT_DIR", tmp_path)
    return tmp_path


def test_csv_is_utf8_sig_with_semicolon_delimiter(tmp_out_dir: Path) -> None:
    audits = [_audit("chaud.fr", 20, "CHAUD")]
    path = write_report_csv(audits)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM utf-8-sig
    text = raw.decode("utf-8-sig")
    header = text.splitlines()[0]
    assert header.split(";") == CSV_COLUMNS


def test_csv_sorted_by_temperature_then_score(tmp_out_dir: Path) -> None:
    audits = [
        _audit("froid.fr", 90, "FROID"),
        _audit("chaud-haut.fr", 30, "CHAUD"),
        _audit("chaud-bas.fr", 10, "CHAUD"),
        _audit("tiede.fr", 50, "TIEDE"),
    ]
    path = write_report_csv(audits)
    lines = path.read_text(encoding="utf-8-sig").splitlines()[1:]
    domains = [line.split(";")[0] for line in lines]
    assert domains == ["chaud-bas.fr", "chaud-haut.fr", "tiede.fr", "froid.fr"]
