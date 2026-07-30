# Image officielle Playwright : Chromium + dépendances système déjà installés
# et appariés à une version précise de `playwright` — ne PAS laisser pip/uv
# résoudre une autre version du paquet Python, sous peine d'incompatibilité
# avec les binaires du navigateur déjà présents dans l'image.
FROM mcr.microsoft.com/playwright/python:v1.61.0-jammy

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY data ./data

RUN pip install --no-cache-dir "playwright==1.61.0" ".[api]"

COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV APP_ENV_FILE=/run/secrets/app_env

EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "seelo_audit.api:app", "--host", "0.0.0.0", "--port", "8000"]
