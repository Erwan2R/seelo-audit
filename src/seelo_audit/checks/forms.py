"""Formulaire de contact / première consultation (poids 12)."""

from __future__ import annotations

from selectolax.parser import Node

from seelo_audit.checks.base import CrawlResult, find_signature, load_signatures
from seelo_audit.config import SIGNATURES_PATH
from seelo_audit.models import CheckResult

FIELD_TAGS = ("input", "select", "textarea")
EXCLUDED_INPUT_TYPES = {"hidden", "submit"}
WORDPRESS_FORM_SELECTORS = (
    ".wpcf7",
    ".gform_wrapper",
    ".ninja-forms-form",
    ".wpforms-container",
    ".elementor-form",
)


def _count_fields(form: Node) -> int:
    count = 0
    for tag in form.css(",".join(FIELD_TAGS)):
        if tag.tag == "input":
            input_type = (tag.attributes.get("type") or "text").lower()
            if input_type in EXCLUDED_INPUT_TYPES:
                continue
        count += 1
    return count


def run(crawl: CrawlResult) -> CheckResult:
    signatures = load_signatures(SIGNATURES_PATH)
    documents = crawl.all_documents()

    embed_match = find_signature(signatures.get("forms_embed", []), documents)

    max_fields = 0
    native_email_form = False
    for doc in documents:
        for form in doc.tree.css("form"):
            has_email = (
                form.css_first("input[type=email]") is not None
                or form.css_first("[name*=mail]") is not None
            )
            if has_email:
                native_email_form = True
                max_fields = max(max_fields, _count_fields(form))

    wp_form_present = any(
        doc.tree.css_first(sel) is not None for doc in documents for sel in WORDPRESS_FORM_SELECTORS
    )

    mailto_count = sum(
        1
        for doc in documents
        for a in doc.tree.css("a[href]")
        if (a.attributes.get("href") or "").lower().startswith("mailto:")
    )

    if embed_match or native_email_form or wp_form_present:
        provider = embed_match.provider_id if embed_match else None
        evidence = (
            embed_match.label
            if embed_match
            else f"formulaire natif détecté ({max_fields} champ(s))"
            if native_email_form
            else "formulaire WordPress détecté"
        )
        return CheckResult(
            id="contact_form",
            status="present",
            provider=provider,
            evidence=evidence,
            detail={"field_count": max_fields, "contact_is_mailto_only": False},
        )

    if mailto_count > 0:
        return CheckResult(
            id="contact_form",
            status="absent",
            evidence=(f"aucun formulaire — {mailto_count} lien(s) mailto: uniquement pour contact"),
            detail={
                "field_count": 0,
                "contact_is_mailto_only": True,
                "mailto_count": mailto_count,
            },
        )

    return CheckResult(
        id="contact_form",
        status="absent",
        evidence="aucun formulaire ni lien mailto: détecté",
        detail={"field_count": 0, "contact_is_mailto_only": False},
    )
