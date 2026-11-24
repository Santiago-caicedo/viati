"""Pruebas del carrito, checkout y Mercado Pago (sin llamar a la API real)."""

import hashlib
import hmac
import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from tienda.models import Product, ProductSize

from .models import Order, ShippingRate

SITE = "https://www.viaticafe.com"
CHECKOUT_DATA = {
    "full_name": "Ana <b>Pérez</b>",
    "email": "ana@example.com",
    "phone": "300 123 4567",
    "document_type": "CC",
    "document": "1.098.765.432",
    "address": "Calle 30 # 14-48",
    "address2": "Apto 201",
    "city": "Bucaramanga",
    "department": "Santander",
    "notes": "<script>alert(1)</script>",
}


def fake_response(status=200, data=None):
    response = mock.Mock()
    response.status_code = status
    response.json.return_value = data or {}
    response.text = json.dumps(data or {})
    return response


@override_settings(
    SITE_URL=SITE,
    MP_ACCESS_TOKEN="TEST-token",
    MP_WEBHOOK_SECRET="",
    EMAIL_DRY_RUN=False,
    RESEND_API_KEY="re_test",
    EMAIL_PROVIDER="resend",
    EMAIL_GERENCIA="gerencia@example.com",
)
class BaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.product = Product.objects.create(
            slug="cafe-prueba", name="Café Prueba", price=0, weight=0, grind_options=["Grano", "Molido"]
        )
        ProductSize.objects.create(product=self.product, name="250 g", price=30000, weight=250)
        ProductSize.objects.create(product=self.product, name="500 g", price=52000, weight=500)
        # Tarifas propias de la prueba (independientes de la migración placeholder).
        ShippingRate.objects.all().delete()
        ShippingRate.objects.create(zona="nacional", min_g=0, max_g=1000, price=15000)
        ShippingRate.objects.create(zona="nacional", min_g=1001, max_g=5000, price=20000)
        ShippingRate.objects.create(zona="local", min_g=0, max_g=5000, price=8000)

    def post_json(self, url, data, **extra):
        return self.client.post(url, json.dumps(data), content_type="application/json", **extra)

    def add_item(self, qty=2, size="500 g"):
        return self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "size": size, "grind": "Molido", "qty": qty})

    def create_order(self):
        self.add_item()
        pref = fake_response(201, {"id": "pref-1", "init_point": "https://mp.test/checkout?pref=1"})
        with mock.patch("carrito.mercadopago.requests.post", return_value=pref) as post:
            response = self.client.post("/checkout", CHECKOUT_DATA)
        return Order.objects.get(), response, post


class CartApiTests(BaseCase):
    def test_add_update_remove(self):
        response = self.add_item(qty=2)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["subtotal"], 104000)  # precio desde la BD, no del cliente
        item = data["items"][0]
        self.assertEqual(item["options"], "500 g · Molido")
        self.assertEqual(data["added"]["qty_added"], 2)

        key = item["key"]
        data = self.post_json("/carrito/actualizar", {"key": key, "qty": 5}).json()
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["subtotal"], 260000)

        data = self.client.get("/carrito/estado").json()
        self.assertEqual(data["count"], 5)

        data = self.post_json("/carrito/eliminar", {"key": key}).json()
        self.assertEqual(data["count"], 0)
        self.assertEqual(data["items"], [])

    def test_validation(self):
        self.assertEqual(self.post_json("/carrito/agregar", {"slug": "no-existe"}).status_code, 404)
        self.product.active = False
        self.product.save()
        self.assertEqual(self.add_item().status_code, 404)
        self.product.active = True
        self.product.save()
        self.assertEqual(self.add_item(qty=0).status_code, 400)
        self.assertEqual(self.add_item(qty=100).status_code, 400)
        self.assertEqual(self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "qty": "x"}).status_code, 400)
        self.assertEqual(self.post_json("/carrito/actualizar", {"key": "nada", "qty": 1}).status_code, 404)

    def test_csrf_required(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post("/carrito/agregar", json.dumps({"slug": "cafe-prueba"}), content_type="application/json")
        self.assertEqual(response.status_code, 403)


class CheckoutTests(BaseCase):
    def test_empty_cart_redirects(self):
        response = self.client.get("/checkout")
        self.assertRedirects(response, "/tienda", fetch_redirect_response=False)

    def test_get_renders_summary(self):
        self.add_item()
        response = self.client.get("/checkout")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Café Prueba")
        self.assertContains(response, "Bogotá D.C.")
        self.assertContains(response, "$ 104.000")

    def test_shipping_quote(self):
        self.add_item(qty=2)  # 1000 g
        data = self.client.get("/checkout/envio", {"departamento": "Santander"}).json()
        self.assertEqual(data["shipping"], 15000)
        self.assertEqual(data["total"], 119000)
        data = self.client.get("/checkout/envio", {"departamento": "Bogotá D.C."}).json()
        self.assertEqual(data["shipping"], 8000)

    def test_creates_order_and_preference(self):
        order, response, post = self.create_order()
        self.assertRedirects(response, "https://mp.test/checkout?pref=1", fetch_redirect_response=False)
        self.assertEqual(order.status, Order.PENDIENTE)
        self.assertEqual(order.subtotal, 104000)
        self.assertEqual(order.shipping, 15000)
        self.assertEqual(order.total, 119000)
        self.assertEqual(order.document, "1098765432")
        self.assertEqual(order.mp_preference_id, "pref-1")
        self.assertEqual(order.items.get().qty, 2)

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["notification_url"], f"{SITE}/api/mercadopago/webhook")
        self.assertEqual(payload["back_urls"]["success"], f"{SITE}/pedido/{order.token}")
        self.assertEqual(payload["external_reference"], str(order.token))
        self.assertEqual(payload["auto_return"], "approved")
        self.assertEqual(payload["statement_descriptor"], "VIATICAFE")
        self.assertEqual(sum(i["unit_price"] * i["quantity"] for i in payload["items"]), order.total)
        self.assertTrue(all(i["currency_id"] == "COP" for i in payload["items"]))
        self.assertEqual(payload["payer"]["identification"], {"type": "CC", "number": "1098765432"})
        # El carrito se vacía al crear el pedido.
        self.assertEqual(self.client.get("/carrito/estado").json()["count"], 0)

    def test_invalid_form_keeps_cart(self):
        self.add_item()
        response = self.client.post("/checkout", {**CHECKOUT_DATA, "email": "malo", "department": "Texas"})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Email inválido", status_code=400)
        self.assertFalse(Order.objects.exists())

    @override_settings(MP_ACCESS_TOKEN="")
    def test_missing_token_shows_error(self):
        self.add_item()
        response = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "pagos en línea no están disponibles", status_code=400)
        self.assertFalse(Order.objects.exists())

    def test_mp_error_deletes_order(self):
        self.add_item()
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(500)):
            response = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.client.get("/carrito/estado").json()["count"], 2)


class WebhookTests(BaseCase):
    def payment(self, order, status="approved", amount=None, currency="COP", pid=999):
        return {
            "id": pid,
            "status": status,
            "status_detail": "accredited" if status == "approved" else "cc_rejected_other_reason",
            "transaction_amount": order.total if amount is None else amount,
            "currency_id": currency,
            "external_reference": str(order.token),
        }

    def notify(self, payment, **extra):
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, payment)) as get, \
                mock.patch("core.email.requests.post", return_value=fake_response(200, {"id": "e"})) as mail:
            response = self.post_json("/api/mercadopago/webhook", {"type": "payment", "data": {"id": str(payment["id"])}}, **extra)
        return response, get, mail

    def test_approved_marks_paid_and_sends_emails_once(self):
        order, _, _ = self.create_order()
        response, get, mail = self.notify(self.payment(order))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(get.call_args.args[0].endswith("/v1/payments/999"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)
        self.assertIsNotNone(order.paid_at)
        self.assertEqual(order.mp_payment_id, "999")
        self.assertTrue(order.emails_sent)
        self.assertEqual(mail.call_count, 2)  # gerencia + cliente
        recipients = [c.kwargs["json"]["to"] for c in mail.call_args_list]
        self.assertIn(["gerencia@example.com"], recipients)
        self.assertIn(["ana@example.com"], recipients)
        html = mail.call_args_list[0].kwargs["json"]["html"]
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<b>Pérez</b>", html)

        # Repetido: idempotente, sin correos nuevos.
        paid_at = order.paid_at
        response, _, mail = self.notify(self.payment(order))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.call_count, 0)
        order.refresh_from_db()
        self.assertEqual(order.paid_at, paid_at)

        # Un pago rechazado posterior no "despaga" el pedido.
        self.notify(self.payment(order, status="rejected", pid=1000))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)

    def test_amount_mismatch_not_paid(self):
        order, _, _ = self.create_order()
        response, _, mail = self.notify(self.payment(order, amount=1000))
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertNotEqual(order.status, Order.PAGADO)
        self.assertIn("NO coincide", order.payment_note)
        self.assertEqual(mail.call_count, 0)

    def test_currency_mismatch_not_paid(self):
        order, _, _ = self.create_order()
        self.notify(self.payment(order, currency="USD"))
        order.refresh_from_db()
        self.assertNotEqual(order.status, Order.PAGADO)

    def test_rejected_and_pending(self):
        order, _, _ = self.create_order()
        self.notify(self.payment(order, status="in_process"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.EN_PROCESO)
        self.notify(self.payment(order, status="rejected"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.RECHAZADO)

    def test_ipn_query_format(self):
        order, _, _ = self.create_order()
        payment = self.payment(order)
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, payment)) as get, \
                mock.patch("core.email.requests.post", return_value=fake_response(200)):
            response = self.client.post("/api/mercadopago/webhook?topic=payment&id=999", data=b"", content_type="text/plain")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(get.call_args.args[0].endswith("/v1/payments/999"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)

    def test_webhook_query_format_and_ignored_events(self):
        order, _, _ = self.create_order()
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, self.payment(order))), \
                mock.patch("core.email.requests.post", return_value=fake_response(200)):
            response = self.client.post("/api/mercadopago/webhook?type=payment&data.id=999", data="no-json", content_type="application/json")
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)

        with mock.patch("carrito.mercadopago.requests.get") as get:
            r1 = self.client.post("/api/mercadopago/webhook?topic=merchant_order&id=5")
            r2 = self.post_json("/api/mercadopago/webhook", {"type": "plan", "data": {"id": "1"}})
        self.assertEqual((r1.status_code, r2.status_code), (200, 200))
        get.assert_not_called()

    def test_unknown_payment_is_ignored(self):
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(404)):
            response = self.post_json("/api/mercadopago/webhook", {"type": "payment", "data": {"id": "123456"}})
        self.assertEqual(response.status_code, 200)

    def test_transient_error_returns_500(self):
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(503)):
            response = self.post_json("/api/mercadopago/webhook", {"type": "payment", "data": {"id": "1"}})
        self.assertEqual(response.status_code, 500)

    def test_email_failure_returns_500_and_retries(self):
        order, _, _ = self.create_order()
        payment = self.payment(order)
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, payment)), \
                mock.patch("core.email.requests.post", return_value=fake_response(500)):
            response = self.post_json("/api/mercadopago/webhook", {"type": "payment", "data": {"id": "999"}})
        self.assertEqual(response.status_code, 500)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)
        self.assertFalse(order.emails_sent)
        response, _, mail = self.notify(payment)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.call_count, 2)

    @override_settings(MP_WEBHOOK_SECRET="secreto")
    def test_signature(self):
        order, _, _ = self.create_order()
        payment = self.payment(order)
        # Firma inválida → 401 sin consultar MP.
        with mock.patch("carrito.mercadopago.requests.get") as get:
            bad = self.client.post(
                "/api/mercadopago/webhook?type=payment&data.id=999",
                json.dumps({"type": "payment", "data": {"id": "999"}}),
                content_type="application/json",
                HTTP_X_SIGNATURE="ts=1700000000,v1=deadbeef",
                HTTP_X_REQUEST_ID="req-1",
            )
            missing = self.post_json("/api/mercadopago/webhook", {"type": "payment", "data": {"id": "999"}})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(missing.status_code, 401)
        get.assert_not_called()

        # Firma válida → procesa.
        manifest = "id:999;request-id:req-1;ts:1700000000;"
        v1 = hmac.new(b"secreto", manifest.encode(), hashlib.sha256).hexdigest()
        response, _, _ = self.notify(
            payment, HTTP_X_SIGNATURE=f"ts=1700000000,v1={v1}", HTTP_X_REQUEST_ID="req-1"
        )
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)


class ReturnPageTests(BaseCase):
    def test_return_with_query_verifies_payment(self):
        order, _, _ = self.create_order()
        payment = {
            "id": 555, "status": "approved", "status_detail": "accredited",
            "transaction_amount": order.total, "currency_id": "COP", "external_reference": str(order.token),
        }
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, payment)), \
                mock.patch("core.email.requests.post", return_value=fake_response(200)) as mail:
            response = self.client.get(
                f"/pedido/{order.token}",
                {"payment_id": "555", "status": "approved", "external_reference": str(order.token)},
            )
        self.assertRedirects(response, f"/pedido/{order.token}", fetch_redirect_response=False)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)
        self.assertEqual(mail.call_count, 2)

        page = self.client.get(f"/pedido/{order.token}")
        self.assertContains(page, "¡Gracias por tu compra!")
        self.assertContains(page, "viati-purchase")
        state = self.client.get(f"/pedido/{order.token}/estado").json()
        self.assertEqual(state["status"], "pagado")

    def test_pending_page_and_retry(self):
        order, _, _ = self.create_order()
        page = self.client.get(f"/pedido/{order.token}")
        self.assertContains(page, "Estamos confirmando tu pago")
        self.assertContains(page, "Pagar ahora")

        Order.objects.filter(pk=order.pk).update(status=Order.RECHAZADO)
        page = self.client.get(f"/pedido/{order.token}")
        self.assertContains(page, "Reintentar pago")
        pref = fake_response(201, {"id": "pref-2", "init_point": "https://mp.test/checkout?pref=2"})
        with mock.patch("carrito.mercadopago.requests.post", return_value=pref):
            response = self.client.post(f"/pedido/{order.token}/reintentar")
        self.assertRedirects(response, "https://mp.test/checkout?pref=2", fetch_redirect_response=False)

        # Con el carrito vacío, /checkout lleva al pedido pendiente.
        response = self.client.get("/checkout")
        self.assertRedirects(response, f"/pedido/{order.token}", fetch_redirect_response=False)
