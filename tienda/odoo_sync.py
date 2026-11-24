"""Sincronización del catálogo con Odoo.

- aplicar(data): guarda en la base de datos los productos leídos de Odoo
  (lo usan el comando `sincronizar_odoo` y la sincronización automática).
- sincronizar_si_toca(): equivalente al `revalidate: 300` de Next.js. Las vistas
  de la tienda la llaman en cada visita; si pasaron ODOO_SYNC_MINUTOS desde el
  último intento, lanza la sincronización en un hilo y la página responde de
  inmediato con lo que ya hay en la base de datos. Sin Celery ni cron.

Varias copias del servidor (workers) no se pisan: el turno se reserva con un
UPDATE condicional sobre OdooSyncState, así que solo una sincroniza por intervalo.
Si Odoo falla no se cambia nada y se reintenta en el siguiente intervalo.
"""

import logging
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from . import odoo
from .models import OdooSyncState, Product

logger = logging.getLogger(__name__)

# Las pruebas lo ponen en False para ejecutar la sincronización en línea.
EN_HILO = True
# Con el turno ocupado por otro worker, no volver a mirar la BD antes de esto.
REINTENTO_LOCAL_SEGUNDOS = 60

_lock = threading.Lock()
_proxima_revision = 0.0  # reloj monotónico de este proceso


# ── Guardar productos ──

def aplicar(data: list[dict], *, solo_odoo: bool = False) -> tuple[int, int, int]:
    """Crea/actualiza productos por odoo_id. Devuelve (creados, actualizados, desactivados).

    Todo ocurre en una transacción: si algo falla no queda nada a medias.
    """
    with transaction.atomic():
        creados, actualizados, by_slug = _upsert(data)
        _link(data, by_slug)

        ids = [item["odoo_id"] for item in data]
        ocultos = (
            Product.objects.filter(odoo_id__isnull=False, active=True).exclude(odoo_id__in=ids).update(active=False)
        )
        if solo_odoo:
            ocultos += Product.objects.filter(odoo_id__isnull=True, active=True).update(active=False)
    return creados, actualizados, ocultos


def _upsert(data: list[dict]):
    creados = actualizados = 0
    by_slug: dict[str, Product] = {}

    for order, item in enumerate(data):
        product = Product.objects.filter(odoo_id=item["odoo_id"]).first()
        if product is None:
            product = Product.objects.filter(slug=item["slug"], odoo_id__isnull=True).first()

        slug = item["slug"]
        clash = Product.objects.filter(slug=slug)
        if product is not None:
            clash = clash.exclude(pk=product.pk)
        if clash.exists():
            slug = f"{slug}-{item['odoo_id']}"

        fields = {
            "odoo_id": item["odoo_id"],
            "slug": slug,
            "name": item["name"],
            "description": item["description"],
            "category": item["category"],
            "image_url_external": item["image"],
            "price": int(round(item["price"])),
            "weight": int(item["weight"]),
            "featured": item["featured"],
            "order": order,
            "active": True,
        }
        if product is None:
            product = Product.objects.create(**fields)
            creados += 1
        else:
            for key, value in fields.items():
                setattr(product, key, value)
            product.save()
            actualizados += 1

        # En Odoo el precio es por producto: sin tamaños.
        product.sizes.all().delete()
        by_slug[item["slug"]] = product

    return creados, actualizados, by_slug


def _link(data: list[dict], by_slug: dict[str, Product]):
    for item in data:
        product = by_slug[item["slug"]]
        product.optional_products.set([by_slug[s] for s in item["optional_slugs"] if s in by_slug])
        product.accessory_products.set([by_slug[s] for s in item["accessory_slugs"] if s in by_slug])


# ── Sincronización automática ──

def intervalo_segundos() -> int:
    """Segundos entre sincronizaciones; 0 = automática apagada o sin datos de Odoo."""
    minutos = getattr(settings, "ODOO_SYNC_MINUTOS", 0)
    configurado = all((settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_USER, settings.ODOO_API_KEY))
    return minutos * 60 if minutos > 0 and configurado else 0


def sincronizar_si_toca() -> bool:
    """Lanza la sincronización si ya pasó el intervalo. Nunca rompe la página.

    Devuelve True si esta llamada inició una sincronización.
    """
    global _proxima_revision
    segundos = intervalo_segundos()
    if segundos <= 0:
        return False
    ahora = time.monotonic()
    with _lock:
        if ahora < _proxima_revision:
            return False
        _proxima_revision = ahora + min(segundos, REINTENTO_LOCAL_SEGUNDOS)

    try:
        if not _reservar_turno(segundos):
            return False
    except DatabaseError:
        logger.exception("[odoo-sync] No se pudo reservar el turno de sincronización")
        return False

    with _lock:
        _proxima_revision = time.monotonic() + segundos
    if EN_HILO:
        threading.Thread(target=_ejecutar_en_hilo, name="odoo-sync", daemon=True).start()
    else:
        _ejecutar()
    return True


def _reservar_turno(segundos: int) -> bool:
    """True solo para UN proceso por intervalo (UPDATE condicional = atómico)."""
    OdooSyncState.objects.get_or_create(pk=1)
    ahora = timezone.now()
    limite = ahora - timedelta(seconds=segundos)
    return (
        OdooSyncState.objects.filter(pk=1)
        .filter(Q(started_at__isnull=True) | Q(started_at__lte=limite))
        .update(started_at=ahora)
        == 1
    )


def _ejecutar_en_hilo() -> None:
    try:
        _ejecutar()
    finally:
        connection.close()  # la conexión del hilo no la cierra Django


def _ejecutar() -> None:
    try:
        data = odoo.fetch_products()
        if not data:
            ok, mensaje = False, "Odoo devolvió 0 productos; no se modificó el catálogo."
            logger.warning("[odoo-sync] %s", mensaje)
        else:
            creados, actualizados, ocultos = aplicar(data, solo_odoo=getattr(settings, "ODOO_SYNC_SOLO_ODOO", False))
            ok = True
            mensaje = f"{creados} creados, {actualizados} actualizados, {ocultos} desactivados."
            logger.info("[odoo-sync] %s", mensaje)
    except Exception as error:  # noqa: BLE001 — la tienda sigue con el catálogo anterior
        ok, mensaje = False, f"{type(error).__name__}: {error}"[:500]
        logger.exception("[odoo-sync] Falló la sincronización; se conserva el catálogo anterior")
    try:
        OdooSyncState.objects.filter(pk=1).update(finished_at=timezone.now(), ok=ok, message=mensaje)
    except DatabaseError:
        logger.exception("[odoo-sync] No se pudo guardar el resultado")
