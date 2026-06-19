"""
Лёгкая загрузка .env (без зависимости python-dotenv) + общие хелперы.
import shared.config  # достаточно, чтобы .env подхватился
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | os.PathLike | None = None) -> None:
    """Простейший парсер .env: KEY=VALUE, # комментарии, пустые строки."""
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


# подхватываем .env при импорте
load_env()
