"""Constantes del sitio — Viati Café.

Fuente de verdad para datos fijos del sitio (equivalente a src/lib/constants.ts
del proyecto Next.js). Las plantillas las reciben vía core.context_processors.
"""

SITE = {
    "nombre": "Viati Café",
    "eslogan": "Vida y Tierra Colombiana",
    "descripcion": (
        "Café de especialidad colombiano, originario de Togüí, Boyacá. Venta de cafés de "
        "origen, reconocimiento a orígenes, prácticas sostenibles."
    ),
    "locale": "es-CO",
    "moneda": "COP",
}

NAV_ITEMS = [
    {"label": "Inicio", "href": "/"},
    {"label": "Tienda", "href": "/tienda"},
    {"label": "Orígenes", "href": "/origenes"},
    {"label": "Institucional", "href": "/institucional"},
    {"label": "Nosotros", "href": "/nosotros"},
    {"label": "Contáctanos", "href": "/contacto"},
]

SEDES = [
    {"ciudad": "Bogotá", "direccion": "Cr 88b # 127 a - 38"},
    {"ciudad": "Bucaramanga", "direccion": "Calle 30 # 14-48"},
    {"ciudad": "Togüí - Boyacá", "direccion": "Finca La Lupita, Vereda Manga"},
]

HORARIOS = [
    {"dias": "Lun - Vie", "rango": "8am - 8pm"},
    {"dias": "Sábado", "rango": "9am - 7pm"},
]

CONTACTO = {
    "telefonos": ["319 320 74 52", "320 441 85 11"],
    "email": "gerencia@agroambientec.com",
    "whatsapp": {
        "numero": "+573219329338",
        "display": "+57 321 932 9338",
        "url": "https://wa.link/80c0rk",
    },
}

REDES_SOCIALES = [
    {"nombre": "Instagram", "url": "https://www.instagram.com/viati.cafe", "icono": "instagram"},
    {"nombre": "WhatsApp", "url": "https://wa.link/80c0rk", "icono": "whatsapp"},
    {"nombre": "Facebook", "url": "https://www.facebook.com/viaticafe", "icono": "facebook"},
]

CERTIFICACIONES = [
    {"nombre": "Bizacaya", "slug": "bizacaya"},
    {"nombre": "After Leto", "slug": "after-leto"},
    {"nombre": "Sello Café S", "slug": "sello-cafe-s"},
]

ORIGENES_SUMARIO = [
    {
        "nombre": "El Paraíso",
        "slug": "el-paraiso",
        "region": "Togüí, Boyacá",
        "descripcion": "Cultivado y cosechado tradicionalmente. Notas dulces por condiciones geográficas y climáticas.",
    },
    {
        "nombre": "Heroico",
        "slug": "heroico",
        "region": "Socorro, Santander",
        "descripcion": "Intenso, con cuerpo y actitud. Cultivado bajo sombra de bosques nativos.",
    },
    {
        "nombre": "Oromiel",
        "slug": "oromiel",
        "region": "Moniquirá, Boyacá",
        "descripcion": "Café honey, notas muy dulces, perfil suave.",
    },
]

LINKS_LEGALES = [
    {"label": "Envíos", "href": "/politicas/envios"},
    {"label": "Devoluciones", "href": "/politicas/devoluciones"},
    {"label": "FAQ", "href": "/politicas/faq"},
]

FOOTER_LINKS = [
    {"label": "Tienda", "href": "/tienda"},
    {"label": "Orígenes", "href": "/origenes"},
    {"label": "Nosotros", "href": "/nosotros"},
    {"label": "Contáctanos", "href": "/contacto"},
]

CATEGORIAS_PRODUCTO = ["Café", "Café honey", "Kit/mercancía", "Accesorio"]
