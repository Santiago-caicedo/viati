"""Integración con Mercado Pago Checkout Pro vía API REST (sin SDK).

Flujo:
1. create_preference(order) → crea la preferencia y devuelve init_point (URL de pago).
2. Mercado Pago avisa al webhook (/api/mercadopago/webhook) y/o devuelve al cliente a
   /pedido/<token>?payment_id=...; en ambos casos se llama a sync_payment(payment_id),
   que consulta el pago REAL en la API (nunca se confía en el payload) y actualiza el
   pedido de forma idempotente.

IMPORTANTE: todas las URLs que recibe Mercado Pago se arman con settings.SITE_URL.
En el sitio original la notification_url estaba fija a https://viaticafe.com, que
redirigía (308) a www, y por eso los webhooks nunca llegaban.
"""

import hashlib
import hmac
import logging
import uuid

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Order

logger = logging.getLogger(__name__)

API_BASE = "https://api.mercadopago.com"
TIMEOUT = 15
# Tolerancia (COP) al comparar el monto pagado con el total del pedido.
AMOUNT_TOLERANCE = 1


class MercadoPagoError(Exception):
    """Error al hablar con Mercado Pago."""


class MercadoPagoNotConfigured(MercadoPagoError):
    """Falta MP_ACCESS_TOKEN."""


class TransientError(MercadoPagoError):
    """Error temporal (red, 5xx, 429): el webhook responde 500 para que MP reintente."""


def is_configured() -> bool:
    return bool(settings.MP_ACCESS_TOKEN)


def _headers(idempotency: bool = False) -> dict:
    if not settings.MP_ACCESS_TOKEN:
        raise MercadoPagoNotConfigured("MP_ACCESS_TOKEN no está configurado")
    headers = {"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}", "Content-Type": "application/json"}
    if idempotency:
        headers["X-Idempotency-Key"] = str(uuid.uuid4())
    return headers


def absolute_url(path: str) -> str:
    if path.startswith(("http://", "https://")):
        return path
    return settings.SITE_URL + (path if path.startswith("/") else f"/{path}")


def notification_url() -> str:
    return f"{settings.SITE_URL}/api/mercadopago/webhook"


# ── Preferencias ──

def build_preference_payload(order: Order) -> dict:
    items = []
    for item in order.items.all():
        title = item.product_name + (f" ({item.options_label})" if item.options_label else "")
        entry = {
            "id": item.product_slug or str(item.pk),
            "title": title[:250],
            "quantity": item.qty,
            "unit_price": item.unit_price,
            "currency_id": "COP",
            "category_id": "food",
        }
        if item.product is not None:
            entry["picture_url"] = absolute_url(item.product.image_url)
        items.append(entry)
    if order.shipping:
        # El envío va como un ítem aparte: así el total de la preferencia siempre
        # coincide con order.total sin depender del modo de envío de MP.
        items.append(
            {
                "id": "envio",
                "title": f"Envío a {order.city}, {order.department}"[:250],
                "quantity": 1,
                "unit_price": order.shipping,
                "currency_id": "COP",
            }
        )

    first, _, last = order.full_name.strip().partition(" ")
    phone_digits = "".join(ch for ch in order.phone if ch.isdigit())
    back_url = absolute_url(order.get_absolute_url())
    payload = {
        "items": items,
        "payer": {
            "name": first,
            "surname": last,
            "email": order.email,
            "phone": {"area_code": "57", "number": phone_digits[-10:]},
            "identification": {"type": order.document_type, "number": order.document},
            "address": {"street_name": order.address[:100]},
        },
        "external_reference": str(order.token),
        "back_urls": {"success": back_url, "failure": back_url, "pending": back_url},
        "statement_descriptor": "VIATICAFE",
        "metadata": {"order_number": order.number},
    }
    # Mercado Pago rechaza auto_return (y no puede entregar webhooks) si SITE_URL no es
    # https público, p. ej. http://localhost en desarrollo. En local el cliente vuelve con
    # el botón "Volver al sitio" y /pedido/<token> verifica el pago.
    if settings.SITE_URL.startswith("https://"):
        payload["auto_return"] = "approved"
        payload["notification_url"] = notification_url()
    return payload


def create_preference(order: Order) -> str:
    """Crea la preferencia de pago y devuelve la URL init_point."""
    payload = build_preference_payload(order)
    try:
        response = requests.post(
            f"{API_BASE}/checkout/preferences", json=payload, headers=_headers(idempotency=True), timeout=TIMEOUT
        )
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo conectar con Mercado Pago: {exc}") from exc
    if response.status_code >= 400:
        logger.error("MP preferencia %s: %s", response.status_code, response.text[:500])
        raise MercadoPagoError(f"Mercado Pago respondió {response.status_code}")
    data = response.json()
    init_point = data.get("init_point") or data.get("sandbox_init_point")
    if not init_point:
        raise MercadoPagoError("Mercado Pago no devolvió init_point")
    Order.objects.filter(pk=order.pk).update(mp_preference_id=str(data.get("id", "")))
    order.mp_preference_id = str(data.get("id", ""))
    return init_point


# ── Pagos ──

def get_payment(payment_id: str) -> dict | None:
    """Consulta un pago. Devuelve None si no existe (404). TransientError si falla la red/5xx."""
    try:
        response = requests.get(f"{API_BASE}/v1/payments/{payment_id}", headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise TransientError(f"No se pudo conectar con Mercado Pago: {exc}") from exc
    if response.status_code == 404:
        return None
    if response.status_code == 429 or response.status_code >= 500:
        raise TransientError(f"Mercado Pago respondió {response.status_code}")
    if response.status_code in (401, 403):
        # Token vencido o inválido: es un problema nuestro, no del pago. Se trata como
        # temporal para que el webhook responda 500 y MP reintente cuando se corrija.
        logger.error("MP rechazó las credenciales (%s) al consultar el pago %s", response.status_code, payment_id)
        raise TransientError(f"Credenciales de Mercado Pago rechazadas ({response.status_code})")
    if response.status_code >= 400:
        logger.error("MP pago %s respondió %s: %s", payment_id, response.status_code, response.text[:300])
        return None
    return response.json()


def find_payments(order: Order) -> list[dict]:
    """Busca los pagos de un pedido por external_reference (red de seguridad)."""
    try:
        response = requests.get(
            f"{API_BASE}/v1/payments/search",
            params={"external_reference": str(order.token), "sort": "date_created", "criteria": "desc"},
            headers=_headers(),
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise TransientError(str(exc)) from exc
    if response.status_code >= 400:
        raise TransientError(f"Mercado Pago respondió {response.status_code}")
    return response.json().get("results", []) or []


def sync_payment(payment_id: str) -> Order | None:
    """Consulta el pago en MP y actualiza el pedido correspondiente.

    Devuelve el pedido actualizado o None si el pago no existe o no corresponde
    a ningún pedido de esta tienda. Lanza TransientError en errores temporales.
    """
    payment = get_payment(str(payment_id))
    if not payment:
        logger.info("Pago MP %s no encontrado; se ignora", payment_id)
        return None
    return apply_payment(payment)


def apply_payment(payment: dict) -> Order | None:
    reference = str(payment.get("external_reference") or "")
    try:
        token = uuid.UUID(reference)
    except ValueError:
        logger.info("Pago MP %s sin external_reference válido (%r); se ignora", payment.get("id"), reference)
        return None

    with transaction.atomic():
        order = Order.objects.select_for_update().filter(token=token).first()
        if order is None:
            logger.warning("Pago MP %s apunta a un pedido inexistente %s", payment.get("id"), token)
            return None
        _update_order(order, payment)
    return order


def _update_order(order: Order, payment: dict) -> None:
    payment_id = str(payment.get("id", ""))
    mp_status = str(payment.get("status", ""))
    detail = str(payment.get("status_detail", ""))
    amount = payment.get("transaction_amount")
    currency = payment.get("currency_id")

    if order.is_paid:
        # Ya pagado: solo un reembolso/contracargo del MISMO pago lo cambia.
        if payment_id == order.mp_payment_id and mp_status in ("refunded", "charged_back"):
            order.status = Order.CANCELADO
            order.mp_status, order.mp_status_detail = mp_status, detail
            order.save()
        return

    order.mp_payment_id = payment_id
    order.mp_status = mp_status
    order.mp_status_detail = detail

    if mp_status == "approved":
        try:
            amount_ok = abs(float(amount) - order.total) <= AMOUNT_TOLERANCE
        except (TypeError, ValueError):
            amount_ok = False
        if amount_ok and currency == "COP":
            order.mark_paid()
        else:
            note = (
                f"[{timezone.now():%Y-%m-%d %H:%M}] Pago {payment_id} aprobado pero NO coincide: "
                f"monto {amount} {currency} vs total {order.total} COP. Revisar manualmente."
            )
            logger.error("Pedido %s: %s", order.number, note)
            order.payment_note = (order.payment_note + "\n" + note).strip()
            order.status = Order.EN_PROCESO
    elif mp_status in ("pending", "in_process", "in_mediation", "authorized"):
        order.status = Order.EN_PROCESO
    elif mp_status in ("rejected", "cancelled"):
        order.status = Order.RECHAZADO
    elif mp_status in ("refunded", "charged_back"):
        order.status = Order.CANCELADO
    order.save()


def refresh_order(order: Order) -> Order:
    """Vuelve a consultar MP para un pedido aún no pagado (polling de /pedido/<token>/estado)."""
    if order.is_paid or not is_configured():
        return order
    if order.mp_payment_id:
        updated = sync_payment(order.mp_payment_id)
    else:
        results = find_payments(order)
        approved = [p for p in results if p.get("status") == "approved"]
        chosen = (approved or results or [None])[0]
        updated = apply_payment(chosen) if chosen else None
    return updated or order


# ── Firma de webhooks ──

def verify_signature(*, x_signature: str, x_request_id: str, data_id: str, secret: str) -> bool:
    """Valida la cabecera x-signature según la documentación de Mercado Pago.

    Plantilla: "id:{data.id};request-id:{x-request-id};ts:{ts};" (las partes que no
    vengan en la notificación se omiten). data.id alfanumérico va en minúsculas.
    """
    parts = {}
    for chunk in (x_signature or "").split(","):
        key, _, value = chunk.strip().partition("=")
        if key and value:
            parts[key.strip()] = value.strip()
    ts, v1 = parts.get("ts"), parts.get("v1")
    if not ts or not v1:
        return False
    manifest = ""
    if data_id:
        manifest += f"id:{data_id.lower()};"
    if x_request_id:
        manifest += f"request-id:{x_request_id};"
    manifest += f"ts:{ts};"
    expected = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
