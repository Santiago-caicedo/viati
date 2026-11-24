"""Panel de estadísticas de la tienda (dentro de /admin, solo personal autorizado).

Ventas = pedidos pagados o enviados, contados por la fecha de pago (hora de Bogotá).
Abandonados = pedidos que llegaron al checkout y no se pagaron (pendientes o
rechazados con más de 1 hora de creados).
"""

from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from .models import Order, OrderItem

PERIODOS = {7: "Últimos 7 días", 30: "Últimos 30 días", 90: "Últimos 90 días", 365: "Último año"}
ABANDONO_TRAS = timedelta(hours=1)


def _pagados():
    return Order.objects.filter(status__in=Order.PAID_STATUSES, paid_at__isnull=False)


def _resumen(qs) -> dict:
    data = qs.aggregate(pedidos=Count("id"), ingresos=Sum("total"), envios=Sum("shipping"))
    pedidos = data["pedidos"] or 0
    ingresos = data["ingresos"] or 0
    return {
        "pedidos": pedidos,
        "ingresos": ingresos,
        "envios": data["envios"] or 0,
        "ticket": round(ingresos / pedidos) if pedidos else 0,
    }


def _serie_diaria(desde, hasta) -> list[dict]:
    """Ingresos y pedidos por día, incluyendo los días sin ventas."""
    tz = timezone.get_current_timezone()
    filas = (
        _pagados()
        .filter(paid_at__date__gte=desde, paid_at__date__lte=hasta)
        .annotate(dia=TruncDate("paid_at", tzinfo=tz))
        .values("dia")
        .annotate(pedidos=Count("id"), ingresos=Sum("total"))
    )
    por_dia = {f["dia"]: f for f in filas}
    serie = []
    dia = desde
    while dia <= hasta:
        fila = por_dia.get(dia, {})
        serie.append({"dia": dia, "pedidos": fila.get("pedidos", 0), "ingresos": fila.get("ingresos") or 0})
        dia += timedelta(days=1)
    maximo = max((d["ingresos"] for d in serie), default=0)
    for d in serie:
        d["altura"] = round(d["ingresos"] / maximo * 100, 1) if maximo else 0
        d["es_max"] = bool(maximo) and d["ingresos"] == maximo
    return serie


def periodo_dias(valor) -> int:
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        return 30
    return dias if dias in PERIODOS else 30


def estadisticas(request):
    """Vista del admin (/admin/estadisticas/)."""
    context = {
        **admin.site.each_context(request),
        "title": "Estadísticas de la tienda",
        **calcular(periodo_dias(request.GET.get("dias", 30))),
    }
    return render(request, "admin/estadisticas.html", context)


def calcular(dias: int = 30) -> dict:
    """Todas las cifras del panel (las usan el admin y /panel)."""
    ahora = timezone.now()
    hoy = timezone.localdate()
    dias = periodo_dias(dias)
    desde = hoy - timedelta(days=dias - 1)

    pagados = _pagados()
    kpis = [
        {"titulo": "Hoy", **_resumen(pagados.filter(paid_at__date=hoy))},
        {"titulo": "Últimos 7 días", **_resumen(pagados.filter(paid_at__date__gte=hoy - timedelta(days=6)))},
        {"titulo": "Este mes", **_resumen(pagados.filter(paid_at__date__gte=hoy.replace(day=1)))},
        {"titulo": "Desde el inicio", **_resumen(pagados)},
    ]

    # ── Periodo seleccionado ──
    periodo_pagados = pagados.filter(paid_at__date__gte=desde)
    creados = Order.objects.filter(created_at__date__gte=desde)
    abandonados_qs = creados.filter(
        status__in=(Order.PENDIENTE, Order.RECHAZADO), created_at__lte=ahora - ABANDONO_TRAS
    )
    total_creados = creados.count()
    pagados_creados = creados.filter(status__in=Order.PAID_STATUSES).count()

    estados = {row["status"]: row["n"] for row in creados.values("status").annotate(n=Count("id"))}
    por_estado = [
        {"codigo": codigo, "nombre": nombre, "n": estados.get(codigo, 0)} for codigo, nombre in Order.STATUS_CHOICES
    ]

    top_productos = list(
        OrderItem.objects.filter(order__in=periodo_pagados)
        .values("product_name")
        .annotate(unidades=Sum("qty"), ingresos=Sum("total"), pedidos=Count("order", distinct=True))
        .order_by("-ingresos", "product_name")[:10]
    )
    top_presentaciones = list(
        OrderItem.objects.filter(order__in=periodo_pagados)
        .values("product_name", "size", "grind")
        .annotate(unidades=Sum("qty"))
        .order_by("-unidades", "product_name")[:10]
    )
    por_departamento = list(
        periodo_pagados.values("department")
        .annotate(pedidos=Count("id"), ingresos=Sum("total"))
        .order_by("-ingresos", "department")
    )
    por_ciudad = list(
        periodo_pagados.values("city", "department")
        .annotate(pedidos=Count("id"), ingresos=Sum("total"))
        .order_by("-pedidos", "-ingresos")[:10]
    )

    # Clientes que repiten (por correo), en todo el histórico.
    clientes = pagados.values("email").annotate(n=Count("id"))
    total_clientes = clientes.count()
    recurrentes = clientes.filter(n__gt=1).count()

    por_enviar = list(pagados.filter(status=Order.PAGADO).order_by("paid_at")[:50])
    for order in por_enviar:
        order.dias_esperando = (hoy - timezone.localtime(order.paid_at).date()).days

    abandonados = abandonados_qs.aggregate(n=Count("id"), valor=Sum("total"))
    ultimos_abandonados = list(abandonados_qs.order_by("-created_at")[:15])

    serie = _serie_diaria(desde, hoy)
    return {
        "dias": dias,
        "periodos": PERIODOS,
        "periodo_nombre": PERIODOS[dias],
        "desde": desde,
        "hoy": hoy,
        "kpis": kpis,
        "periodo": _resumen(periodo_pagados),
        "serie": serie,
        "serie_tiene_ventas": any(d["ingresos"] for d in serie),
        "por_estado": por_estado,
        "total_creados": total_creados,
        "conversion": round(pagados_creados / total_creados * 100) if total_creados else None,
        "top_productos": top_productos,
        "top_presentaciones": top_presentaciones,
        "por_departamento": por_departamento,
        "por_ciudad": por_ciudad,
        "total_clientes": total_clientes,
        "recurrentes": recurrentes,
        "por_enviar": por_enviar,
        "por_enviar_total": pagados.filter(status=Order.PAGADO).count(),
        "abandonados_n": abandonados["n"] or 0,
        "abandonados_valor": abandonados["valor"] or 0,
        "ultimos_abandonados": ultimos_abandonados,
        "rechazados_n": creados.filter(status=Order.RECHAZADO).count(),
        "revisar_n": Order.objects.filter(status=Order.EN_PROCESO).exclude(payment_note="").count(),
        "correos_pendientes": pagados.filter(emails_sent=False).count(),
    }


def vista_estadisticas():
    """La vista protegida por el login del admin (solo usuarios con acceso al panel)."""
    return admin.site.admin_view(estadisticas)
