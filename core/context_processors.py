import json

from django.conf import settings

from . import constants


def sitio(request):
    """Datos fijos del sitio disponibles en todas las plantillas."""
    path = request.path
    nav_items = [
        {
            **item,
            "activo": path == item["href"]
            or (item["href"] != "/" and path.startswith(item["href"])),
        }
        for item in constants.NAV_ITEMS
    ]
    return {
        "SITE": {**constants.SITE, "url": settings.SITE_URL},
        "NAV_ITEMS": nav_items,
        "SEDES": constants.SEDES,
        "HORARIOS": constants.HORARIOS,
        "CONTACTO": constants.CONTACTO,
        "REDES_SOCIALES": constants.REDES_SOCIALES,
        "LINKS_LEGALES": constants.LINKS_LEGALES,
        "FOOTER_LINKS": constants.FOOTER_LINKS,
        "GA_MEASUREMENT_ID": settings.GA_MEASUREMENT_ID,
        "ORGANIZATION_JSONLD": json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": constants.SITE["nombre"],
                "url": settings.SITE_URL,
                "logo": f"{settings.SITE_URL}/static/images/logo.png",
                "description": constants.SITE["descripcion"],
                "contactPoint": {
                    "@type": "ContactPoint",
                    "telephone": constants.CONTACTO["telefonos"][0],
                    "contactType": "customer service",
                    "availableLanguage": "Spanish",
                    "areaServed": "CO",
                },
                "address": [
                    {
                        "@type": "PostalAddress",
                        "addressLocality": sede["ciudad"],
                        "streetAddress": sede["direccion"].split(": ")[-1],
                        "addressCountry": "CO",
                    }
                    for sede in constants.SEDES
                ],
                "sameAs": [red["url"] for red in constants.REDES_SOCIALES],
            },
            ensure_ascii=False,
        ),
    }
