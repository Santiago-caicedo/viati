from django.urls import include, path

from . import seo, views

urlpatterns = [
    path("origenes", views.origenes, name="origenes"),
    path("origenes/<slug:slug>", views.origen_detalle, name="origen_detalle"),
    path("nosotros", views.nosotros, name="nosotros"),
    path("institucional", views.institucional, name="institucional"),
    path("contacto", views.contacto, name="contacto"),
    path("politicas/envios", views.politica_envios, name="politica_envios"),
    path("politicas/devoluciones", views.politica_devoluciones, name="politica_devoluciones"),
    path("politicas/faq", views.politica_faq, name="politica_faq"),
    # API de formularios (mismas rutas que Next.js)
    path("api/contact", views.api_contact, name="api_contact"),
    path("api/institucional", views.api_institucional, name="api_institucional"),
    # SEO
    path("sitemap.xml", seo.sitemap, name="sitemap"),
    path("robots.txt", seo.robots, name="robots"),
    path("manifest.webmanifest", seo.manifest, name="manifest"),
    # 301 desde las URLs del sitio Wix
    path("", include("paginas.redirects")),
]
