"""Conversión de rutas de imagen del contenido Markdown a URLs de static."""

from urllib.parse import unquote

from django.templatetags.static import static


def imagen_url(src: str) -> str:
    """"/images/x%20y.jpg" (formato del sitio Next.js) → URL de static de "images/x y.jpg"."""
    if not src or src.startswith(("http://", "https://")):
        return src
    return static(unquote(src.lstrip("/")))
