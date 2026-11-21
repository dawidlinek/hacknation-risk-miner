"""Runtime settings: env vars (.env) + config/config.yaml (feature flags, LLM, connectors)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(os.environ.get("RISKMINER_ROOT") or Path(__file__).resolve().parents[2])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(REPO_ROOT / ".env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://riskminer:riskminer@localhost:5434/riskminer"
    riskminer_config: str = str(REPO_ROOT / "config" / "config.yaml")
    data_dir: str = str(REPO_ROOT / "data")
    exports_dir: str = str(REPO_ROOT / "exports")
    catalogue_dir: str = str(REPO_ROOT / "catalogue")
    bzp_copy_path: str = str(
        REPO_ROOT / "materials/bzp_kopia/risk_miner_bzp_kopia/bzp_kopia/notices.jsonl"
    )
    organizer_xlsx_path: str = str(REPO_ROOT / "materials/starter/Risk_Miner_dane_projekty.xlsx")
    bzp_api_base: str = "https://ezamowienia.gov.pl"
    bzp_mirror_base: str = "https://bzp.cytr.us"
    user_agent: str = "RiskMiner-hackathon/0.1 (research prototype; HackNation 2026)"

    @property
    def raw_dir(self) -> Path:
        return Path(self.data_dir) / "raw"

    @property
    def ref_dir(self) -> Path:
        return Path(self.data_dir) / "ref"

    @property
    def dsn(self) -> str:
        """asyncpg DSN (no SQLAlchemy driver suffix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def settings() -> Settings:
    return Settings()


@lru_cache
def app_config() -> dict[str, Any]:
    """config/config.yaml, falling back to config/config.example.yaml."""
    p = Path(settings().riskminer_config)
    if not p.exists():
        p = REPO_ROOT / "config" / "config.example.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def feature(name: str, default: bool = False) -> bool:
    return bool((app_config().get("features") or {}).get(name, default))
