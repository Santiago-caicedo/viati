"""Banco de pruebas de escenarios: Mercado Pago, carrito, checkout, envíos y admin.

Complementa carrito/tests.py. No llama a APIs reales: Mercado Pago se simula con
mock sobre requests.get/post y los correos con mock sobre carrito.emails.send_email.
Cada prueba describe el comportamiento ESPERADO; si una falla, es un hallazgo.

Correr solo este banco:  python manage.py test carrito.test_banco -v 2
"""

import hashlib
import hmac
import json
import uuid
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import override_settings

from tienda.models import Product, ProductSize

from . import mercadopago as mp
from .emails import render_cliente, render_gerencia
from .models import Order, ShippingRate, StoreSettings
from .shipping import quote
from .tests import CHECKOUT_DATA, SITE, BaseCase, fake_response

PREF_OK = {"id": "pref-1", "init_point": "https://mp.test/checkout?pref=1"}


def pago(order, *, status="approved", pid=1001, amount=None, currency="COP", detail="accredited", ref=None):
    return {
        "id": pid,
        "status": status,
        "status_detail": detail,
        "transaction_amount": order.total if amount is None else amount,
        "currency_id": currency,
        "external_reference": str(order.token) if ref is None else ref,
    }


class Banco(BaseCase):
    """Base con helpers: crear pedidos, simular webhooks y contar correos."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch("carrito.emails.send_email")
        self.mail = patcher.start()
        self.addCleanup(patcher.stop)

    def nuevo_pedido(self, qty=2, size="500 g", data=None):
        self.add_item(qty=qty, size=size)
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, PREF_OK)) as post:
            response = self.client.post("/checkout", data or CHECKOUT_DATA)
        self.assertEqual(response.status_code, 302, "el checkout debía redirigir a Mercado Pago")
        order = Order.objects.order_by("-pk").first()
        return order, post

    def webhook(self, payment, *, status=200, **headers):
        pid = payment["id"] if payment else 1
        body = json.dumps({"type": "payment", "action": "payment.updated", "data": {"id": str(pid)}})
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(status, payment)) as get:
            response = self.client.post(
                f"/api/mercadopago/webhook?data.id={pid}&type=payment", body,
                content_type="application/json", **headers,
            )
        return response, get

    def correos(self):
        return [c.kwargs["to"] for c in self.mail.call_args_list]


# ─────────────────────────── Mercado Pago: estados del pago ───────────────────────────

class MPEstadosPago(Banco):
    def test_aprobado_marca_pagado_y_envia_2_correos(self):
        order, _ = self.nuevo_pedido()
        r, _ = self.webhook(pago(order))
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(order.status, Order.PAGADO)
        self.assertIsNotNone(order.paid_at)
        self.assertEqual(order.mp_payment_id, "1001")
        self.assertEqual(sorted(self.correos()), sorted(["gerencia@example.com", "ana@example.com"]))

    def test_webhook_repetido_no_duplica_correos(self):
        order, _ = self.nuevo_pedido()
        for _ in range(4):  # MP reintenta y manda payment.created + payment.updated
            self.webhook(pago(order))
        self.assertEqual(self.mail.call_count, 2)

    def test_pendiente_y_luego_aprobado(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, status="in_process", detail="pending_contingency"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.EN_PROCESO)
        self.assertEqual(self.mail.call_count, 0)
        self.webhook(pago(order))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)
        self.assertEqual(self.mail.call_count, 2)

    def test_rechazado_reintento_y_aprobado_con_otro_pago(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, status="rejected", detail="cc_rejected_insufficient_amount", pid=1))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.RECHAZADO)
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, PREF_OK)):
            r = self.client.post(f"/pedido/{order.token}/reintentar")
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("https://mp.test/"))
        self.webhook(pago(order, pid=2))
        order.refresh_from_db()
        self.assertEqual((order.status, order.mp_payment_id), (Order.PAGADO, "2"))

    def test_rechazo_viejo_que_llega_tarde_no_despaga(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, pid=2))
        self.webhook(pago(order, status="rejected", pid=1))
        order.refresh_from_db()
        self.assertEqual((order.status, order.mp_payment_id), (Order.PAGADO, "2"))

    def test_estados_autorizado_cancelado_y_en_mediacion(self):
        casos = {"authorized": Order.EN_PROCESO, "cancelled": Order.RECHAZADO, "in_mediation": Order.EN_PROCESO}
        for mp_status, esperado in casos.items():
            with self.subTest(mp_status=mp_status):
                order, _ = self.nuevo_pedido()
                self.webhook(pago(order, status=mp_status))
                order.refresh_from_db()
                self.assertEqual(order.status, esperado)

    def test_estado_desconocido_no_cambia_el_pedido(self):
        order, _ = self.nuevo_pedido()
        r, _ = self.webhook(pago(order, status="estado_nuevo_de_mp"))
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(order.status, Order.PENDIENTE)

    def test_reembolso_del_mismo_pago_cancela(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        self.webhook(pago(order, status="refunded", detail="refunded"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.CANCELADO)

    def test_contracargo_cancela_incluso_si_ya_se_envio(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        Order.objects.filter(pk=order.pk).update(status=Order.ENVIADO)
        self.webhook(pago(order, status="charged_back"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.CANCELADO)

    def test_reembolso_de_otro_pago_no_afecta_pedido_pagado(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, pid=2))
        self.webhook(pago(order, status="refunded", pid=1))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PAGADO)

    def test_pedido_enviado_no_vuelve_a_pagado(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        Order.objects.filter(pk=order.pk).update(status=Order.ENVIADO)
        self.webhook(pago(order))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.ENVIADO)


# ─────────────────────────── Mercado Pago: montos y referencias ───────────────────────────

class MPMontosYReferencias(Banco):
    def test_monto_menor_no_marca_pagado_y_deja_nota(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, amount=order.total - 1000))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.EN_PROCESO)
        self.assertIn("NO coincide", order.payment_note)
        self.assertEqual(self.mail.call_count, 0)

    def test_monto_mayor_tampoco_se_acepta(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, amount=order.total + 5000))
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

    def test_diferencia_de_1_peso_se_tolera(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, amount=order.total + 1))
        order.refresh_from_db()
        self.assertTrue(order.is_paid)

    def test_monto_decimal_o_texto(self):
        for amount in (None, "AS_STR", "AS_FLOAT"):
            with self.subTest(amount=amount):
                order, _ = self.nuevo_pedido()
                value = {None: order.total, "AS_STR": f"{order.total}.00", "AS_FLOAT": float(order.total)}[amount]
                self.webhook(pago(order, amount=value))
                order.refresh_from_db()
                self.assertTrue(order.is_paid)

    def test_monto_nulo_no_marca_pagado(self):
        order, _ = self.nuevo_pedido()
        payment = pago(order)
        payment["transaction_amount"] = None
        r, _ = self.webhook(payment)
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertFalse(order.is_paid)

    def test_moneda_distinta(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order, currency="USD"))
        order.refresh_from_db()
        self.assertFalse(order.is_paid)

    def test_pago_sin_external_reference_se_ignora(self):
        order, _ = self.nuevo_pedido()
        r, _ = self.webhook(pago(order, ref=""))
        self.assertEqual(r.json().get("ignored"), "pago sin pedido")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.PENDIENTE)

    def test_pago_de_pedido_inexistente_se_ignora(self):
        order, _ = self.nuevo_pedido()
        r, _ = self.webhook(pago(order, ref=str(uuid.uuid4())))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json().get("ignored"), "pago sin pedido")

    def test_pago_de_otro_pedido_no_toca_el_pedido_de_la_url(self):
        order_a, _ = self.nuevo_pedido()
        order_b, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, pago(order_b))):
            self.client.get(f"/pedido/{order_a.token}?payment_id=1001")
        order_a.refresh_from_db()
        order_b.refresh_from_db()
        self.assertEqual(order_a.status, Order.PENDIENTE)
        self.assertEqual(order_b.status, Order.PAGADO)


# ─────────────────────────── Mercado Pago: errores de red / API ───────────────────────────

class MPErroresAPI(Banco):
    def test_pago_inexistente_404_responde_200(self):
        r, _ = self.webhook({"id": 999}, status=404)
        self.assertEqual(r.status_code, 200)

    def test_errores_temporales_piden_reintento(self):
        for status in (429, 500, 502, 503):
            with self.subTest(status=status):
                r, _ = self.webhook({"id": 5}, status=status)
                self.assertEqual(r.status_code, 500)

    def test_timeout_de_red_pide_reintento(self):
        with mock.patch("carrito.mercadopago.requests.get", side_effect=requests.Timeout("lento")):
            r = self.client.post("/api/mercadopago/webhook?type=payment&data.id=5", "{}", content_type="application/json")
        self.assertEqual(r.status_code, 500)

    def test_token_invalido_o_vencido_pide_reintento(self):
        """Si el MP_ACCESS_TOKEN deja de servir (401/403), el webhook NO debe responder 200:
        con 200 Mercado Pago da la notificación por entregada y el pago se pierde."""
        order, _ = self.nuevo_pedido()
        for status in (401, 403):
            with self.subTest(status=status):
                r, _ = self.webhook(pago(order), status=status)
                self.assertGreaterEqual(r.status_code, 500)

    def test_sin_token_configurado_responde_500(self):
        with override_settings(MP_ACCESS_TOKEN=""):
            r = self.client.post("/api/mercadopago/webhook?type=payment&data.id=5", "{}", content_type="application/json")
        self.assertEqual(r.status_code, 500)

    def test_falla_correo_gerencia_pide_reintento_y_luego_envia_una_vez(self):
        order, _ = self.nuevo_pedido()
        self.mail.side_effect = [Exception("Resend caído"), None, None]
        r1, _ = self.webhook(pago(order))
        self.assertEqual(r1.status_code, 500)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertFalse(order.emails_sent)
        r2, _ = self.webhook(pago(order))
        self.assertEqual(r2.status_code, 200)
        r3, _ = self.webhook(pago(order))
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(self.mail.call_count, 3)  # 1 fallido + gerencia + cliente

    def test_falla_solo_correo_cliente_no_bloquea(self):
        from core.email import EmailError

        order, _ = self.nuevo_pedido()
        self.mail.side_effect = [None, EmailError("buzón inválido")]
        r, _ = self.webhook(pago(order))
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(order.emails_sent)

    def test_preferencia_rechazada_borra_pedido_y_conserva_carrito(self):
        self.add_item()
        for status in (400, 401, 500):
            with self.subTest(status=status), \
                    mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(status, {"message": "x"})):
                r = self.client.post("/checkout", CHECKOUT_DATA)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(Order.objects.count(), 0)
                self.assertEqual(self.client.get("/carrito/estado").json()["count"], 2)

    def test_preferencia_timeout(self):
        self.add_item()
        with mock.patch("carrito.mercadopago.requests.post", side_effect=requests.ConnectionError("sin red")):
            r = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)

    def test_preferencia_sin_init_point(self):
        self.add_item()
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, {"id": "p"})):
            r = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)


# ─────────────────────────── Mercado Pago: formato y firma del webhook ───────────────────────────

SECRET = "secreto-de-prueba"


def firma(data_id, request_id="req-1", ts="1700000000"):
    manifest = f"id:{data_id.lower()};request-id:{request_id};ts:{ts};"
    v1 = hmac.new(SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"HTTP_X_SIGNATURE": f"ts={ts},v1={v1}", "HTTP_X_REQUEST_ID": request_id}


class MPWebhookFormato(Banco):
    def test_get_responde_ok(self):
        self.assertEqual(self.client.get("/api/mercadopago/webhook").status_code, 200)

    def test_cuerpo_malformado_no_rompe(self):
        for body in ("no es json", "[]", "null", '{"data": "x"}'):
            with self.subTest(body=body):
                r = self.client.post("/api/mercadopago/webhook", body, content_type="application/json")
                self.assertEqual(r.status_code, 200)

    def test_eventos_que_no_son_pagos_se_ignoran(self):
        for kind in ("merchant_order", "plan", "subscription_preapproval", "point_integration_wh"):
            with self.subTest(kind=kind), mock.patch("carrito.mercadopago.requests.get") as get:
                r = self.client.post(f"/api/mercadopago/webhook?type={kind}&data.id=1", "{}", content_type="application/json")
                self.assertEqual(r.status_code, 200)
                get.assert_not_called()

    def test_solo_action_sin_type(self):
        order, _ = self.nuevo_pedido()
        body = json.dumps({"action": "payment.created", "data": {"id": 1001}})
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, pago(order))):
            r = self.client.post("/api/mercadopago/webhook", body, content_type="application/json")
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(order.is_paid)

    def test_ipn_clasico(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, pago(order))):
            r = self.client.post("/api/mercadopago/webhook?topic=payment&id=1001")
        order.refresh_from_db()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(order.is_paid)

    @override_settings(MP_WEBHOOK_SECRET=SECRET)
    def test_firma_valida_se_procesa(self):
        order, _ = self.nuevo_pedido()
        r, _ = self.webhook(pago(order), **firma("1001"))
        self.assertEqual(r.status_code, 200)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)

    @override_settings(MP_WEBHOOK_SECRET=SECRET)
    def test_firma_invalida_o_ausente_401_sin_consultar_mp(self):
        order, _ = self.nuevo_pedido()
        casos = {
            "sin firma": {},
            "firma alterada": {"HTTP_X_SIGNATURE": "ts=1700000000,v1=" + "0" * 64, "HTTP_X_REQUEST_ID": "req-1"},
            "firma de otro pago": firma("2002"),
            "cabecera rota": {"HTTP_X_SIGNATURE": "basura"},
        }
        for nombre, headers in casos.items():
            with self.subTest(nombre):
                r, get = self.webhook(pago(order), **headers)
                self.assertEqual(r.status_code, 401)
                get.assert_not_called()

    @override_settings(MP_WEBHOOK_SECRET=SECRET)
    def test_ipn_sin_firma_se_acepta_con_secreto(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, pago(order))):
            r = self.client.post("/api/mercadopago/webhook?topic=payment&id=1001")
        self.assertEqual(r.status_code, 200)

    def test_firma_con_id_alfanumerico_en_mayusculas(self):
        headers = firma("ABC123")
        self.assertTrue(mp.verify_signature(
            x_signature=headers["HTTP_X_SIGNATURE"], x_request_id="req-1", data_id="ABC123", secret=SECRET))


# ─────────────────────────── Página del pedido y reintentos ───────────────────────────

class RetornoYPedido(Banco):
    def test_cliente_cancela_en_mp_vuelve_con_null(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get") as get:
            r = self.client.get(f"/pedido/{order.token}?collection_id=null&collection_status=null&payment_id=null&status=null")
        get.assert_not_called()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], f"/pedido/{order.token}")

    def test_retorno_con_collection_id(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, pago(order))):
            self.client.get(f"/pedido/{order.token}?collection_id=1001&collection_status=approved")
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(self.mail.call_count, 2)

    def test_retorno_con_mp_caido_no_rompe_la_pagina(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.get", side_effect=requests.ConnectionError()):
            r = self.client.get(f"/pedido/{order.token}?payment_id=1001", follow=True)
        self.assertEqual(r.status_code, 200)

    def test_paginas_de_pedido_inexistente(self):
        self.assertEqual(self.client.get(f"/pedido/{uuid.uuid4()}").status_code, 404)
        self.assertEqual(self.client.get("/pedido/no-es-un-uuid").status_code, 404)
        self.assertEqual(self.client.get(f"/pedido/{uuid.uuid4()}/estado").status_code, 404)

    def test_pagina_muestra_estado_y_productos(self):
        order, _ = self.nuevo_pedido()
        html = self.client.get(f"/pedido/{order.token}").content.decode()
        self.assertIn(order.number, html)
        self.assertIn("Café Prueba", html)

    def test_polling_limitado_a_una_consulta_cada_8s(self):
        order, _ = self.nuevo_pedido()
        search = fake_response(200, {"results": []})
        with mock.patch("carrito.mercadopago.requests.get", return_value=search) as get:
            for _ in range(5):
                r = self.client.get(f"/pedido/{order.token}/estado")
        self.assertEqual(r.json()["status"], Order.PENDIENTE)
        self.assertEqual(get.call_count, 1)

    def test_polling_encuentra_el_aprobado_entre_varios(self):
        order, _ = self.nuevo_pedido()
        results = {"results": [pago(order, status="rejected", pid=1), pago(order, pid=2)]}
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, results)):
            data = self.client.get(f"/pedido/{order.token}/estado").json()
        self.assertTrue(data["paid"])

    def test_reintentar_pedido_pagado_no_crea_preferencia(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        with mock.patch("carrito.mercadopago.requests.post") as post:
            r = self.client.post(f"/pedido/{order.token}/reintentar")
        post.assert_not_called()
        self.assertEqual(r["Location"], f"/pedido/{order.token}")

    def test_reintentar_por_get_no_se_permite(self):
        order, _ = self.nuevo_pedido()
        self.assertEqual(self.client.get(f"/pedido/{order.token}/reintentar").status_code, 405)

    def test_reintentar_con_mp_caido_muestra_error(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(503)):
            r = self.client.post(f"/pedido/{order.token}/reintentar")
        self.assertEqual(r.status_code, 400)
        self.assertIn("No pudimos conectar", r.content.decode())


# ─────────────────────────── Checkout ───────────────────────────

class Checkout(Banco):
    def test_preferencia_cuadra_con_el_total(self):
        order, post = self.nuevo_pedido(qty=3)
        payload = post.call_args.kwargs["json"]
        suma = sum(i["unit_price"] * i["quantity"] for i in payload["items"])
        self.assertEqual(suma, order.total)
        self.assertEqual(order.total, order.subtotal + order.shipping)
        self.assertEqual(payload["external_reference"], str(order.token))
        self.assertTrue(all(i["currency_id"] == "COP" for i in payload["items"]))

    def test_preferencia_en_https_lleva_auto_return_y_webhook(self):
        _, post = self.nuevo_pedido()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["auto_return"], "approved")
        self.assertEqual(payload["notification_url"], f"{SITE}/api/mercadopago/webhook")
        self.assertTrue(payload["back_urls"]["success"].startswith(SITE + "/pedido/"))

    @override_settings(SITE_URL="http://localhost:8000")
    def test_preferencia_en_localhost_sin_auto_return(self):
        _, post = self.nuevo_pedido()
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("auto_return", payload)
        self.assertNotIn("notification_url", payload)

    def test_doble_envio_del_formulario_crea_un_solo_pedido(self):
        order, _ = self.nuevo_pedido()
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, PREF_OK)) as post:
            r = self.client.post("/checkout", CHECKOUT_DATA)
        post.assert_not_called()
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(r["Location"], order.get_absolute_url())

    def test_volver_atras_desde_mp_lleva_al_pedido_pendiente(self):
        order, _ = self.nuevo_pedido()
        r = self.client.get("/checkout")
        self.assertEqual(r["Location"], order.get_absolute_url())

    def test_carrito_vacio_tras_pago_va_a_tienda(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        self.assertEqual(self.client.get("/checkout")["Location"], "/tienda")

    def test_cambio_de_precio_antes_de_pagar_usa_precio_nuevo(self):
        self.add_item(qty=1)
        ProductSize.objects.filter(name="500 g").update(price=60000)
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, PREF_OK)):
            self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(Order.objects.get().subtotal, 60000)

    def test_producto_desactivado_antes_de_pagar(self):
        self.add_item(qty=1)
        Product.objects.filter(slug="cafe-prueba").update(active=False)
        r = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(r["Location"], "/tienda")
        self.assertEqual(Order.objects.count(), 0)

    def test_validaciones_del_formulario(self):
        self.add_item()
        malos = {
            "email inválido": {"email": "ana@"},
            "celular corto": {"phone": "123"},
            "celular con letras": {"phone": "abcdefgh"},
            "documento con símbolos": {"document": "12$45#78"},
            "documento corto": {"document": "123"},
            "departamento inventado": {"department": "Narnia"},
            "nombre de 2 letras": {"full_name": "Al"},
            "dirección corta": {"address": "Cl 1"},
            "ciudad vacía": {"city": ""},
            "tipo de documento inválido": {"document_type": "PASAPORTE"},
        }
        for nombre, cambio in malos.items():
            with self.subTest(nombre), mock.patch("carrito.mercadopago.requests.post") as post:
                r = self.client.post("/checkout", {**CHECKOUT_DATA, **cambio})
                self.assertEqual(r.status_code, 400)
                post.assert_not_called()
        self.assertEqual(Order.objects.count(), 0)

    def test_datos_se_normalizan(self):
        order, _ = self.nuevo_pedido(data={**CHECKOUT_DATA, "full_name": "  Ana   María  ", "document": "1.098 765.432"})
        self.assertEqual(order.full_name, "Ana María")
        self.assertEqual(order.document, "1098765432")

    def test_nombre_de_una_sola_palabra(self):
        _, post = self.nuevo_pedido(data={**CHECKOUT_DATA, "full_name": "Madonna"})
        payer = post.call_args.kwargs["json"]["payer"]
        self.assertEqual(payer["name"], "Madonna")

    def test_html_del_cliente_se_escapa_en_correos(self):
        order, _ = self.nuevo_pedido()
        for html in (render_gerencia(order), render_cliente(order)):
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("<b>Pérez</b>", html)

    def test_producto_con_precio_cero_no_se_puede_comprar(self):
        """Un producto mal cargado (precio 0) no debe llegar a Mercado Pago: MP exige unit_price > 0."""
        Product.objects.create(slug="gratis", name="Sin precio", price=0, weight=100)
        self.post_json("/carrito/agregar", {"slug": "gratis", "qty": 1})
        with mock.patch("carrito.mercadopago.requests.post", return_value=fake_response(201, PREF_OK)) as post:
            self.client.post("/checkout", CHECKOUT_DATA)
        if post.called:
            precios = [i["unit_price"] for i in post.call_args.kwargs["json"]["items"]]
            self.assertNotIn(0, precios, "se envió a Mercado Pago un ítem con precio 0")

    def test_sin_mp_configurado_no_crea_pedido(self):
        self.add_item()
        with override_settings(MP_ACCESS_TOKEN=""):
            r = self.client.post("/checkout", CHECKOUT_DATA)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(Order.objects.count(), 0)


# ─────────────────────────── Carrito ───────────────────────────

class Carrito(Banco):
    def estado(self):
        return self.client.get("/carrito/estado").json()

    def test_cantidades_invalidas(self):
        for qty in (0, -1, 100, "abc", "1.5", None, [], {"a": 1}):
            with self.subTest(qty=qty):
                r = self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "qty": qty})
                if qty is None:  # sin cantidad → 1 por defecto
                    self.assertEqual(r.status_code, 200)
                else:
                    self.assertEqual(r.status_code, 400)

    def test_acumular_mas_de_99_queda_en_99(self):
        for _ in range(3):
            self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "size": "250 g", "qty": 50})
        self.assertEqual(self.estado()["count"], 99)

    def test_mismo_cafe_distinta_molienda_son_2_lineas(self):
        self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "grind": "Grano"})
        self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "grind": "Molido"})
        self.assertEqual(len(self.estado()["items"]), 2)

    def test_tamano_o_molienda_inventados_usan_los_validos(self):
        data = self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "size": "1 tonelada", "grind": "Polvo"}).json()
        item = data["items"][0]
        self.assertEqual(item["size"], "250 g")
        self.assertEqual(item["grind"], "Grano")
        self.assertEqual(item["unit_price"], 30000)

    def test_precio_enviado_por_el_navegador_se_ignora(self):
        data = self.post_json("/carrito/agregar", {"slug": "cafe-prueba", "size": "500 g", "price": 1, "unit_price": 1}).json()
        self.assertEqual(data["subtotal"], 52000)

    def test_producto_sin_tamanos_usa_su_precio(self):
        Product.objects.create(slug="cuchara", name="Cuchara", price=30000, weight=50)
        data = self.post_json("/carrito/agregar", {"slug": "cuchara"}).json()
        self.assertEqual((data["subtotal"], data["items"][0]["grind"]), (30000, ""))

    def test_productos_inexistentes_o_inactivos(self):
        Product.objects.create(slug="viejo", name="Viejo", price=1000, active=False)
        for slug in ("no-existe", "viejo", "", "../admin"):
            with self.subTest(slug=slug):
                self.assertEqual(self.post_json("/carrito/agregar", {"slug": slug}).status_code, 404)

    def test_producto_desactivado_desaparece_del_carrito(self):
        self.add_item()
        Product.objects.filter(slug="cafe-prueba").update(active=False)
        self.assertEqual(self.estado()["count"], 0)

    def test_producto_borrado_desaparece_del_carrito(self):
        self.add_item()
        Product.objects.filter(slug="cafe-prueba").delete()
        self.assertEqual(self.estado()["count"], 0)

    def test_actualizar_y_eliminar(self):
        key = self.add_item().json()["items"][0]["key"]
        self.assertEqual(self.post_json("/carrito/actualizar", {"key": key, "qty": 100}).status_code, 400)
        self.assertEqual(self.post_json("/carrito/actualizar", {"key": key, "qty": "x"}).status_code, 400)
        self.assertEqual(self.post_json("/carrito/actualizar", {"key": "nada", "qty": 1}).status_code, 404)
        self.assertEqual(self.post_json("/carrito/actualizar", {"key": key, "qty": -3}).json()["count"], 0)
        self.assertEqual(self.post_json("/carrito/eliminar", {"key": "nada"}).status_code, 200)

    def test_json_malformado_y_formulario_clasico(self):
        r = self.client.post("/carrito/agregar", "{roto", content_type="application/json")
        self.assertEqual(r.status_code, 404)
        r = self.client.post("/carrito/agregar", {"slug": "cafe-prueba", "qty": "2"})
        self.assertEqual(r.json()["count"], 2)

    def test_metodos_no_permitidos(self):
        self.assertEqual(self.client.get("/carrito/agregar").status_code, 405)
        self.assertEqual(self.client.post("/carrito/estado").status_code, 405)

    def test_carritos_de_dos_clientes_no_se_mezclan(self):
        self.add_item(qty=3)
        otro = self.client_class()
        self.assertEqual(otro.get("/carrito/estado").json()["count"], 0)


# ─────────────────────────── Envíos ───────────────────────────

class Envios(Banco):
    def q(self, peso, depto="Santander", subtotal=10000):
        return quote(weight_g=peso, departamento=depto, subtotal=subtotal)

    def test_rangos_de_peso(self):
        casos = {0: 15000, 1000: 15000, 1001: 20000, 5000: 20000, 20000: 20000}
        for peso, precio in casos.items():
            with self.subTest(peso=peso):
                self.assertEqual(self.q(peso).price, precio)

    def test_bogota_es_zona_local(self):
        self.assertEqual(self.q(500, "Bogotá D.C.").price, 8000)

    def test_tarifa_de_departamento_tiene_prioridad(self):
        ShippingRate.objects.create(zona="nacional", departamento="San Andrés y Providencia", min_g=0, max_g=5000, price=45000)
        self.assertEqual(self.q(500, "San Andrés y Providencia").price, 45000)
        self.assertEqual(self.q(500, "Santander").price, 15000)

    def test_tarifa_inactiva_se_ignora(self):
        ShippingRate.objects.filter(zona="local").update(active=False)
        self.assertEqual(self.q(500, "Bogotá D.C.").available, False)

    def test_envio_gratis_desde_el_umbral(self):
        StoreSettings.objects.update_or_create(pk=1, defaults={"free_shipping_from": 100000})
        self.assertTrue(self.q(500, subtotal=100000).free)
        self.assertFalse(self.q(500, subtotal=99999).free)

    def test_envio_gratis_en_checkout(self):
        StoreSettings.objects.update_or_create(pk=1, defaults={"free_shipping_from": 100000})
        order, post = self.nuevo_pedido(qty=2)  # 104.000
        self.assertEqual((order.shipping, order.total), (0, 104000))
        self.assertNotIn("envio", [i["id"] for i in post.call_args.kwargs["json"]["items"]])

    def test_cotizador_del_checkout(self):
        self.add_item(qty=1)
        ok = self.client.get("/checkout/envio?departamento=Santander").json()
        self.assertEqual((ok["shipping"], ok["total"], ok["shipping_known"]), (15000, 67000, True))
        malo = self.client.get("/checkout/envio?departamento=Narnia").json()
        self.assertFalse(malo["shipping_known"])

    def test_todos_los_departamentos_tienen_tarifa_en_la_migracion(self):
        """Con las tarifas de la migración (sin las de esta prueba) ningún departamento debe quedar en $0."""
        from .shipping import DEPARTAMENTOS

        from importlib import import_module

        from django.apps import apps as global_apps

        ShippingRate.objects.all().delete()
        import_module("carrito.migrations.0002_tarifas_envio_placeholder").sembrar(global_apps, None)
        sin_tarifa = [d for d in DEPARTAMENTOS if not self.q(500, d).available]
        self.assertEqual(sin_tarifa, [])


# ─────────────────────────── Admin ───────────────────────────

class Admin(Banco):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("admin", "a@example.com", "x")

    def accion(self, action, orders):
        self.client.force_login(self.admin)
        return self.client.post("/admin/carrito/order/", {
            "action": action, "_selected_action": [o.pk for o in orders],
        }, follow=True)

    def test_admin_exige_login(self):
        r = self.client_class().get("/admin/carrito/order/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login", r["Location"])

    def test_listados_del_admin_cargan(self):
        order, _ = self.nuevo_pedido()
        self.client.force_login(self.admin)
        for url in ("/admin/", "/admin/carrito/order/", f"/admin/carrito/order/{order.pk}/change/",
                    "/admin/carrito/shippingrate/", "/admin/tienda/product/", "/admin/carrito/storesettings/"):
            with self.subTest(url=url):
                self.assertIn(self.client.get(url, follow=True).status_code, (200,))

    def test_marcar_enviado_solo_pedidos_pagados(self):
        pagado, _ = self.nuevo_pedido()
        self.webhook(pago(pagado))
        pendiente, _ = self.nuevo_pedido()
        self.accion("marcar_enviado", [pagado, pendiente])
        pagado.refresh_from_db()
        pendiente.refresh_from_db()
        self.assertEqual((pagado.status, pendiente.status), (Order.ENVIADO, Order.PENDIENTE))
        self.assertIsNotNone(pagado.shipped_at)

    def test_reenviar_correos(self):
        order, _ = self.nuevo_pedido()
        self.webhook(pago(order))
        self.mail.reset_mock()
        self.accion("reenviar_correos", [order])
        self.assertEqual(self.mail.call_count, 2)

    def test_verificar_pago_desde_admin(self):
        order, _ = self.nuevo_pedido()
        results = {"results": [pago(order)]}
        with mock.patch("carrito.mercadopago.requests.get", return_value=fake_response(200, results)):
            self.accion("verificar_pago", [order])
        order.refresh_from_db()
        self.assertTrue(order.is_paid)
        self.assertEqual(self.mail.call_count, 2)
