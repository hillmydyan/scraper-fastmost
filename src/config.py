"""Configuration loader for FastMoss Scraper"""
import os
from pathlib import Path
import yaml

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
STORAGE_DIR = BASE_DIR / "storage"
SESSIONS_DIR = STORAGE_DIR / "sessions"
OUTPUTS_DIR = STORAGE_DIR / "outputs"
LOGS_DIR = STORAGE_DIR / "logs"

# Ensure directories exist
for d in [STORAGE_DIR, SESSIONS_DIR, OUTPUTS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

DEFAULT_STORAGE_STATE_PATH = SESSIONS_DIR / "storage_state.json"
CACHE_DB_PATH = STORAGE_DIR / "cache.db"


def load_yaml(file_path: Path) -> dict:
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_selectors() -> dict:
    return load_yaml(CONFIG_DIR / "selectors.yaml")


def get_category_config() -> dict:
    return load_yaml(CONFIG_DIR / "kategori_target.yaml")

