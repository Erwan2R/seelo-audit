# seelo-audit

Auditeur du tunnel de réservation des sites web de praticiens indépendants du
bien-être (sophrologues, coachs, naturopathes, hypnothérapeutes). Donne une
liste d'URLs, récupère un CSV qualifié avec un score, les frictions détectées
et une accroche de premier contact pré-rédigée — pour de la prospection
outbound interne (usage v1).

## Ce que l'outil peut faire

- Détecter la réservation en ligne (Calendly, Doctolib, Wix Bookings, plugins
  WordPress, etc.), le paiement en ligne, les tarifs visibles, la nature du
  formulaire de contact (ou son absence), la politique d'annulation, les
  signaux de confiance, les données structurées LocalBusiness et la
  plateforme technique — **tout ceci de façon 100% déterministe** (parsing
  HTML/DOM/CSS, aucune supposition).
- Auditer le parcours mobile (viewport, débordement horizontal, taille des
  zones tactiles, position du CTA) via un vrai navigateur (Playwright).
- Calculer un score de maturité du tunnel (0-100), une température de lead
  (CHAUD/TIÈDE/FROID/EXCLU) et des flags commerciaux (`competitor_locked`,
  `diy_tooling`).
- Générer une accroche de premier contact à partir de gabarits fixes (jamais
  de génération libre).
- Produire un **diagnostic visuel automatique (règles, sans IA)** sur 7
  critères — voir la section limites ci-dessous, c'est le point le plus
  important à lire avant d'utiliser le rapport.
- Interroger PageSpeed Insights (optionnel, nécessite une clé Google).

## Ce que l'outil ne fait PAS (et pourquoi)

**Pas d'intelligence artificielle, nulle part dans le pipeline.** C'est un
choix délibéré du client (2026-07-30), pas une question de coût. Concrètement,
ça change une chose : la spec technique d'origine prévoyait un appel à un
modèle de vision (Claude) pour juger 7 critères visuels d'un coup d'œil
humain. Ce module (`visual_diagnostics.py`, libellé **"Diagnostic visuel
automatique (règles, sans IA)"** partout où il apparaît) a été reconstruit
sans aucun appel réseau à un fournisseur d'IA :

| Critère | Fiabilité sans IA |
|---|---|
| CTA visible sans scroll, parcours mobile | ✅ Aussi fiable — calcul DOM/CSS exact |
| Lisibilité (contraste, taille de police) | ✅ Aussi fiable, voire plus rigoureux (calcul WCAG réel plutôt qu'une impression) |
| Photo du praticien | 🟡 Détection de visage (OpenCV, locale) — dit s'il y a un visage humain, pas si c'est vraiment le praticien ni la qualité de la photo |
| Hiérarchie visuelle / densité | 🟡 Proxy structurel (nombre de titres, profondeur du DOM) — pas un vrai jugement visuel |
| Cohérence / professionnalisme | 🟡 Proxy (nombre de couleurs dominantes sur le screenshot) — signal de désordre, pas un jugement esthétique |
| **Clarté du message en 5 secondes** | 🔴 **Limite assumée.** Aucun proxy structurel ne remplace correctement le jugement humain "je comprends qui/quoi/pour qui en un coup d'œil". Le champ reste rempli mais dit explicitement qu'il n'a pas pu juger ça |

Chaque critère du JSON de sortie porte un champ `method` (`regle_deterministe`
ou `heuristique_proxy`) pour qu'on sache toujours ce qui a été réellement
vérifié. Détail complet dans `DECISIONS.md`.

**Autres limites, héritées de la spec v1 :**
- Pas d'interface web, pas d'envoi d'email, pas de base de données.
- Pas d'analyse SEO exhaustive (uniquement les données structurées
  LocalBusiness, seul point ayant un effet mesurable sur ce segment).
- Le crawl est limité à la page d'accueil + 6 pages internes maximum.
- PageSpeed est optionnel : sans clé API, `pagespeed: null` dans le JSON,
  jamais bloquant.

## Installation

```bash
uv sync --extra dev
uv run playwright install chromium
cp .env.example .env   # remplir PAGESPEED_API_KEY si tu en as une (optionnel)
```

## Utilisation

```bash
# Audite une liste d'URLs (CSV ou TXT, une URL par ligne/par première colonne)
uv run seelo-audit run data/input/mes_urls.csv

# Réaudite même si un résultat récent existe déjà
uv run seelo-audit run data/input/mes_urls.csv --force

# Sans Playwright : plus rapide, mais pas de screenshots ni de check mobile
uv run seelo-audit run data/input/mes_urls.csv --no-browser

# Vide le cache et les vieux résultats (> 90 jours par défaut)
uv run seelo-audit purge --older-than 90d
```

Sorties : `out/audits/{domaine}.json` (un par site) et `out/report.csv`
(agrégé, trié par température puis score croissant — le premier prospect à
appeler est en ligne 2). CSV en `utf-8-sig` séparé par `;` pour Excel FR.

## Conformité

- User-Agent identifiable (`SeeloAuditBot/1.0 (+https://seelo.fr/bot)`),
  aucun spoofing de navigateur pour le fetch HTTP.
- `robots.txt` respecté pour le crawl des pages internes (la page d'accueil
  est toujours auditée — c'est une consultation, pas une indexation).
- Rythme poli : 1 requête/seconde max par domaine.
- Le CSV contient des données professionnelles publiques (prospection B2B).
  La prospection par email reste soumise à l'obligation de mentionner
  l'origine des données et un moyen d'opposition simple — cette obligation
  porte sur l'outil d'envoi (pas encore construit), pas sur cet auditeur.
- Minimisation : pas de scraping d'emails/téléphones personnels au-delà de ce
  qui est publiquement affiché sur le site audité lui-même.

## Service HTTP (v2 — lead magnet public `/audit-site`)

En plus du CLI, `src/seelo_audit/api.py` expose `pipeline.audit_one` via une
API FastAPI interne (jamais publique), consommée par la route
`/audit-site` de `landing-leadmagnets`. Fonctionnement : `POST /audits`
démarre un job en tâche de fond (file en mémoire, 2 audits simultanés max),
`GET /audits/{id}` renvoie son statut/résultat, `GET
/audits/{id}/screenshots/{desktop|mobile}` sert les captures.

```bash
uv sync --extra api
uv run uvicorn seelo_audit.api:app --reload --port 8000
```

Déploiement : `Dockerfile` + `docker-compose.yml` + `.github/workflows/deploy.yml`
répliquent le pipeline déjà utilisé par `landing-leadmagnets` (build Docker
via GitHub Actions, aucun Docker local requis). Voir `DECISIONS.md` pour le
détail des choix (file en mémoire, pas d'exposition publique, etc.).

## Développement

```bash
uv run pytest          # 56 tests (sécurité SSRF, checks, scoring, CSV, outreach)
uv run ruff check .
uv run ruff format .
uv run mypy src/       # strict, doit passer sans erreur
```

Voir `DECISIONS.md` pour l'historique des arbitrages techniques (dont le
retrait de l'IA et le passage en diagnostic 100% déterministe/heuristique).
