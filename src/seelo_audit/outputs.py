"""Génération des sorties : un JSON par domaine + un CSV agrégé trié."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from seelo_audit.config import OUT_DIR
from seelo_audit.models import Audit, CheckResult
from seelo_audit.scoring import top_frictions

CSV_COLUMNS = [
    "domaine",
    "url",
    "statut_audit",
    "score_tunnel",
    "temperature",
    "plateforme",
    "booking_statut",
    "booking_provider",
    "competitor_locked",
    "diy_tooling",
    "paiement_statut",
    "tarifs_statut",
    "formulaire_statut",
    "formulaire_nb_champs",
    "contact_mailto_seul",
    "annulation_statut",
    "mobile_ok",
    "mobile_problemes",
    "confiance_score",
    "schema_localbusiness",
    "perf_score",
    "seo_score",
    "lcp_s",
    "blocage_principal",
    "top_3_frictions",
    "accroche_email",
    "date_audit",
]

FRICTION_LABELS = {
    "online_booking": "réservation en ligne",
    "online_payment": "paiement en ligne",
    "pricing_visible": "tarifs visibles",
    "contact_form": "formulaire de contact",
    "mobile_experience": "parcours mobile",
    "cancellation_policy": "politique d'annulation",
    "trust_signals": "signaux de confiance",
    "structured_data": "données structurées",
}

_TEMPERATURE_ORDER = {"CHAUD": 0, "TIEDE": 1, "FROID": 2, "EXCLU": 3}


def write_audit_json(audit: Audit) -> Path:
    out_path = OUT_DIR / "audits" / f"{audit.domain}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(audit.model_dump_json(indent=2), encoding="utf-8")
    return out_path


def _by_id(audit: Audit, check_id: str) -> CheckResult | None:
    return next((c for c in audit.checks if c.id == check_id), None)


def audit_to_row(audit: Audit) -> dict[str, Any]:
    booking = _by_id(audit, "online_booking")
    payment = _by_id(audit, "online_payment")
    pricing = _by_id(audit, "pricing_visible")
    forms = _by_id(audit, "contact_form")
    mobile = _by_id(audit, "mobile_experience")
    policy = _by_id(audit, "cancellation_policy")
    trust = _by_id(audit, "trust_signals")
    structured = _by_id(audit, "structured_data")

    frictions = top_frictions(audit.checks)
    friction_labels = " | ".join(FRICTION_LABELS.get(f, f) for f in frictions)

    lcp_s: str | float = ""
    if audit.pagespeed and audit.pagespeed.lcp_ms is not None:
        lcp_s = round(audit.pagespeed.lcp_ms / 1000, 2)

    blocage_principal = friction_labels
    if audit.visual_diagnostic is not None:
        blocage_principal = audit.visual_diagnostic.biggest_conversion_blocker

    return {
        "domaine": audit.domain,
        "url": str(audit.url),
        "statut_audit": audit.status,
        "score_tunnel": audit.score_tunnel,
        "temperature": audit.temperature,
        "plateforme": audit.platform or "",
        "booking_statut": booking.status if booking else "",
        "booking_provider": booking.provider or "" if booking else "",
        "competitor_locked": audit.competitor_locked,
        "diy_tooling": audit.diy_tooling,
        "paiement_statut": payment.status if payment else "",
        "tarifs_statut": pricing.status if pricing else "",
        "formulaire_statut": forms.status if forms else "",
        "formulaire_nb_champs": forms.detail.get("field_count", "") if forms else "",
        "contact_mailto_seul": forms.detail.get("contact_is_mailto_only", "") if forms else "",
        "annulation_statut": policy.status if policy else "",
        "mobile_ok": (mobile.status == "present") if mobile else "",
        "mobile_problemes": mobile.evidence if mobile and mobile.status != "present" else "",
        "confiance_score": trust.detail.get("score", "") if trust else "",
        "schema_localbusiness": structured.status if structured else "",
        "perf_score": audit.pagespeed.performance_score if audit.pagespeed else "",
        "seo_score": audit.pagespeed.seo_score if audit.pagespeed else "",
        "lcp_s": lcp_s,
        "blocage_principal": blocage_principal,
        "top_3_frictions": friction_labels,
        "accroche_email": audit.outreach_hook or "",
        "date_audit": audit.audited_at.date().isoformat(),
    }


def write_report_csv(audits: list[Audit]) -> Path:
    out_path = OUT_DIR / "report.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sorted_audits = sorted(
        audits, key=lambda a: (_TEMPERATURE_ORDER.get(a.temperature, 9), a.score_tunnel)
    )
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, delimiter=";")
        writer.writeheader()
        for audit in sorted_audits:
            writer.writerow(audit_to_row(audit))
    return out_path
