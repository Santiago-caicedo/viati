"""Vistas de la tienda — Viati Café.

Equivalen a src/app/page.tsx, src/app/tienda/page.tsx,
src/app/tienda/[slug]/page.tsx y src/app/api/odoo-image/[id]/route.ts.
"""

import json
import logging

from django.conf import settings
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from core import constants

from . import odoo, odoo_sync
from .models import Product

logger = logging.getLogger(__name__)

# Aliados de la home (equivale al arreglo `instituciones` de SellosGrid.tsx).
INSTITUCIONES = [
    {"nombre": "Afternoon", "slug": "after-leto", "logo": "images/Aliados/after-leto.png"},
    {"nombre": "Café y Postres Chicalá", "slug": "chicala", "logo": "images/Aliados/aliado-4.png"},
    {"nombre": "Hotel Vizcaya Plaza", "slug": "hotel-vizcaya-plaza", "logo": "images/Aliados/hotel-vizcaya-plaza.gif"},
    {"nombre": "Herencia", "slug": "herencia", "logo": "images/Aliados/aliado-5.jpeg"},
    {"nombre": "Cafe Entrenos", "slug": "cafe-entrenos", "logo": "images/Aliados/SELLO-CAFE-S.png"},
]


def _productos_activos():
    # Si toca, refresca el catálogo desde Odoo en segundo plano (no bloquea la página).
    odoo_sync.sincronizar_si_toca()
    return Product.objects.filter(active=True).prefetch_related("sizes")


def _url_absoluta(url: str) -> str:
    """Convierte una ruta relativa (/static/...) en URL absoluta del sitio."""
    if not url or url.startswith(("http://", "https://")):
        return url
    return f"{settings.SITE_URL}{url}"


def inicio(request):
    """Home: hero, sostenibilidad, aliados, productos destacados y orígenes."""
    destacados = _productos_activos().filter(featured=True)
    return render(
        request,
        "tienda/inicio.html",
        {"products": destacados, "instituciones": INSTITUCIONES},
    )


def tienda(request):
    """Catálogo completo con filtros por categoría y orden (en el cliente)."""
    products = list(_productos_activos())
    # Categorías en el orden en que aparecen en el catálogo (new Set(...) del original).
    categories = ["Todos"]
    for product in products:
        if product.category not in categories:
            categories.append(product.category)
    # Orden inicial "Destacados": primero los destacados y luego por nombre
    # (main JS lo vuelve a aplicar con Intl.Collator('es')).
    products.sort(key=lambda p: (not p.featured, odoo.sort_key(p.name)))
    return render(
        request,
        "tienda/tienda.html",
        {"products": products, "categories": categories},
    )


def producto(request, slug: str):
    """Detalle de producto (404 si no existe o está inactivo)."""
    product = get_object_or_404(_productos_activos(), slug=slug)
    optional_products = list(
        product.optional_products.filter(active=True).prefetch_related("sizes")
    )

    site_url = settings.SITE_URL
    product_url = f"{site_url}/tienda/{product.slug}"
    image_abs = _url_absoluta(product.image_url)
    sizes = product.size_list

    breadcrumb_ld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": site_url},
            {"@type": "ListItem", "position": 2, "name": "Tienda", "item": f"{site_url}/tienda"},
            {"@type": "ListItem", "position": 3, "name": product.name, "item": product_url},
        ],
    }
    if sizes:
        offers = [
            {
                "@type": "Offer",
                "name": size.name,
                "price": size.price,
                "priceCurrency": constants.SITE["moneda"],
                "availability": "https://schema.org/InStock",
                "url": product_url,
            }
            for size in sizes
        ]
    else:
        offers = {
            "@type": "Offer",
            "price": product.price,
            "priceCurrency": constants.SITE["moneda"],
            "availability": "https://schema.org/InStock",
            "url": product_url,
        }
    product_ld = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.name,
        "description": product.description,
        "image": image_abs,
        "sku": product.slug,
        "brand": {"@type": "Brand", "name": constants.SITE["nombre"]},
        "offers": offers,
    }

    # Imagen grande del detalle: el endpoint de Odoo recibe área/encuadre mayores.
    detail_image = product.image_url
    if detail_image.startswith("/api/odoo-image/"):
        detail_image = f"{detail_image}?area=70&fit=95"

    def _ld(data) -> str:
        # Evita cerrar el <script> desde el contenido.
        return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return render(
        request,
        "tienda/producto.html",
        {
            "product": product,
            "sizes": sizes,
            "selected_size": sizes[0] if sizes else None,
            "optional_products": optional_products,
            "detail_image": detail_image,
            "og_image": image_abs,
            "breadcrumb_ld": _ld(breadcrumb_ld),
            "product_ld": _ld(product_ld),
        },
    )


@require_GET
def odoo_image(request, template_id: int):
    """Imagen cuadrada (webp) de un producto de Odoo, procesada y cacheada en disco."""
    if template_id <= 0:
        return HttpResponse("id inválido", status=400, content_type="text/plain; charset=utf-8")

    area = odoo.clamp_area_fraction(request.GET.get("area"))
    fit = odoo.clamp_fit_fraction(request.GET.get("fit"))

    try:
        data = odoo.get_square_image(template_id, area, fit)
    except odoo.OdooConfigError as error:
        logger.warning("[odoo-image] %s", error)
        return HttpResponse(str(error), status=503, content_type="text/plain; charset=utf-8")
    except odoo.OdooImageNotFound:
        raise Http404("Imagen no disponible")
    except Exception:  # noqa: BLE001 — cualquier fallo de red/procesado
        logger.exception("[odoo-image] Error procesando la imagen %s", template_id)
        return HttpResponse(
            "Error procesando la imagen", status=500, content_type="text/plain; charset=utf-8"
        )

    response = HttpResponse(data, content_type="image/webp")
    response["Content-Length"] = str(len(data))
    response["Cache-Control"] = "public, max-age=0, s-maxage=3600, stale-while-revalidate=86400"
    return response
