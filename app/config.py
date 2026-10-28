"""Runtime configuration, read once from the environment."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL_FAST = "nvidia/Nemotron-3_5-Lightning"
DEFAULT_MODEL_DEEP = "nvidia/Nemotron-3-Ultra-550b-a55b"


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key) or default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (ROOT / p).resolve()


@dataclass(frozen=True)
class Settings:
    nebius_api_key: str
    nebius_base_url: str
    model_fast: str
    model_deep: str
    tavily_api_key: str
    data_dir: Path
    skills_dir: Path

    @property
    def db_path(self) -> Path:
        return self.data_dir / "mnemo.sqlite3"

    @property
    def nebius_ready(self) -> bool:
        return bool(self.nebius_api_key)

    @property
    def tavily_ready(self) -> bool:
        return bool(self.tavily_api_key)


def load_settings() -> Settings:
    s = Settings(
        nebius_api_key=os.getenv("NEBIUS_API_KEY", "").strip(),
        nebius_base_url=(os.getenv("NEBIUS_BASE_URL") or DEFAULT_BASE_URL).strip(),
        model_fast=(os.getenv("MNEMO_MODEL_FAST") or DEFAULT_MODEL_FAST).strip(),
        model_deep=(os.getenv("MNEMO_MODEL_DEEP") or DEFAULT_MODEL_DEEP).strip(),
        tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
        data_dir=_path("MNEMO_DATA_DIR", "./data"),
        skills_dir=_path("MNEMO_SKILLS_DIR", "./skills"),
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = load_settings()
