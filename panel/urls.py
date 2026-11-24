from django.urls import path

from . import views

app_name = "panel"

# Sin "/" final, como el resto del sitio (RemoveTrailingSlashMiddleware).
urlpatterns = [
    path("panel", views.inicio, name="inicio"),
    path("panel/ingresar", views.ingresar, name="login"),
    path("panel/salir", views.salir, name="salir"),
    path("panel/cuenta", views.cuenta, name="cuenta"),
    path("panel/pedidos", views.pedidos, name="pedidos"),
    path("panel/pedidos/exportar", views.pedidos_csv, name="pedidos_csv"),
    path("panel/pedidos/<int:pk>", views.pedido, name="pedido"),
    path("panel/pedidos/<int:pk>/<slug:accion>", views.pedido_accion, name="pedido_accion"),
    path("panel/productos", views.productos, name="productos"),
    path("panel/productos/nuevo", views.producto_editar, name="producto_nuevo"),
    path("panel/productos/<int:pk>", views.producto_editar, name="producto_editar"),
    path("panel/productos/<int:pk>/visible", views.producto_visible, name="producto_visible"),
    path("panel/envios", views.envios, name="envios"),
]
