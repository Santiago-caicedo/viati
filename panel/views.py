"""Vistas del panel de gestión de Viati Café (/panel)."""

import csv
import logging
import re

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from carrito import estadisticas
from carrito import mercadopago as mp
from carrito.emails import send_order_emails
from carrito.models import Order, ShippingRate, StoreSettings
from tienda import odoo_sync
from tienda.models import OdooSyncState, Product

from . import seguridad
from .forms import (
    CambiarClaveForm, ConfigTiendaForm, FiltroPedidos, LoginForm, ProductoForm, TamanosFormSet, TarifasFormSet,
)
from .seguridad import panel_requerido

logger = logging.getLogger(__name__)

SESION_RECORDADA = 7 * 24 * 3600


# ── Acceso ──

@never_cache
@csrf_protect
def ingresar(request):
    destino = request.POST.get("next") or request.GET.get("next") or ""
    if not url_has_allowed_host_and_scheme(destino, {request.get_host()}, require_https=request.is_secure()) \
            or not destino.startswith("/panel"):
        destino = "/panel"

    if seguridad.puede_entrar(request.user):
        return redirect(destino)

    bloqueado = False
    if request.method == "POST":
        usuario = request.POST.get("username", "")
        if seguridad.esta_bloqueado(request, usuario):
            bloqueado = True
            form = LoginForm(request)
        else:
            form = LoginForm(request, data=request.POST)
            if form.is_valid():
                user = form.get_user()
                login(request, user)  # cambia el id de sesión (evita fijación de sesión)
                request.session.set_expiry(SESION_RECORDADA if form.cleaned_data.get("recordarme") else 0)
                seguridad.limpiar_fallos(request, usuario)
                logger.info("Ingreso al panel: %s (ip=%s)", user.get_username(), seguridad.ip_cliente(request))
                return redirect(destino)
            seguridad.registrar_fallo(request, usuario)
            bloqueado = seguridad.esta_bloqueado(request, usuario)
    else:
        form = LoginForm(request)

    response = render(request, "panel/login.html", {"form": form, "next": destino, "bloqueado": bloqueado},
                      status=429 if bloqueado else 200)
    return seguridad.con_cabeceras_privadas(response)


@require_POST
@csrf_protect
def salir(request):
    logout(request)
    messages.success(request, "Cerraste sesión.")
    return redirect("panel:login")


@panel_requerido
def cuenta(request):
    form = CambiarClaveForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # no cierra la sesión actual
        messages.success(request, "Tu contraseña se cambió correctamente.")
        return redirect("panel:cuenta")
    return render(request, "panel/cuenta.html", {"form": form, "seccion": "cuenta"})


# ── Inicio / estadísticas ──

@panel_requerido
def inicio(request):
    datos = estadisticas.calcular(estadisticas.periodo_dias(request.GET.get("dias", 30)))
    return render(request, "panel/inicio.html", {**datos, "seccion": "inicio"})


# ── Pedidos ──

def _pedidos_filtrados(request):
    filtro = FiltroPedidos(request.GET or None)
    qs = Order.objects.all()
    if filtro.is_valid():
        d = filtro.cleaned_data
        q = (d.get("q") or "").strip()
        if q:
            numero = re.fullmatch(r"(?i)(?:vc-?)?0*(\d+)", q)
            condicion = (
                Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q)
                | Q(document__icontains=q) | Q(mp_payment_id=q) | Q(city__icontains=q)
            )
            if numero:
                condicion |= Q(pk=int(numero.group(1)))
            qs = qs.filter(condicion)
        if d.get("estado"):
            qs = qs.filter(status=d["estado"])
        if d.get("departamento"):
            qs = qs.filter(department=d["departamento"])
        if d.get("desde"):
            qs = qs.filter(created_at__date__gte=d["desde"])
        if d.get("hasta"):
            qs = qs.filter(created_at__date__lte=d["hasta"])
    return filtro, qs.order_by("-created_at")


@panel_requerido
def pedidos(request):
    filtro, qs = _pedidos_filtrados(request)
    pagina = Paginator(qs, 25).get_page(request.GET.get("pagina"))
    params = request.GET.copy()
    params.pop("pagina", None)
    conteo = {s: Order.objects.filter(status=s).count() for s in (Order.PAGADO, Order.EN_PROCESO, Order.PENDIENTE)}
    return render(request, "panel/pedidos.html", {
        "filtro": filtro, "pagina": pagina, "total": qs.count(), "params": params.urlencode(),
        "conteo": conteo, "seccion": "pedidos",
    })


@panel_requerido
def pedidos_csv(request):
    _, qs = _pedidos_filtrados(request)
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="pedidos-viati-{timezone.localdate():%Y-%m-%d}.csv"'
    response.write("﻿")  # BOM: Excel abre bien las tildes
    w = csv.writer(response, delimiter=";")
    w.writerow(["Pedido", "Creado", "Pagado", "Estado", "Cliente", "Correo", "Celular", "Documento", "Dirección",
                "Complemento", "Ciudad", "Departamento", "Productos", "Subtotal", "Envío", "Total", "Pago MP", "Notas"])
    for o in qs.prefetch_related("items"):
        productos = " | ".join(f"{i.qty}x {i.product_name}" + (f" ({i.options_label})" if i.options_label else "")
                               for i in o.items.all())
        w.writerow([
            o.number, timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"),
            timezone.localtime(o.paid_at).strftime("%Y-%m-%d %H:%M") if o.paid_at else "",
            o.get_status_display(), o.full_name, o.email, o.phone, f"{o.document_type} {o.document}",
            o.address, o.address2, o.city, o.department, productos, o.subtotal, o.shipping, o.total,
            o.mp_payment_id, _sin_formula(o.notes),
        ])
    return seguridad.con_cabeceras_privadas(response)


def _sin_formula(texto: str) -> str:
    """Evita que Excel ejecute como fórmula un texto escrito por el cliente."""
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def _whatsapp(phone: str) -> str:
    digitos = re.sub(r"\D", "", phone or "")
    if len(digitos) == 10:
        digitos = "57" + digitos
    return f"https://wa.me/{digitos}" if len(digitos) >= 11 else ""


@panel_requerido
def pedido(request, pk):
    order = get_object_or_404(Order, pk=pk)
    return render(request, "panel/pedido.html", {
        "order": order, "items": list(order.items.select_related("product")), "whatsapp": _whatsapp(order.phone),
        "seccion": "pedidos",
    })


@panel_requerido
@require_POST
def pedido_accion(request, pk, accion):
    order = get_object_or_404(Order, pk=pk)
    if accion == "enviado":
        if order.status == Order.PAGADO:
            order.status = Order.ENVIADO
            order.shipped_at = timezone.now()
            order.save(update_fields=["status", "shipped_at", "updated_at"])
            messages.success(request, f"{order.number} quedó marcado como enviado.")
        else:
            messages.error(request, "Solo se pueden marcar como enviados los pedidos pagados.")
    elif accion == "correos":
        if not order.is_paid:
            messages.error(request, "Los correos solo se envían para pedidos pagados.")
        else:
            try:
                send_order_emails(order, force=True)
                messages.success(request, f"Correos de {order.number} reenviados a gerencia y al cliente.")
            except Exception as exc:  # noqa: BLE001
                logger.exception("Reenvío de correos falló para %s", order.number)
                messages.error(request, f"No se pudieron enviar los correos: {exc}")
    elif accion == "verificar":
        try:
            order = mp.refresh_order(order)
            if order.is_paid and not order.emails_sent:
                send_order_emails(order)
            messages.success(request, f"Mercado Pago dice: {order.get_status_display()}.")
        except mp.MercadoPagoError as exc:
            messages.error(request, f"No se pudo consultar Mercado Pago: {exc}")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"El pago se verificó pero fallaron los correos: {exc}")
    else:
        messages.error(request, "Acción desconocida.")
    return redirect("panel:pedido", pk=order.pk)


# ── Productos ──

@panel_requerido
def productos(request):
    lista = Product.objects.prefetch_related("sizes").order_by("order", "name")
    return render(request, "panel/productos.html", {
        "productos": lista, "seccion": "productos", "odoo_activo": odoo_sync.intervalo_segundos() > 0,
        "odoo_estado": OdooSyncState.objects.filter(pk=1).first(),
    })


@panel_requerido
def producto_editar(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else Product(active=True)
    form = ProductoForm(request.POST or None, request.FILES or None, instance=product)
    tamanos = TamanosFormSet(request.POST or None, instance=product, prefix="tamanos")
    if request.method == "POST":
        if form.is_valid() and tamanos.is_valid():
            if tamanos.tamanos_validos() == 0 and not form.cleaned_data.get("price"):
                form.add_error("price", "Pon un precio mayor a 0 o agrega al menos un tamaño.")
            else:
                with transaction.atomic():
                    product = form.save()
                    tamanos.instance = product
                    tamanos.save()
                messages.success(request, f"«{product.name}» se guardó.")
                return redirect("panel:productos")
        messages.error(request, "Revisa los campos marcados.")
    return render(request, "panel/producto_form.html", {
        "form": form, "tamanos": tamanos, "product": product, "seccion": "productos",
        "desde_odoo": bool(product.odoo_id) and odoo_sync.intervalo_segundos() > 0,
    })


@panel_requerido
@require_POST
def producto_visible(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.active = not product.active
    product.save(update_fields=["active", "updated_at"])
    messages.success(request, f"«{product.name}» ahora está {'visible' if product.active else 'oculto'} en la tienda.")
    return redirect("panel:productos")


# ── Envíos ──

@panel_requerido
def envios(request):
    config = StoreSettings.load()
    tarifas = TarifasFormSet(request.POST or None, queryset=ShippingRate.objects.order_by("zona", "departamento", "min_g"),
                             prefix="tarifas")
    config_form = ConfigTiendaForm(request.POST or None, instance=config, prefix="config")
    if request.method == "POST":
        if tarifas.is_valid() and config_form.is_valid():
            with transaction.atomic():
                tarifas.save()
                config_form.save()
            messages.success(request, "Tarifas y configuración guardadas.")
            return redirect("panel:envios")
        messages.error(request, "Revisa los campos marcados.")
    return render(request, "panel/envios.html", {"tarifas": tarifas, "config_form": config_form, "seccion": "envios"})
