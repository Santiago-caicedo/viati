"""Correos de pedidos pagados.

- Gerencia: mismo diseño del correo "Nuevo Pedido" del webhook de Snipcart original.
- Cliente: confirmación de compra con el mismo estilo de marca.

Las plantillas usan el autoescape de Django: todo dato del cliente se escapa (el
original interpolaba nombre/dirección sin escapar → inyección de HTML).
"""

import logging

from django.conf import settings
from django.template.loader import render_to_string

from core.email import EmailError, send_email

from .models import Order

logger = logging.getLogger(__name__)


def _context(order: Order) -> dict:
    return {
        "order": order,
        "items": list(order.items.all()),
        "order_url": f"{settings.SITE_URL}{order.get_absolute_url()}",
        "site_url": settings.SITE_URL,
    }


def render_gerencia(order: Order) -> str:
    return render_to_string("carrito/emails/gerencia.html", _context(order))


def render_cliente(order: Order) -> str:
    return render_to_string("carrito/emails/cliente.html", _context(order))


def send_order_emails(order: Order, *, force: bool = False) -> bool:
    """Envía los correos de un pedido pagado UNA sola vez.

    Reserva el envío con un UPDATE condicional (emails_sent False → True) para que
    dos notificaciones simultáneas no dupliquen correos. Si falla el correo a
    gerencia se libera la reserva (para reintentar) y se relanza EmailError.
    El correo al cliente es secundario: si falla solo se registra en el log.
    Devuelve True si se enviaron en esta llamada.
    """
    if not order.is_paid:
        return False
    if force:
        Order.objects.filter(pk=order.pk).update(emails_sent=True)
    else:
        claimed = Order.objects.filter(pk=order.pk, emails_sent=False).update(emails_sent=True)
        if not claimed:
            return False
    order.emails_sent = True

    try:
        send_email(
            to=settings.EMAIL_GERENCIA,
            subject=f"☕ Nuevo Pedido Recibido #{order.number}",
            html=render_gerencia(order),
            reply_to=order.email,
        )
    except Exception:
        Order.objects.filter(pk=order.pk).update(emails_sent=False)
        order.emails_sent = False
        logger.exception("No se pudo enviar el correo de gerencia del pedido %s", order.number)
        raise

    try:
        send_email(
            to=order.email,
            subject=f"Confirmamos tu pedido #{order.number} — Viati Café",
            html=render_cliente(order),
        )
    except EmailError:
        logger.exception("No se pudo enviar la confirmación al cliente del pedido %s", order.number)
    return True
