"""Seguridad del panel: quién entra, bloqueo por intentos fallidos y cabeceras.

- Solo entran usuarios activos con is_staff (los mismos que pueden entrar al /admin).
- 5 intentos fallidos en 15 min (por IP o por usuario) bloquean el inicio de sesión 15 min.
- Todas las páginas del panel salen con no-store (no quedan en caché del navegador
  ni de proxies) y noindex (no aparecen en buscadores).
"""

import functools
import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache

logger = logging.getLogger("panel.seguridad")

MAX_INTENTOS = 5
VENTANA_SEGUNDOS = 15 * 60


def puede_entrar(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


def ip_cliente(request) -> str:
    # Detrás de un proxy (Railway/Render) la IP real viene en X-Forwarded-For.
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        reenviada = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if reenviada:
            return reenviada.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "desconocida"


def _claves(request, usuario: str) -> list[str]:
    usuario_hash = hashlib.sha256((usuario or "").strip().lower().encode()).hexdigest()[:24]
    return [f"panel-login-ip:{ip_cliente(request)}", f"panel-login-user:{usuario_hash}"]


def esta_bloqueado(request, usuario: str) -> bool:
    return any((cache.get(clave) or 0) >= MAX_INTENTOS for clave in _claves(request, usuario))


def registrar_fallo(request, usuario: str) -> None:
    for clave in _claves(request, usuario):
        if not cache.add(clave, 1, VENTANA_SEGUNDOS):
            try:
                cache.incr(clave)
            except ValueError:
                cache.set(clave, 1, VENTANA_SEGUNDOS)
    logger.warning("Intento fallido de ingreso al panel (usuario=%r, ip=%s)", usuario, ip_cliente(request))


def limpiar_fallos(request, usuario: str) -> None:
    cache.delete_many(_claves(request, usuario))


def con_cabeceras_privadas(response):
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["X-Frame-Options"] = "DENY"
    return response


def panel_requerido(vista):
    """Exige sesión de personal autorizado; si no, manda al login del panel."""

    @functools.wraps(vista)
    @never_cache
    def envoltura(request, *args, **kwargs):
        if not puede_entrar(request.user):
            destino = reverse("panel:login") + "?" + urlencode({"next": request.get_full_path()})
            return redirect(destino)
        return con_cabeceras_privadas(vista(request, *args, **kwargs))

    return envoltura
