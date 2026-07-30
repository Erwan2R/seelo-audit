"""Signaux de confiance (poids 10) — moyenne de 8 sous-checks indépendants."""

from __future__ import annotations

import re
from typing import Any

from seelo_audit.checks.base import CrawlResult, find_signature, load_signatures, normalize_text
from seelo_audit.config import SIGNATURES_PATH
from seelo_audit.models import CheckResult, CheckStatus

SIRET_RE = re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}\s?\d{5}\b|\b\d{9}\s?\d{5}\b")
POSTAL_CODE_RE = re.compile(r"\b\d{5}\b")
CERT_KEYWORDS = (
    "rncp",
    "qualiopi",
    "certifie",
    "diplome",
    "chambre syndicale de la sophrologie",
    "societe francaise de sophrologie",
    "fenahman",
    "omnes",
    "adnr",
    "arche",
    "institut de formation",
    "titre professionnel",
)
REVIEW_KEYWORDS = ("avis", "temoignages", "ils m'ont fait confiance")


def _find_keyword(combined_norm: str, keywords: tuple[str, ...]) -> str | None:
    for kw in keywords:
        if normalize_text(kw) in combined_norm:
            return kw
    return None


def run(crawl: CrawlResult) -> CheckResult:
    documents = crawl.all_documents()
    signatures = load_signatures(SIGNATURES_PATH)
    combined_norm = " ".join(doc.visible_text_normalized for doc in documents)

    subchecks: dict[str, dict[str, Any]] = {}

    kw = _find_keyword(combined_norm, ("mentions legales",))
    subchecks["legal_notice"] = {"present": kw is not None, "evidence": kw or ""}

    kw = _find_keyword(
        combined_norm, ("politique de confidentialite", "rgpd", "donnees personnelles")
    )
    subchecks["privacy_policy"] = {"present": kw is not None, "evidence": kw or ""}

    kw = _find_keyword(combined_norm, ("cgv", "conditions generales"))
    subchecks["terms"] = {"present": kw is not None, "evidence": kw or ""}

    siret_match = next(
        (m.group(0) for doc in documents if (m := SIRET_RE.search(doc.visible_text))), None
    )
    subchecks["siret"] = {"present": siret_match is not None, "evidence": siret_match or ""}

    reviews_signature = find_signature(signatures.get("trust_reviews", []), documents)
    kw = _find_keyword(combined_norm, REVIEW_KEYWORDS)
    reviews_present = reviews_signature is not None or kw is not None
    subchecks["reviews"] = {
        "present": reviews_present,
        "evidence": reviews_signature.label if reviews_signature else (kw or ""),
    }

    kw = _find_keyword(combined_norm, CERT_KEYWORDS)
    subchecks["certifications"] = {"present": kw is not None, "evidence": kw or ""}

    address_present = any(
        POSTAL_CODE_RE.search(doc.visible_text) or "google.com/maps/embed" in doc.html.lower()
        for doc in documents
    )
    subchecks["address"] = {
        "present": address_present,
        "evidence": "code postal ou Google Maps embed détecté" if address_present else "",
    }

    phone_present = any(
        (a.attributes.get("href") or "").lower().startswith("tel:")
        for doc in documents
        for a in doc.tree.css("a[href]")
    )
    subchecks["phone"] = {
        "present": phone_present,
        "evidence": "lien tel: détecté" if phone_present else "",
    }

    score = sum(1 for v in subchecks.values() if v["present"]) / len(subchecks)
    status: CheckStatus = "present" if score >= 0.625 else "partial" if score > 0 else "absent"
    present_keys = [k for k, v in subchecks.items() if v["present"]]
    labels = ", ".join(present_keys) or "aucun"
    evidence = f"{len(present_keys)}/{len(subchecks)} signaux présents : {labels}"

    return CheckResult(
        id="trust_signals",
        status=status,
        evidence=evidence,
        detail={"score": round(score, 3), "subchecks": subchecks},
    )
