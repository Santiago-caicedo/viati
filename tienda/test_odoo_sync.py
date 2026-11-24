"""Pruebas de la sincronización automática con Odoo (Odoo simulado con mock)."""

from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from tienda import odoo, odoo_sync
from tienda.models import OdooSyncState, Product, ProductSize


def item(odoo_id: int, slug: str, price: int = 40000, **extra) -> dict:
    return {
        "odoo_id": odoo_id, "slug": slug, "name": slug.replace("-", " ").title(), "description": "desc",
        "category": "Café", "image": f"/api/odoo-image/{odoo_id}", "price": price, "weight": 350,
        "featured": True, "optional_slugs": [], "accessory_slugs": [], **extra,
    }


ODOO_ON = dict(ODOO_URL="https://odoo.example.com", ODOO_DB="db", ODOO_USER="u@example.com", ODOO_API_KEY="k")


@override_settings(**ODOO_ON, ODOO_SYNC_MINUTOS=5, ODOO_SYNC_SOLO_ODOO=False)
class SyncAutomatica(TestCase):
    def setUp(self):
        odoo_sync._proxima_revision = 0.0
        patcher = mock.patch.object(odoo_sync, "EN_HILO", False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.local = Product.objects.create(slug="local", name="Local", price=10000, weight=100)

    def fetch(self, **kwargs):
        return mock.patch.object(odoo, "fetch_products", **kwargs)

    def test_apagada_por_defecto(self):
        with override_settings(ODOO_SYNC_MINUTOS=0), self.fetch() as fetch:
            self.assertEqual(self.client.get("/tienda").status_code, 200)
        fetch.assert_not_called()

    def test_sin_datos_de_odoo_no_consulta(self):
        with override_settings(ODOO_API_KEY=""), self.fetch() as fetch:
            self.assertEqual(self.client.get("/tienda").status_code, 200)
        fetch.assert_not_called()

    def test_visita_sincroniza_una_vez_por_intervalo(self):
        with self.fetch(return_value=[item(7, "cafe-odoo", 45000)]) as fetch:
            for url in ("/tienda", "/", "/tienda/cafe-odoo", "/tienda"):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(Product.objects.get(odoo_id=7).price, 45000)
        self.assertTrue(Product.objects.get(slug="local").active)  # los locales no se ocultan
        state = OdooSyncState.objects.get(pk=1)
        self.assertTrue(state.ok)
        self.assertIn("1 creados", state.message)

    def test_vuelve_a_sincronizar_al_pasar_el_intervalo(self):
        with self.fetch(return_value=[item(7, "cafe-odoo", 45000)]) as fetch:
            self.client.get("/tienda")
            # Simula que pasaron 6 minutos (en este proceso y en la BD).
            odoo_sync._proxima_revision = 0.0
            OdooSyncState.objects.update(started_at=timezone.now() - timedelta(minutes=6))
            fetch.return_value = [item(7, "cafe-odoo", 48000)]
            self.client.get("/tienda")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(Product.objects.get(odoo_id=7).price, 48000)

    def test_otro_worker_ya_tiene_el_turno(self):
        OdooSyncState.objects.create(pk=1, started_at=timezone.now() - timedelta(minutes=1))
        with self.fetch() as fetch:
            self.client.get("/tienda")
        fetch.assert_not_called()

    def test_si_odoo_falla_la_tienda_sigue_igual(self):
        with self.fetch(side_effect=odoo.OdooError("Odoo caído")):
            r = self.client.get("/tienda")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Local")
        state = OdooSyncState.objects.get(pk=1)
        self.assertFalse(state.ok)
        self.assertIn("Odoo caído", state.message)

    def test_cero_productos_no_cambia_nada(self):
        with self.fetch(return_value=[]):
            self.client.get("/tienda")
        self.assertEqual(Product.objects.filter(active=True).count(), 1)
        self.assertFalse(OdooSyncState.objects.get(pk=1).ok)

    def test_error_al_guardar_no_deja_datos_a_medias(self):
        roto = item(8, "roto")
        del roto["weight"]  # hace fallar el segundo producto
        with self.fetch(return_value=[item(7, "cafe-odoo"), roto]):
            self.assertEqual(self.client.get("/tienda").status_code, 200)
        self.assertFalse(Product.objects.filter(odoo_id__isnull=False).exists())

    def test_solo_odoo_oculta_los_locales(self):
        with override_settings(ODOO_SYNC_SOLO_ODOO=True), self.fetch(return_value=[item(7, "cafe-odoo")]):
            self.client.get("/tienda")
        self.assertFalse(Product.objects.get(slug="local").active)

    def test_adopta_producto_con_mismo_slug_y_quita_tamanos(self):
        ProductSize.objects.create(product=self.local, name="350g", price=10000, weight=350)
        with self.fetch(return_value=[item(9, "local", 52000)]):
            self.client.get("/tienda")
        self.local.refresh_from_db()
        self.assertEqual((self.local.odoo_id, self.local.price, self.local.sizes.count()), (9, 52000, 0))
        self.assertEqual(Product.objects.count(), 1)

    def test_producto_que_sale_de_odoo_se_desactiva(self):
        with self.fetch(return_value=[item(7, "a"), item(8, "b")]) as fetch:
            self.client.get("/tienda")
            odoo_sync._proxima_revision = 0.0
            OdooSyncState.objects.update(started_at=None)
            fetch.return_value = [item(7, "a")]
            self.client.get("/tienda")
        self.assertFalse(Product.objects.get(odoo_id=8).active)
        self.assertTrue(Product.objects.get(odoo_id=7).active)


@override_settings(**ODOO_ON)
class ComandoSincronizar(TestCase):
    def test_comando_sigue_funcionando(self):
        with mock.patch.object(odoo, "fetch_products", return_value=[item(7, "cafe-odoo", 45000)]):
            call_command("sincronizar_odoo", stdout=mock.Mock())
        self.assertEqual(Product.objects.get(odoo_id=7).price, 45000)

    def test_dry_run_no_guarda(self):
        with mock.patch.object(odoo, "fetch_products", return_value=[item(7, "cafe-odoo")]):
            call_command("sincronizar_odoo", "--dry-run", stdout=mock.Mock())
        self.assertFalse(Product.objects.exists())
