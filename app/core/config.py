"""Application settings (environment variables) and versioned configuration loading."""
from __future__ import annotations

import functools
import hashlib
import json
import os
import subprocess
from pathlib import Path

import yaml

APP_NAME = "RH-OB Process Control and Digital Twin"
MODEL_VERSION = "1.0.0-demo"
API_VERSION = "v1"
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BASE_DIR / "config"
DATASET_DIR = BASE_DIR / "datasets"
MATURITY_GATE = "A"  # Gate A - software complete (engineering demonstration)
SYNTHETIC_BANNER = "SYNTHETIC DATA - ENGINEERING DEMONSTRATION - NOT VALIDATED FOR PLANT OPERATION - NOT CONNECTED TO PLANT CONTROLS"


class Settings:
    def __init__(self):
        self.env = os.getenv("RHOB_ENV", "demo")
        self.database_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR.parent / 'rhob_demo.db'}")
        if self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql://", 1)
        self.allowed_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
        self.token_secret = os.getenv("RHOB_TOKEN_SECRET", "")
        self.demo_auth = os.getenv("RHOB_DEMO_AUTH", "true").lower() == "true"
        self.max_sessions = int(os.getenv("RHOB_MAX_SESSIONS", "40"))
        self.closed_loop_feature = os.getenv("RHOB_ENABLE_CLOSED_LOOP_EDGE", "false").lower() == "true"
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or _git_sha()


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR.parent,
                                       stderr=subprocess.DEVNULL, timeout=2).decode().strip()
    except Exception:
        return "source-" + source_hash()[:12]


@functools.lru_cache(maxsize=1)
def source_hash() -> str:
    """SHA-256 over the physics + orchestration source tree (reproducibility fingerprint)."""
    h = hashlib.sha256()
    for sub in ["physics", "orchestration", "estimation", "optimization", "ml", "schemas"]:
        for p in sorted((BASE_DIR / sub).glob("*.py")):
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@functools.lru_cache(maxsize=1)
def _grades_raw():
    with open(CONFIG_DIR / "grades_demo.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_grades():
    from ..schemas.configuration import GradeCard
    return [GradeCard(**g) for g in _grades_raw()["grades"]]


def grades_version() -> str:
    return _grades_raw().get("version", "unknown")


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def checksum(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
