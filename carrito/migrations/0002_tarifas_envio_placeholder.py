"""Siembra tarifas de envío de REFERENCIA (placeholder).

Las tarifas reales vivían en el dashboard de Snipcart y no se conocen: estos
valores solo permiten que el checkout funcione. Ajustarlas en el admin
(Carrito → Tarifas de envío) con las tarifas reales de la transportadora.
"""

from django.db import migrations

# (min_g, max_g, precio local Bogotá, precio nacional) — PLACEHOLDER
TARIFAS = [
    (0, 1000, 9000, 14000),
    (1001, 3000, 12000, 18000),
    (3001, 6000, 16000, 25000),
    (6001, 10000, 22000, 34000),
    (10001, 20000, 30000, 48000),
]


def sembrar(apps, schema_editor):
    ShippingRate = apps.get_model("carrito", "ShippingRate")
    StoreSettings = apps.get_model("carrito", "StoreSettings")
    if not ShippingRate.objects.exists():
        for min_g, max_g, local, nacional in TARIFAS:
            ShippingRate.objects.create(zona="local", min_g=min_g, max_g=max_g, price=local)
            ShippingRate.objects.create(zona="nacional", min_g=min_g, max_g=max_g, price=nacional)
    StoreSettings.objects.get_or_create(pk=1, defaults={"free_shipping_from": 0})


def deshacer(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("carrito", "0001_initial")]
    operations = [migrations.RunPython(sembrar, deshacer)]
