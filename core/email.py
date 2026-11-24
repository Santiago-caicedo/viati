"""Envío de correos con la API HTTP de Resend (equivalente a src/lib/resend.ts).

IMPORTANTE: todo dato que venga del usuario debe pasar por django.utils.html.escape
(o el autoescape de una plantilla) antes de incluirse en el HTML del correo.
"""

import logging
import smtplib

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class EmailError(Exception):
    pass


def send_email(*, to: str | list[str], subject: str, html: str, reply_to: str | None = None) -> None:
    """Envía un correo. Lanza EmailError si Resend no está configurado o falla.

    Con EMAIL_DRY_RUN=true (recomendado en desarrollo) no se envía nada: el correo
    se guarda en tmp_emails/ para revisarlo, así no llegan correos reales a gerencia.
    """
    if settings.EMAIL_DRY_RUN:
        from datetime import datetime

        folder = settings.BASE_DIR / "tmp_emails"
        folder.mkdir(exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".html"
        (folder / name).write_text(
            f"<!-- to: {to} | subject: {subject} | reply_to: {reply_to} -->\n{html}", encoding="utf-8"
        )
        logger.info("EMAIL_DRY_RUN: correo '%s' para %s guardado en tmp_emails/%s", subject, to, name)
        return
    if settings.EMAIL_PROVIDER == "smtp":
        _send_smtp(to=to, subject=subject, html=html, reply_to=reply_to)
        return
    if not settings.RESEND_API_KEY:
        raise EmailError("RESEND_API_KEY no está configurada")

    payload = {
        "from": settings.EMAIL_FROM,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    try:
        response = requests.post(
            RESEND_URL,
            json=payload,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise EmailError(f"No se pudo conectar con Resend: {exc}") from exc

    if response.status_code >= 400:
        logger.error("Resend respondió %s: %s", response.status_code, response.text)
        raise EmailError(f"Resend respondió {response.status_code}")


def _send_smtp(*, to: str | list[str], subject: str, html: str, reply_to: str | None) -> None:
    """Envía por SMTP (Gmail / Google Workspace con contraseña de aplicación)."""
    if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
        raise EmailError("EMAIL_HOST_USER / EMAIL_HOST_PASSWORD no están configurados")
    message = EmailMultiAlternatives(
        subject=subject,
        body=strip_tags(html),
        from_email=settings.EMAIL_FROM,
        to=[to] if isinstance(to, str) else list(to),
        reply_to=[reply_to] if reply_to else None,
    )
    message.attach_alternative(html, "text/html")
    try:
        message.send(fail_silently=False)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("SMTP falló enviando '%s': %s", subject, exc)
        raise EmailError(f"No se pudo enviar por SMTP: {exc}") from exc
