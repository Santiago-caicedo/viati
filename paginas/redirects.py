"""Redirecciones 301 de las URLs del sitio Wix anterior (next.config.ts → redirects()).

Next declaraba cada ruta con y sin "/" final; aquí basta con la versión sin barra
porque core.middleware.RemoveTrailingSlashMiddleware ya redirige "/x/" → "/x"
(la variante con barra termina igual en el destino, vía dos 301).
Django compara contra la ruta ya decodificada, por eso "maletín" va con tilde.
"""

from django.urls import path
from django.views.generic import RedirectView

WIX_REDIRECTS = {
    "category/all-products": "/tienda",
    "viati-institucional": "/institucional",
    "contactanos": "/contacto",
    "store-policy": "/politicas/envios",
    "shipping-returns": "/politicas/devoluciones",
    "faq": "/politicas/faq",
    "blog": "/",
    "product-page/dulce-bendicion": "/tienda/dulce-bendicion",
    "product-page/al-natural": "/tienda/al-natural",
    "product-page/el-paraiso": "/tienda/el-paraiso",
    "product-page/del-carajillo": "/tienda/del-carajillo",
    "product-page/oromiel": "/tienda/oromiel",
    "product-page/heroico": "/tienda/heroico",
    "product-page/maletín-los-sabores-de-mi-tierra": "/tienda/maletin-sabores",
    "product-page/cuchara-pinza-dosificadora": "/tienda/cuchara-dosificadora",
}

# query_string=True: Next.js conserva la query string en sus redirects.
urlpatterns = [
    path(origen, RedirectView.as_view(url=destino, permanent=True, query_string=True))
    for origen, destino in WIX_REDIRECTS.items()
]
