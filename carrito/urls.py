from django.urls import path

from . import views

# Sin "/" final (RemoveTrailingSlashMiddleware redirige /x/ → /x).
urlpatterns = [
    path("carrito/estado", views.estado, name="carrito_estado"),
    path("carrito/agregar", views.agregar, name="carrito_agregar"),
    path("carrito/actualizar", views.actualizar, name="carrito_actualizar"),
    path("carrito/eliminar", views.eliminar, name="carrito_eliminar"),
    path("checkout", views.checkout, name="checkout"),
    path("checkout/envio", views.checkout_envio, name="checkout_envio"),
    path("pedido/<uuid:token>", views.pedido, name="pedido"),
    path("pedido/<uuid:token>/estado", views.pedido_estado, name="pedido_estado"),
    path("pedido/<uuid:token>/reintentar", views.pedido_reintentar, name="pedido_reintentar"),
    path("api/mercadopago/webhook", views.mercadopago_webhook, name="mercadopago_webhook"),
]
