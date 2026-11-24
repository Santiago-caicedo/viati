"""Envía un correo de prueba por SMTP (Gmail / Google Workspace).

Uso:
    python manage.py probar_correo --para correo@ejemplo.com
    python manage.py probar_correo --para correo@ejemplo.com --pedido 6   # correos reales de un pedido

Ignora EMAIL_DRY_RUN: siempre intenta enviar de verdad.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test.utils import override_settings
from django.utils import timezone

from core.email import EmailError, send_email


class Command(BaseCommand):
    help = "Envía un correo de prueba usando la configuración de correo del .env"

    def add_arguments(self, parser):
        parser.add_argument("--para", required=True, help="Destinatario del correo de prueba")
        parser.add_argument("--pedido", type=int, help="ID de un pedido pagado: envía sus 2 correos al destinatario")

    def handle(self, *args, para, pedido=None, **options):
        self.stdout.write(
            f"Proveedor: {settings.EMAIL_PROVIDER} | servidor: {settings.EMAIL_HOST}:{settings.EMAIL_PORT} | "
            f"usuario: {settings.EMAIL_HOST_USER or '(vacío)'} | remitente: {settings.EMAIL_FROM} | "
            f"contraseña: {'definida' if settings.EMAIL_HOST_PASSWORD else 'VACÍA'}"
        )
        with override_settings(EMAIL_DRY_RUN=False):
            try:
                if pedido:
                    self._pedido(pedido, para)
                else:
                    send_email(
                        to=para,
                        subject="Prueba de correo — Viati Café",
                        html=(
                            "<h2>Prueba de correo de Viati Café</h2>"
                            f"<p>Si lees esto, el envío por {settings.EMAIL_PROVIDER.upper()} funciona.</p>"
                            f"<p>Enviado el {timezone.localtime():%Y-%m-%d %H:%M}.</p>"
                        ),
                    )
            except EmailError as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Correo enviado a {para}"))

    def _pedido(self, pk: int, para: str) -> None:
        from carrito.emails import render_cliente, render_gerencia
        from carrito.models import Order

        order = Order.objects.filter(pk=pk).first()
        if order is None:
            raise CommandError(f"No existe el pedido {pk}")
        send_email(to=para, subject=f"[PRUEBA] ☕ Nuevo Pedido Recibido #{order.number}", html=render_gerencia(order))
        send_email(to=para, subject=f"[PRUEBA] Confirmamos tu pedido #{order.number} — Viati Café", html=render_cliente(order))
