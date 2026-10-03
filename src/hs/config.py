"""Paths and YAML config. Config and content live in the repo; data lives in HS_HOME (default: repo root)."""

import os
from functools import cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
CONTENT = REPO / "content"


def home() -> Path:
    return Path(os.environ.get("HS_HOME", REPO))


def data_dir() -> Path:
    return home() / "data"


def inbox_dir() -> Path:
    d = home() / "inbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return home() / "hs.db"


def day_dir(date: str, student: str) -> Path:
    d = data_dir() / date / student
    d.mkdir(parents=True, exist_ok=True)
    return d


@cache
def settings() -> dict:
    return yaml.safe_load((CONFIG / "settings.yaml").read_text())


@cache
def students() -> dict[str, dict]:
    cfg = yaml.safe_load((CONFIG / "students.yaml").read_text())
    return {s["id"]: s for s in cfg["students"]}


@cache
def skills(subject: str = "math") -> list[dict]:
    """Skills in teaching order, each with id, name, strand, grade, form, levels."""
    return yaml.safe_load((CONTENT / subject / "skills.yaml").read_text())["skills"]


def skill(skill_id: str, subject: str = "math") -> dict:
    return next(s for s in skills(subject) if s["id"] == skill_id)


@cache
def curriculum(subject: str = "math") -> list[dict]:
    """K-12 scope and sequence: grades in order, each with topics in teaching order."""
    return yaml.safe_load((CONTENT / subject / "curriculum.yaml").read_text())["grades"]
