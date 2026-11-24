"""sitemap.xml, robots.txt y manifest.webmanifest (equivalen a src/app/sitemap.ts,
robots.ts y manifest.ts)."""

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.http import require_GET

from core.constants import SITE
from tienda.models import Product

from .origenes import get_all_origenes

# (ruta, prioridad, frecuencia) — mismas que staticRoutes de sitemap.ts
RUTAS_ESTATICAS = [
    ("", 1.0, "daily"),
    ("/tienda", 0.9, "daily"),
    ("/origenes", 0.9, "daily"),
    ("/institucional", 0.5, "monthly"),
    ("/nosotros", 0.5, "monthly"),
    ("/contacto", 0.5, "monthly"),
    ("/politicas/envios", 0.5, "monthly"),
    ("/politicas/devoluciones", 0.5, "monthly"),
    ("/politicas/faq", 0.5, "monthly"),
]


@require_GET
def sitemap(request):
    base = settings.SITE_URL
    ahora = timezone.now().isoformat(timespec="milliseconds").replace("+00:00", "Z")
    entradas = [(f"{base}{ruta}", freq, prio) for ruta, prio, freq in RUTAS_ESTATICAS]
    entradas += [
        (f"{base}/tienda/{slug}", "weekly", 0.8)
        for slug in Product.objects.filter(active=True).values_list("slug", flat=True)
    ]
    entradas += [(f"{base}/origenes/{o['slug']}", "monthly", 0.8) for o in get_all_origenes()]

    lineas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url, freq, prio in entradas:
        lineas.append(
            f"<url>\n<loc>{escape(url)}</loc>\n<lastmod>{ahora}</lastmod>\n"
            f"<changefreq>{freq}</changefreq>\n<priority>{prio}</priority>\n</url>"
        )
    lineas.append("</urlset>")
    return HttpResponse("\n".join(lineas), content_type="application/xml")


BOTS_IA = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User", "ClaudeBot", "PerplexityBot",
    "cohere-ai", "Google-Extended", "Applebot-Extended",
]


@require_GET
def robots(request):
    lineas = [f"User-Agent: {bot}" for bot in BOTS_IA]
    lineas += [f"Allow: {r}" for r in ("/", "/tienda", "/origenes", "/nosotros", "/institucional", "/contacto")]
    lineas += ["Disallow: /api/", "Disallow: /carrito", "Disallow: /panel", ""]
    # "/_next/" de Next.js no existe aquí; se bloquea /admin/ en su lugar.
    lineas += ["User-Agent: *", "Allow: /", "Disallow: /api/", "Disallow: /carrito", "Disallow: /admin/", "Disallow: /panel", ""]
    lineas += [f"Sitemap: {settings.SITE_URL}/sitemap.xml", ""]
    return HttpResponse("\n".join(lineas), content_type="text/plain; charset=utf-8")


@require_GET
def manifest(request):
    return JsonResponse(
        {
            "name": SITE["nombre"],
            "short_name": "Viati",
            "description": SITE["descripcion"],
            "start_url": "/",
            "display": "standalone",
            "background_color": "#FFFFFF",
            "theme_color": "#293E31",
            "icons": [{"src": static("images/logo.png"), "sizes": "512x512", "type": "image/png"}],
        },
        content_type="application/manifest+json",
        json_dumps_params={"ensure_ascii": False},
    )
