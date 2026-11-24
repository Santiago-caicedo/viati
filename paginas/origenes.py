"""Lectura de los orígenes en content/origenes/*.md (equivale a src/lib/origenes.ts)."""

from core.content import content_path, read_markdown

from .imagenes import imagen_url

CAMPOS_REQUERIDOS = (
    "slug", "name", "region", "description", "image", "gallery", "altitude",
    "temperature", "perfilTaza", "notas", "ubicacion", "clima", "atractivos",
)


def _parse_origen(path) -> dict:
    data, _ = read_markdown(path)
    faltantes = [c for c in CAMPOS_REQUERIDOS if data.get(c) in (None, "")]
    if faltantes:
        raise ValueError(f"Error en {path.name}: faltan campos {', '.join(faltantes)}")
    origen = {k: data[k] for k in CAMPOS_REQUERIDOS}
    origen["altitude"] = str(origen["altitude"])
    origen["temperature"] = str(origen["temperature"])
    origen["caficultor"] = data.get("caficultor") or ""
    origen["finca"] = data.get("finca") or ""
    # URLs ya resueltas para las plantillas
    origen["image_url"] = imagen_url(origen["image"])
    origen["gallery_urls"] = [imagen_url(img) for img in origen["gallery"]]
    return origen


def get_all_origenes() -> list[dict]:
    """Todos los orígenes, en orden alfabético de archivo (igual que fs.readdir)."""
    carpeta = content_path("origenes")
    return [_parse_origen(p) for p in sorted(carpeta.glob("*.md"))]


def get_origen_by_slug(slug: str) -> dict | None:
    return next((o for o in get_all_origenes() if o["slug"] == slug), None)
