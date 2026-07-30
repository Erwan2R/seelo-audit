"""Accroches d'outreach — gabarits déterministes, jamais générées par un LLM.

Règles imposées par la spec : pas de pitch produit, pas de mention de Seelo,
une seule question ouverte, moins de 60 mots. L'accroche va dans le CSV, elle
n'est jamais envoyée automatiquement par l'outil.
"""

from __future__ import annotations

from seelo_audit.models import CheckResult

TEMPLATES: dict[str, str] = {
    "no_booking_mailto": (
        "Bonjour {prenom}, en regardant {domaine} j'ai vu que la prise de "
        "rendez-vous passe uniquement par mail. Sur ce format, une bonne partie "
        "des demandes se perd entre le premier message et la confirmation. "
        "Est-ce que c'est quelque chose que vous constatez ?"
    ),
    "diy_calendly": (
        "Bonjour {prenom}, j'ai vu que vous utilisez {provider} pour vos "
        "rendez-vous sur {domaine}. La question que je me pose : comment vous "
        "gérez l'acompte et la facturation derrière ?"
    ),
    "competitor_locked": (
        "Bonjour {prenom}, j'ai vu que vos rendez-vous passent par {provider}. "
        "Sur la part de vos clients qui vous connaissent déjà et qui réservent "
        "quand même par là, la commission tombe aussi. Vous avez chiffré ce que "
        "ça représente sur l'année ?"
    ),
    "no_pricing": (
        "Bonjour {prenom}, sur {domaine} je n'ai pas trouvé vos tarifs. "
        "C'est un choix assumé, ou c'est resté en suspens ? Je demande parce que "
        "ça change beaucoup le type de demandes que vous recevez."
    ),
    "mobile_broken": (
        "Bonjour {prenom}, j'ai ouvert {domaine} sur mobile et {probleme_precis}. "
        "Sur votre activité c'est là que passe l'essentiel du trafic — ça vaut "
        "sans doute le coup d'y jeter un œil."
    ),
}

PROVIDER_LABELS = {
    "calendly": "Calendly",
    "cal_com": "Cal.com",
    "doctolib": "Doctolib",
    "planity": "Planity",
    "treatwell": "Treatwell",
    "fresha": "Fresha",
    "booksy": "Booksy",
}


def _by_id(checks: list[CheckResult], check_id: str) -> CheckResult | None:
    return next((c for c in checks if c.id == check_id), None)


def select_hook(
    domain: str,
    checks: list[CheckResult],
    competitor_locked: bool,
    diy_tooling: bool,
    prenom: str | None = None,
) -> str | None:
    """Sélectionne le gabarit selon la friction dominante. `prenom` vient de la
    liste d'entrée si fourni ; sinon `{prenom}` reste littéral (jamais deviné)."""
    booking = _by_id(checks, "online_booking")
    forms = _by_id(checks, "contact_form")
    pricing = _by_id(checks, "pricing_visible")
    mobile = _by_id(checks, "mobile_experience")

    prenom_value = prenom or "{prenom}"

    if (
        booking
        and booking.status == "absent"
        and forms
        and forms.detail.get("contact_is_mailto_only")
    ):
        return TEMPLATES["no_booking_mailto"].format(prenom=prenom_value, domaine=domain)

    if diy_tooling and booking:
        provider_label = PROVIDER_LABELS.get(
            booking.provider or "", booking.provider or "l'outil détecté"
        )
        return TEMPLATES["diy_calendly"].format(
            prenom=prenom_value, domaine=domain, provider=provider_label
        )

    if competitor_locked and booking:
        provider_label = PROVIDER_LABELS.get(
            booking.provider or "", booking.provider or "la plateforme détectée"
        )
        return TEMPLATES["competitor_locked"].format(prenom=prenom_value, provider=provider_label)

    if pricing and pricing.status == "absent":
        return TEMPLATES["no_pricing"].format(prenom=prenom_value, domaine=domain)

    if mobile and mobile.status != "present":
        probleme = (
            mobile.evidence.split(";")[0].strip()
            if mobile.evidence
            else "certains éléments ne s'affichent pas correctement"
        )
        return TEMPLATES["mobile_broken"].format(
            prenom=prenom_value, domaine=domain, probleme_precis=probleme
        )

    return None
