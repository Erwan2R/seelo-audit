# Décisions techniques

## §10 — Passe "vision" : déterministe, pas de LLM (2026-07-30)

La spec d'origine prévoit un appel Claude (vision) pour 7 critères visuels
(proposition de valeur, CTA, photo, lisibilité, hiérarchie, professionnalisme,
parcours mobile). Décision du client : **aucun appel à un LLM externe**, quel
que soit le fournisseur — pas une question de coût (négligeable, quelques
dollars pour 500 sites), mais un choix délibéré de ne pas dépendre d'une API
tierce pour cette fonctionnalité.

Remplacement dans `vision.py` :

| Critère spec | Implémentation |
|---|---|
| CTA visible sans scroll | Déjà déterministe dans `checks/mobile.py` (position DOM vs. fold) |
| Lisibilité (contraste, taille police, longueur de ligne) | Calcul direct via `getComputedStyle` (Playwright) + formule de contraste WCAG |
| Photo du praticien (visage) | Détection de visage OpenCV (Haar cascade), locale, gratuite, aucun réseau |
| Hiérarchie visuelle / densité | Heuristique : nombre de titres, profondeur DOM, ratio texte/image |
| Clarté de la proposition de valeur | Heuristique : présence d'un H1, longueur du texte au-dessus de la ligne de flottaison — **dégradé** par rapport à un jugement LLM, documenté comme limite connue |
| Cohérence / professionnalisme | Heuristique : nombre de couleurs dominantes extraites du screenshot (clustering k-means), nombre de familles de polices |

**Limite assumée** : les critères "clarté du message" et "cohérence visuelle"
perdent en finesse (proxy structurel plutôt que jugement sémantique/esthétique).
Le champ `biggest_conversion_blocker` du modèle `VisualDiagnostic` est déduit du
critère au verdict le plus faible plutôt que généré en langage libre.

Conséquence sur la stack : `anthropic` retiré des dépendances, aucune clé API
LLM dans `.env`. `opencv-python-headless` ajouté pour la détection de visage.

**Nommage — pas de titre trompeur (demandé explicitement par le client 2026-07-30) :**
Le module et les modèles de données sont renommés pour ne jamais suggérer une
analyse par IA : `vision.py` de la spec devient `visual_diagnostics.py`,
`VisionResult`/`VisionCriterion` deviennent `VisualDiagnostic`/`VisualCriterion`,
le champ `Audit.vision` devient `Audit.visual_diagnostic`. Chaque `VisualCriterion`
porte un champ `method: Literal["regle_deterministe", "heuristique_proxy"]`
explicite. Le README et le JSON de sortie affichent le libellé **"Diagnostic
visuel automatique (règles, sans IA)"** — jamais "analyse IA", "vision par
intelligence artificielle" ou équivalent. Objectif : que quiconque lit le
rapport (Erwan, ou plus tard un praticien en v2) comprenne immédiatement la
nature et les limites de ce qui a été vérifié, sans survente.

## opencv-python-headless épinglé à `<5` (2026-07-30)

Testé en conditions réelles sur de vrais sites de praticiens (labullesophro.com,
marinamerley-naturopathe-paris.com, etc.) : la version 5.0.0 d'opencv-python-headless
a supprimé `cv2.CascadeClassifier` (détection de visage par cascades de Haar,
bundlée gratuitement via `cv2.data.haarcascades`) au profit d'un détecteur DNN
(`cv2.FaceDetectorYN`) qui nécessite de télécharger un modèle ONNX externe — ce
qui casserait l'exigence "aucune dépendance réseau" du diagnostic visuel.
Épinglé `opencv-python-headless>=4.10,<5` pour garder les cascades de Haar
embarquées. À réévaluer si une version 5.x réintroduit un détecteur embarqué
sans téléchargement.

## Bandeaux cookies — liste de sélecteurs étendue (2026-07-30)

Trouvé en testant sur un vrai site (labullesophro.com) : son bandeau cookie
utilise le bouton "Autoriser", absent de la liste initiale de la spec
(`Tout accepter`, `Accepter`, `J'accepte`, `OK`, `Accept all`, `Continuer sans
accepter`). Ajouté "Autoriser", "Tout autoriser", "Accepter tout", "J'accepte
tout" à `screenshots.COOKIE_BANNER_SELECTORS`. Vérifié après coup que le
bandeau disparaît bien de la capture desktop et mobile.

## v2 — service HTTP public pour `/audit-site` (2026-07-30)

Le client a demandé d'exposer l'audit comme lead magnet public sur
`leadmagnet.seelo.fr/audit-site`, alors que la spec d'origine (§18) prévoyait
explicitement de ne pas construire cette partie tout de suite. Décisions
prises pour cette extension (détail complet dans le plan d'implémentation
de la conversation) :

- **File d'attente en mémoire, pas de Redis/RQ.** `src/seelo_audit/api.py`
  garde les jobs dans un `dict` Python + `asyncio.Semaphore(2)` pour limiter
  la charge Playwright. Limite assumée : un redémarrage du service pendant un
  audit fait perdre ce job (le visiteur doit relancer) — acceptable vu le
  volume attendu d'un lead magnet.
- **Aucune exposition publique du service Python.** Pas de règle Traefik sur
  `docker-compose.yml` — le service n'est joignable que depuis le réseau
  interne `seelo_proxy`, appelé uniquement par le conteneur Next.js de
  landing-leadmagnets (alias réseau `seelo-audit`). Les screenshots transitent
  via un relais côté Next.js, jamais servis directement au navigateur.
- **Gate d'accès réutilisé, pas de nouveau mécanisme.** Le site protège déjà
  ses outils via `src/proxy.ts` (cookie `seelo_lm_access` posé après
  validation d'un lien emailé) — `/audit-site` a simplement été ajouté à la
  liste des routes protégées, aucune capture d'email dédiée à cet outil.
- **Rate-limiting par IP côté Next.js, pas côté service Python** — seul le
  serveur Next.js voit l'IP réelle du visiteur (le service Python ne verrait
  que l'IP du conteneur Next.js).
- **Image Docker `mcr.microsoft.com/playwright/python:v1.61.0-jammy`** —
  Chromium et ses dépendances système sont déjà appariés à cette version
  précise de `playwright` dans l'image ; le `Dockerfile` épingle
  `playwright==1.61.0` explicitement pour ne jamais laisser pip résoudre une
  version différente de celle des binaires déjà présents dans l'image.
- **Repo et pipeline de déploiement séparés** de landing-leadmagnets, copiés
  à l'identique (GitHub Actions → build/push Scaleway → SSH → `docker stack
  deploy`) pour ne prendre aucun risque sur le déploiement du site principal.
- **Limite connue non résolue** : `pipeline.audit_one` écrit les screenshots
  dans `out/screenshots/{domaine}/` (pas par identifiant de job) — deux
  audits simultanés sur exactement le même domaine pourraient se marcher
  dessus sur les fichiers image. Risque jugé négligeable vu le
  `Semaphore(2)` et le volume attendu ; non corrigé pour ne pas toucher au
  cœur de `pipeline.py`, déjà testé et stable.

## Autres décisions

(à compléter au fil de l'implémentation)
