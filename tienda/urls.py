from django.urls import path

from . import views

# Sin "/" final, igual que en el sitio Next.js.
urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("tienda", views.tienda, name="tienda"),
    path("tienda/<slug:slug>", views.producto, name="producto"),
    path("api/odoo-image/<int:template_id>", views.odoo_image, name="odoo_image"),
]
