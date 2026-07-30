from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

def _find_project_root() -> Path:
    # En dev (install editable), le code tourne depuis le repo -> data/ est
    # 2 niveaux au-dessus de ce fichier. Une fois pip-installe dans une image
    # Docker (site-packages), ce chemin n'existe plus : on retombe sur le
    # repertoire courant, la ou le Dockerfile a copie data/ (WORKDIR /app).
    candidate = Path(__file__).resolve().parents[2]
    if (candidate / "data").exists():
        return candidate
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
DATA_DIR = PROJECT_ROOT / "data"
OUT_DIR = PROJECT_ROOT / "out"
CACHE_DIR = PROJECT_ROOT / "cache"
SIGNATURES_PATH = DATA_DIR / "signatures.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    pagespeed_api_key: str | None = Field(default=None, alias="PAGESPEED_API_KEY")
    max_concurrency: int = Field(default=5, alias="MAX_CONCURRENCY")
    cache_ttl_days: int = Field(default=30, alias="CACHE_TTL_DAYS")
    user_agent: str = Field(default="SeeloAuditBot/1.0 (+https://seelo.fr/bot)", alias="USER_AGENT")

    # Timeouts (secondes)
    fetch_timeout_s: float = 15.0
    playwright_timeout_s: float = 30.0
    pagespeed_timeout_s: float = 60.0
    audit_timeout_s: float = 180.0

    # Limites
    max_response_bytes: int = 5 * 1024 * 1024
    max_pages_crawled: int = 6
    crawl_delay_s: float = 1.0
    max_redirects: int = 5


settings = Settings()
