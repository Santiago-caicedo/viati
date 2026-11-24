"""Cálculo del costo de envío (reemplaza las tarifas por peso del dashboard de Snipcart).

Política (src/app/politicas/envios): envíos nacionales en 2 a 5 días hábiles, costo
según el peso del pedido y el destino. Los envíos internacionales NO se venden por
el checkout: se coordinan por WhatsApp.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 32 departamentos + Bogotá D.C. (orden alfabético, Bogotá primero por ser el más común).
DEPARTAMENTOS = [
    "Bogotá D.C.",
    "Amazonas",
    "Antioquia",
    "Arauca",
    "Atlántico",
    "Bolívar",
    "Boyacá",
    "Caldas",
    "Caquetá",
    "Casanare",
    "Cauca",
    "Cesar",
    "Chocó",
    "Córdoba",
    "Cundinamarca",
    "Guainía",
    "Guaviare",
    "Huila",
    "La Guajira",
    "Magdalena",
    "Meta",
    "Nariño",
    "Norte de Santander",
    "Putumayo",
    "Quindío",
    "Risaralda",
    "San Andrés y Providencia",
    "Santander",
    "Sucre",
    "Tolima",
    "Valle del Cauca",
    "Vaupés",
    "Vichada",
]

# Departamentos que cotizan con la tarifa de zona "local".
ZONA_LOCAL_DEPARTAMENTOS = {"Bogotá D.C."}


@dataclass
class ShippingQuote:
    price: int
    free: bool = False
    zona: str = ""
    available: bool = True


def quote(*, weight_g: int, departamento: str, subtotal: int) -> ShippingQuote:
    """Cotiza el envío nacional para un pedido.

    - Envío gratis si el subtotal supera el umbral de StoreSettings (si está activo).
    - Busca primero una tarifa específica del departamento y luego la de la zona.
    - Si el peso supera todos los rangos se usa la tarifa del rango más alto.
    """
    from .models import ShippingRate, StoreSettings

    zona = ShippingRate.zona_para(departamento)
    settings_obj = StoreSettings.load()
    if settings_obj.free_shipping_from and subtotal >= settings_obj.free_shipping_from:
        return ShippingQuote(price=0, free=True, zona=zona)

    rates = ShippingRate.objects.filter(active=True)
    for candidates in (rates.filter(departamento=departamento), rates.filter(departamento="", zona=zona)):
        candidates = list(candidates.order_by("min_g"))
        if not candidates:
            continue
        for rate in candidates:
            if rate.min_g <= weight_g <= rate.max_g:
                return ShippingQuote(price=rate.price, zona=zona)
        return ShippingQuote(price=max(candidates, key=lambda r: r.max_g).price, zona=zona)

    logger.warning("No hay tarifas de envío para %s (zona %s); se cobra $0", departamento, zona)
    return ShippingQuote(price=0, zona=zona, available=False)
