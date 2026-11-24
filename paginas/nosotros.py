"""Lectura de content/nosotros.md (equivale a src/lib/nosotros.ts)."""

from core.content import content_path, read_markdown

from .imagenes import imagen_url

SECCIONES = ("hero", "historia", "procesos", "galeria", "carrusel", "valores")


def get_pagina_nosotros() -> dict:
    data, _ = read_markdown(content_path("nosotros.md"))
    faltantes = [s for s in SECCIONES if not isinstance(data.get(s), dict)]
    if faltantes:
        raise ValueError(f"Validación fallida en content/nosotros.md: faltan {', '.join(faltantes)}")

    data["hero"]["image_url"] = imagen_url(data["hero"]["image"])
    for feat in data["procesos"]["featured"]:
        feat["image_url"] = imagen_url(feat["image"])
    for item in data["galeria"]["items"] + data["carrusel"]["items"]:
        item["url"] = imagen_url(item["src"])
    return data
