"""Vistas del carrito, checkout, retorno de Mercado Pago y webhook.

Decisión sobre el carrito: se VACÍA apenas se crea el pedido y se redirige a
Mercado Pago (el pedido ya guarda los artículos). Si el pago es rechazado, el
cliente reintenta desde /pedido/<token> con el mismo pedido.
"""

import json
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.constants import CONTACTO
from tienda.models import Product

from . import mercadopago as mp
from .cart import MAX_QTY, Cart
from .emails import send_order_emails
from .forms import CheckoutForm
from .models import Order, OrderItem, StoreSettings
from .shipping import DEPARTAMENTOS, quote

logger = logging.getLogger(__name__)


# ── Utilidades ──

def _payload(request) -> dict:
    """Lee el cuerpo como JSON o como formulario."""
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body or b"{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST.dict()


def _qty(value, default: int = 1) -> int | None:
    try:
        qty = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return None
    return qty if 1 <= qty <= MAX_QTY else None


def cart_state(cart: Cart, lines=None) -> dict:
    lines = cart.lines() if lines is None else lines
    store = StoreSettings.load()
    return {
        "count": sum(line.qty for line in lines),
        "subtotal": cart.subtotal(lines),
        "total_weight": cart.total_weight(lines),
        "items": [line.as_dict() for line in lines],
        "free_shipping_from": store.free_shipping_from,
        "checkout_url": "/checkout",
    }


def _error(message: str, status: int = 400, cart: Cart | None = None) -> JsonResponse:
    data = {"error": message}
    if cart is not None:
        data.update(cart_state(cart))
    return JsonResponse(data, status=status)


def _ensure_emails(order: Order) -> None:
    """Envía los correos del pedido pagado si aún no salieron (sin romper la página)."""
    if order.is_paid and not order.emails_sent:
        try:
            send_order_emails(order)
        except Exception:  # noqa: BLE001 — ya queda registrado en el log
            logger.exception("Fallo enviando correos del pedido %s", order.number)


# ── API JSON del carrito ──

@require_GET
def estado(request):
    return JsonResponse(cart_state(Cart(request)))


@require_POST
def agregar(request):
    data = _payload(request)
    cart = Cart(request)
    slug = str(data.get("slug") or "").strip()
    product = Product.objects.filter(slug=slug, active=True).prefetch_related("sizes").first() if slug else None
    if product is None:
        return _error("El producto no existe o no está disponible.", 404, cart)
    qty = _qty(data.get("qty"))
    if qty is None:
        return _error(f"La cantidad debe estar entre 1 y {MAX_QTY}.", 400, cart)
    line = cart.add(product, str(data.get("size") or ""), str(data.get("grind") or ""), qty)
    state = cart_state(cart)
    state["added"] = {**line.as_dict(), "qty_added": qty}
    return JsonResponse(state)


@require_POST
def actualizar(request):
    data = _payload(request)
    cart = Cart(request)
    key = str(data.get("key") or "")
    if key not in cart.data:
        return _error("Ese artículo ya no está en el carrito.", 404, cart)
    try:
        qty = int(data.get("qty"))
    except (TypeError, ValueError):
        return _error("Cantidad inválida.", 400, cart)
    if qty > MAX_QTY:
        return _error(f"La cantidad máxima es {MAX_QTY}.", 400, cart)
    cart.update(key, qty)  # qty <= 0 elimina la línea
    return JsonResponse(cart_state(cart))


@require_POST
def eliminar(request):
    data = _payload(request)
    cart = Cart(request)
    cart.remove(str(data.get("key") or ""))
    return JsonResponse(cart_state(cart))


# ── Checkout ──

def _summary(lines, cart: Cart, departamento: str | None) -> dict:
    subtotal = cart.subtotal(lines)
    weight = cart.total_weight(lines)
    if departamento:
        q = quote(weight_g=weight, departamento=departamento, subtotal=subtotal)
        shipping, free, known = q.price, q.free, True
    else:
        shipping, free, known = 0, False, False
    return {
        "lines": lines,
        "subtotal": subtotal,
        "total_weight": weight,
        "shipping": shipping,
        "shipping_free": free,
        "shipping_known": known,
        "total": subtotal + shipping,
    }


def _render_checkout(request, form, lines, cart, error: str = ""):
    departamento = form.data.get("department") if form.is_bound else form.initial.get("department")
    context = {
        "form": form,
        "error": error,
        "mp_configured": mp.is_configured(),
        "whatsapp_url": CONTACTO["whatsapp"]["url"],
        "free_shipping_from": StoreSettings.load().free_shipping_from,
        **_summary(lines, cart, departamento if departamento else None),
    }
    return render(request, "carrito/checkout.html", context, status=400 if error or form.errors else 200)


@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = Cart(request)
    lines = cart.lines()
    if not lines:
        # Si volvió de Mercado Pago sin pagar, llevarlo a su pedido para reintentar.
        last = request.session.get("ultimo_pedido")
        if last:
            order = Order.objects.filter(token=last, status__in=[Order.PENDIENTE, Order.RECHAZADO]).first()
            if order:
                return redirect(order.get_absolute_url())
        return redirect("/tienda")

    if request.method == "GET":
        return _render_checkout(request, CheckoutForm(), lines, cart)

    form = CheckoutForm(request.POST)
    if not form.is_valid():
        return _render_checkout(request, form, lines, cart)
    if not mp.is_configured():
        logger.error("Checkout sin MP_ACCESS_TOKEN configurado")
        return _render_checkout(
            request, form, lines, cart,
            "Los pagos en línea no están disponibles en este momento. Escríbenos por WhatsApp y te ayudamos a completar tu pedido.",
        )
    sin_precio = [line.product.name for line in lines if line.unit_price <= 0]
    if sin_precio:
        # Producto mal cargado en el admin: no se vende (MP exige precio > 0).
        logger.error("Checkout bloqueado: producto(s) con precio 0: %s", ", ".join(sin_precio))
        return _render_checkout(
            request, form, lines, cart,
            f"Estos productos no están disponibles por ahora: {', '.join(sin_precio)}. "
            "Quítalos del carrito o escríbenos por WhatsApp.",
        )

    data = form.cleaned_data
    summary = _summary(lines, cart, data["department"])
    with transaction.atomic():
        order = Order.objects.create(
            full_name=data["full_name"],
            email=data["email"],
            phone=data["phone"],
            document_type=data["document_type"],
            document=data["document"],
            address=data["address"],
            address2=data["address2"],
            city=data["city"],
            department=data["department"],
            notes=data["notes"],
            subtotal=summary["subtotal"],
            shipping=summary["shipping"],
            total=summary["total"],
            total_weight=summary["total_weight"],
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=line.product,
                    product_name=line.product.name,
                    product_slug=line.product.slug,
                    size=line.size,
                    grind=line.grind,
                    qty=line.qty,
                    unit_price=line.unit_price,
                    unit_weight=line.unit_weight,
                    total=line.total,
                )
                for line in lines
            ]
        )

    try:
        init_point = mp.create_preference(order)
    except mp.MercadoPagoError:
        logger.exception("No se pudo crear la preferencia del pedido %s", order.number)
        order.delete()
        return _render_checkout(
            request, form, lines, cart,
            "No pudimos conectar con Mercado Pago. Intenta de nuevo en unos minutos o escríbenos por WhatsApp.",
        )

    cart.clear()
    request.session["ultimo_pedido"] = str(order.token)
    return redirect(init_point)


@require_GET
def checkout_envio(request):
    """Cotiza el envío para el resumen del checkout (lo usa checkout.js)."""
    cart = Cart(request)
    lines = cart.lines()
    departamento = request.GET.get("departamento", "")
    if departamento not in DEPARTAMENTOS:
        departamento = ""
    summary = _summary(lines, cart, departamento or None)
    return JsonResponse(
        {
            "subtotal": summary["subtotal"],
            "shipping": summary["shipping"],
            "shipping_free": summary["shipping_free"],
            "shipping_known": summary["shipping_known"],
            "total": summary["total"],
        }
    )


# ── Retorno de Mercado Pago ──

STATUS_MESSAGES = {
    Order.PAGADO: "Pago confirmado",
    Order.ENVIADO: "Pedido enviado",
    Order.PENDIENTE: "Esperando confirmación del pago",
    Order.EN_PROCESO: "Pago en proceso",
    Order.RECHAZADO: "Pago rechazado",
    Order.CANCELADO: "Pedido cancelado",
}


@require_GET
def pedido(request, token):
    order = get_object_or_404(Order, token=token)
    payment_id = request.GET.get("payment_id") or request.GET.get("collection_id")
    if payment_id and payment_id != "null" and not order.is_paid and mp.is_configured():
        # Red de seguridad (y modo local): verificar el pago contra la API de MP.
        try:
            mp.sync_payment(payment_id)
        except mp.MercadoPagoError:
            logger.exception("No se pudo verificar el pago %s del pedido %s", payment_id, order.number)
        order.refresh_from_db()
    _ensure_emails(order)
    if request.GET:
        # Quita los parámetros de MP de la URL (evita reverificar al recargar).
        return redirect(order.get_absolute_url())
    return _render_pedido(request, order)


def _render_pedido(request, order: Order, error: str = ""):
    items = list(order.items.all())
    purchase = {
        "transaction_id": order.number,
        "value": order.total,
        "currency": "COP",
        "shipping": order.shipping,
        "items": [
            {"item_id": i.product_slug, "item_name": i.product_name, "price": i.unit_price, "quantity": i.qty}
            for i in items
        ],
    }
    return render(
        request,
        "carrito/pedido.html",
        {
            "order": order,
            "items": items,
            "status_label": STATUS_MESSAGES.get(order.status, order.get_status_display()),
            "purchase": purchase,
            "whatsapp_url": CONTACTO["whatsapp"]["url"],
            "error": error,
        },
        status=400 if error else 200,
    )


@require_GET
def pedido_estado(request, token):
    order = get_object_or_404(Order, token=token)
    # Máximo una consulta a MP cada 8 s por pedido.
    if order.is_waiting and cache.add(f"mp-refresh-{order.token}", 1, 8):
        try:
            order = mp.refresh_order(order)
        except mp.MercadoPagoError:
            logger.warning("No se pudo refrescar el pago del pedido %s", order.number)
    _ensure_emails(order)
    return JsonResponse(
        {"status": order.status, "paid": order.is_paid, "label": STATUS_MESSAGES.get(order.status, "")}
    )


@require_POST
def pedido_reintentar(request, token):
    """Crea una nueva preferencia para el mismo pedido (pago rechazado o abandonado)."""
    order = get_object_or_404(Order, token=token)
    if order.status not in (Order.PENDIENTE, Order.RECHAZADO):
        return redirect(order.get_absolute_url())
    try:
        init_point = mp.create_preference(order)
    except mp.MercadoPagoError:
        logger.exception("No se pudo recrear la preferencia del pedido %s", order.number)
        return _render_pedido(request, order, "No pudimos conectar con Mercado Pago. Intenta de nuevo en unos minutos.")
    return redirect(init_point)


# ── Webhook de Mercado Pago ──

def _notification(request) -> tuple[str, str, bool]:
    """Devuelve (tipo, id, es_ipn) aceptando Webhooks e IPN."""
    body = {}
    if request.body:
        try:
            parsed = json.loads(request.body)
            body = parsed if isinstance(parsed, dict) else {}
        except (ValueError, UnicodeDecodeError):
            body = {}
    q = request.GET
    if q.get("topic"):  # IPN: ?topic=payment&id=123
        return q["topic"], q.get("id", ""), True
    kind = q.get("type") or body.get("type") or body.get("topic") or ""
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    data_id = q.get("data.id") or str(data.get("id") or "") or q.get("id", "")
    if not kind and body.get("action", "").startswith("payment."):
        kind = "payment"
    return str(kind), str(data_id), False


@csrf_exempt
@require_http_methods(["GET", "POST"])
def mercadopago_webhook(request):
    if request.method == "GET":
        # MP (o un humano) a veces prueba la URL con GET: responder 200.
        return HttpResponse("ok")
    kind, data_id, is_ipn = _notification(request)

    secret = settings.MP_WEBHOOK_SECRET
    signature = request.headers.get("x-signature", "")
    # Las notificaciones IPN no traen firma; son seguras igual porque el pago
    # se consulta siempre en la API. Si traen firma, se valida.
    if secret and (signature or not is_ipn):
        valid = mp.verify_signature(
            x_signature=signature,
            x_request_id=request.headers.get("x-request-id", ""),
            data_id=request.GET.get("data.id") or data_id,
            secret=secret,
        )
        if not valid:
            logger.warning("Webhook MP con firma inválida (id=%s)", data_id)
            return JsonResponse({"error": "Firma inválida"}, status=401)

    if kind != "payment" or not data_id:
        return JsonResponse({"ok": True, "ignored": kind or "sin tipo"})

    try:
        order = mp.sync_payment(data_id)
    except mp.MercadoPagoNotConfigured:
        logger.error("Webhook MP recibido pero MP_ACCESS_TOKEN no está configurado")
        return JsonResponse({"error": "No configurado"}, status=500)
    except mp.TransientError:
        logger.exception("Error temporal consultando el pago %s", data_id)
        return JsonResponse({"error": "Reintentar"}, status=500)

    if order is None:
        return JsonResponse({"ok": True, "ignored": "pago sin pedido"})

    if order.is_paid and not order.emails_sent:
        try:
            send_order_emails(order)
        except Exception:  # noqa: BLE001
            # 500 → MP reintenta y el reintento vuelve a intentar los correos.
            return JsonResponse({"error": "Fallo el envío de correos"}, status=500)

    return JsonResponse({"ok": True, "order": order.number, "status": order.status})

