from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from carrito.estadisticas import vista_estadisticas

admin.site.site_header = "Viati Café — Administración"
admin.site.site_title = "Viati Café"
admin.site.index_title = "Panel de la tienda"

# Las URLs públicas van SIN "/" final, igual que en el sitio Next.js (SEO).
urlpatterns = [
    # Va antes de admin.site.urls para que el admin no la tome como un modelo.
    path("admin/estadisticas/", vista_estadisticas(), name="admin_estadisticas"),
    path("admin/", admin.site.urls),
    path("", include("panel.urls")),
    path("", include("carrito.urls")),
    path("", include("paginas.urls")),
    path("", include("tienda.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
elif settings.SERVE_MEDIA:
    # Producción sin almacenamiento externo: Django sirve las fotos subidas.
    urlpatterns += [
        re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    ]
