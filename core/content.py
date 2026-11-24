"""Lectura de contenido Markdown con frontmatter YAML (equivalente a gray-matter)."""

from pathlib import Path

import yaml
from django.conf import settings


def read_markdown(path: Path) -> tuple[dict, str]:
    """Devuelve (frontmatter, cuerpo) de un archivo .md."""
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            return yaml.safe_load(parts[1]) or {}, parts[2].strip()
    return {}, raw.strip()


def content_path(*parts: str) -> Path:
    return Path(settings.CONTENT_DIR).joinpath(*parts)
