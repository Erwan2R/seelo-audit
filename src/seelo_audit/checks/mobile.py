"""Parcours mobile (poids 12) — ~80% du trafic du segment.

Contrairement aux autres checks, celui-ci a besoin d'une page Playwright déjà
rendue en contexte mobile (viewport iPhone 13) — il est donc appelé
séparément par le pipeline, pas via `checks.run_html_checks`.
"""

from __future__ import annotations

from typing import Any, Protocol

from seelo_audit.models import CheckResult, CheckStatus

BOOKING_CONTACT_VOCAB = (
    "rendez-vous",
    "rdv",
    "reserver",
    "reservation",
    "contact",
    "appeler",
    "prendre-rdv",
)
FIRST_SCREEN_HEIGHT_PX = 812
MIN_FONT_SIZE_PX = 14
MAX_SMALL_TOUCH_TARGET_RATIO = 0.3


class MobilePage(Protocol):
    async def evaluate(self, script: str, arg: Any = None) -> Any: ...


async def run(page: MobilePage) -> CheckResult:
    detail: dict[str, Any] = {}
    problems: list[str] = []

    viewport_meta = await page.evaluate(
        "() => { const m = document.querySelector('meta[name=viewport]');"
        " return m ? m.getAttribute('content') : null; }"
    )
    has_viewport = bool(viewport_meta and "width=device-width" in viewport_meta)
    detail["viewport_meta"] = viewport_meta
    if not has_viewport:
        problems.append("balise meta viewport absente ou incorrecte")

    overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth > window.innerWidth + 2"
    )
    detail["horizontal_overflow"] = overflow
    if overflow:
        problems.append("débordement horizontal détecté")

    base_font_size = await page.evaluate(
        "() => parseFloat(getComputedStyle(document.body).fontSize)"
    )
    detail["base_font_size_px"] = base_font_size
    if base_font_size and base_font_size < MIN_FONT_SIZE_PX:
        problems.append(f"taille de police de base trop petite ({base_font_size:.0f}px)")

    small_targets_ratio = await page.evaluate(
        """() => {
            const els = [...document.querySelectorAll('a, button')].filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            });
            if (els.length === 0) return 0;
            const small = els.filter(e => {
                const r = e.getBoundingClientRect();
                return r.height < 40 || r.width < 40;
            });
            return small.length / els.length;
        }"""
    )
    detail["small_touch_targets_ratio"] = small_targets_ratio
    if small_targets_ratio > MAX_SMALL_TOUCH_TARGET_RATIO:
        problems.append(f"{small_targets_ratio:.0%} des zones tactiles < 40px")

    cta_script = f"""(vocab) => {{
            const els = [...document.querySelectorAll('a, button')];
            return els.some(e => {{
                const text = (e.textContent || '').toLowerCase();
                const href = (e.getAttribute('href') || '').toLowerCase();
                if (!vocab.some(v => text.includes(v) || href.includes(v))) return false;
                const r = e.getBoundingClientRect();
                const ok = r.top >= 0 && r.top < {FIRST_SCREEN_HEIGHT_PX};
                return ok && r.width > 0 && r.height > 0;
            }});
        }}"""
    cta_above_fold = await page.evaluate(cta_script, list(BOOKING_CONTACT_VOCAB))
    detail["cta_above_fold"] = cta_above_fold
    if not cta_above_fold:
        problems.append("aucun CTA de réservation/contact visible dans le premier écran")

    status: CheckStatus
    if not problems:
        status = "present"
        evidence = "viewport correct, pas de débordement, CTA visible au premier écran"
    elif len(problems) >= 3 or not has_viewport:
        status = "absent"
        evidence = "; ".join(problems)
    else:
        status = "partial"
        evidence = "; ".join(problems)

    return CheckResult(
        id="mobile_experience", status=status, evidence=evidence[:500], detail=detail
    )
