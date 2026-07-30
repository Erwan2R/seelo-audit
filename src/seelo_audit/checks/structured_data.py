"""Données structurées LocalBusiness (poids 6) — seul point SEO conservé (pack local Google)."""

from __future__ import annotations

import json
from typing import Any

from seelo_audit.checks.base import CrawlResult, PageDocument
from seelo_audit.models import CheckResult, CheckStatus

RELEVANT_TYPES = {
    "LocalBusiness",
    "HealthAndBeautyBusiness",
    "MedicalBusiness",
    "ProfessionalService",
    "Physician",
    "Person",
    "Organization",
}
IMPORTANT_FIELDS = (
    "name",
    "address",
    "telephone",
    "openingHoursSpecification",
    "priceRange",
    "aggregateRating",
    "geo",
    "image",
)


def _iter_json_ld(doc: PageDocument) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for script in doc.tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (ValueError, TypeError):
            continue
        if isinstance(data, list):
            blocks.extend(b for b in data if isinstance(b, dict))
        elif isinstance(data, dict):
            graph = data.get("@graph")
            if isinstance(graph, list):
                blocks.extend(b for b in graph if isinstance(b, dict))
            else:
                blocks.append(data)
    return blocks


def run(crawl: CrawlResult) -> CheckResult:
    for doc in crawl.all_documents():
        for block in _iter_json_ld(doc):
            type_value = block.get("@type")
            types = type_value if isinstance(type_value, list) else [type_value]
            if any(t in RELEVANT_TYPES for t in types if isinstance(t, str)):
                present_fields = [f for f in IMPORTANT_FIELDS if f in block]
                status: CheckStatus = "present" if len(present_fields) >= 4 else "partial"
                return CheckResult(
                    id="structured_data",
                    status=status,
                    evidence=f"@type={types} — champs : {', '.join(present_fields) or 'aucun'}",
                    detail={"type": types, "fields_present": present_fields},
                )

    return CheckResult(
        id="structured_data",
        status="absent",
        evidence="aucune donnée structurée LocalBusiness trouvée",
        detail={},
    )
