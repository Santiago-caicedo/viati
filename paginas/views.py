"""Vistas de las páginas institucionales: orígenes, nosotros, institucional,
contacto, políticas y los endpoints /api/contact y /api/institucional."""

import json
import logging

from django.conf import settings
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST

from core.email import EmailError, send_email

from .faq import FAQ_ITEMS
from .forms import ContactForm, InstitucionalForm, primer_error
from .nosotros import get_pagina_nosotros
from .origenes import get_all_origenes, get_origen_by_slug

logger = logging.getLogger(__name__)


def _jsonld(data: dict) -> str:
    """JSON-LD seguro para incrustar en <script> (escapa "<", ">" y "&")."""
    texto = json.dumps(data, ensure_ascii=False)
    return texto.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ── Páginas ──

def origenes(request):
    return render(request, "paginas/origenes.html", {"origenes": get_all_origenes()})


def origen_detalle(request, slug):
    origen = get_origen_by_slug(slug)
    if not origen:
        raise Http404("Origen no encontrado")
    breadcrumb = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Inicio", "item": settings.SITE_URL},
            {"@type": "ListItem", "position": 2, "name": "Orígenes", "item": f"{settings.SITE_URL}/origenes"},
            {"@type": "ListItem", "position": 3, "name": origen["name"],
             "item": f"{settings.SITE_URL}/origenes/{origen['slug']}"},
        ],
    }
    tabs = [
        {"id": "clima", "label": "Clima"},
        {"id": "atractivos", "label": "Atractivos"},
    ]
    if origen["caficultor"]:
        tabs.append({"id": "caficultor", "label": "El Caficultor"})
    return render(request, "paginas/origen_detalle.html", {
        "origen": origen,
        "tabs": tabs,
        "breadcrumb_jsonld": _jsonld(breadcrumb),
    })


def nosotros(request):
    return render(request, "paginas/nosotros.html", {"data": get_pagina_nosotros()})


def institucional(request):
    return render(request, "paginas/institucional.html")


def contacto(request):
    return render(request, "paginas/contacto.html")


def politica_envios(request):
    return render(request, "paginas/politicas/envios.html")


def politica_devoluciones(request):
    return render(request, "paginas/politicas/devoluciones.html")


def politica_faq(request):
    return render(request, "paginas/politicas/faq.html", {"faq_items": FAQ_ITEMS})


# ── API de formularios (JSON, igual que las rutas de Next.js) ──

def _leer_json(request, campos_texto: tuple[str, ...]) -> dict | None:
    """Lee el cuerpo JSON. Los campos de texto que no sean string se descartan
    (zod los rechazaría), así el formulario devuelve su mensaje de error."""
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    return {k: v for k, v in body.items() if k not in campos_texto or isinstance(v, str)}


def _linea(texto: str) -> str:
    """Asunto en una sola línea (evita saltos de línea inyectados por el usuario)."""
    return " ".join(texto.split())


@require_POST
def api_contact(request):
    data = _leer_json(request, ("nombre", "apellido", "email", "celular", "mensaje", "website"))
    if data is None:
        return JsonResponse({"error": "Solicitud inválida"}, status=400)

    form = ContactForm(data)
    if not form.is_valid():
        return JsonResponse({"error": primer_error(form)}, status=400)
    if form.es_spam():
        # Respuesta "exitosa" para no dar pistas al bot; no se envía nada.
        return JsonResponse({"success": True})

    d = form.cleaned_data
    try:
        send_email(
            to=settings.EMAIL_GERENCIA,
            reply_to=d["email"],
            subject=_linea(f"Nuevo mensaje de {d['nombre']} {d['apellido']} — Viati Café"),
            # La plantilla escapa (autoescape) todo dato del usuario.
            html=render_to_string("paginas/emails/contacto.html", d),
        )
    except EmailError:
        logger.exception("No se pudo enviar el correo de contacto")
        return JsonResponse({"error": "Error al enviar el correo. Intenta de nuevo."}, status=500)
    return JsonResponse({"success": True})


@require_POST
def api_institucional(request):
    data = _leer_json(request, ("name", "company", "email", "message", "website"))
    if data is None:
        return JsonResponse({"error": "Solicitud inválida"}, status=400)

    form = InstitucionalForm(data)
    if not form.is_valid():
        return JsonResponse({"error": primer_error(form)}, status=400)
    if form.es_spam():
        return JsonResponse({"success": True})

    d = form.cleaned_data
    try:
        send_email(
            to=settings.EMAIL_GERENCIA,
            reply_to=d["email"],
            subject=_linea(f"Nueva solicitud institucional de {d['name']} ({d['company']}) — Viati Café"),
            html=render_to_string("paginas/emails/institucional.html", d),
        )
    except EmailError:
        logger.exception("No se pudo enviar el correo institucional")
        return JsonResponse({"error": "Error al enviar la solicitud. Intenta de nuevo."}, status=500)
    return JsonResponse({"success": True})
