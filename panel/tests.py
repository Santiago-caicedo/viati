"""Pruebas del panel de gestión (/panel)."""

from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from carrito.models import Order, OrderItem, ShippingRate, StoreSettings
from tienda.models import Product, ProductSize

CLAVE = "Clave-Segura-2026!"
PAGINAS = ["/panel", "/panel/pedidos", "/panel/productos", "/panel/productos/nuevo", "/panel/envios", "/panel/cuenta"]


def crear_pedido(status=Order.PAGADO, **extra):
    datos = dict(full_name="Ana Pérez", email="ana@example.com", phone="300 123 4567", document="123456",
                 address="Calle 1 # 2-3", city="Bucaramanga", department="Santander", subtotal=50000, shipping=14000,
                 total=64000, status=status, paid_at=timezone.now() if status in Order.PAID_STATUSES else None)
    datos.update(extra)
    o = Order.objects.create(**datos)
    OrderItem.objects.create(order=o, product_name="El Paraíso", size="500g", grind="Molido", qty=1,
                             unit_price=50000, total=50000)
    return o


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.staff = User.objects.create_user("equipo", "e@example.com", CLAVE, is_staff=True)

    def entrar(self):
        self.client.force_login(self.staff)


class Acceso(Base):
    def test_paginas_piden_login(self):
        for url in PAGINAS:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 302)
                self.assertTrue(r["Location"].startswith("/panel/ingresar?next="))

    def test_login_correcto_y_redireccion_segura(self):
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE, "next": "/panel/pedidos"})
        self.assertRedirects(r, "/panel/pedidos", fetch_redirect_response=False)
        # Un "next" externo se ignora (evita redirecciones abiertas).
        self.client.logout()
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE, "next": "https://malo.example"})
        self.assertEqual(r["Location"], "/panel")
        self.client.logout()
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE, "next": "/admin/"})
        self.assertEqual(r["Location"], "/panel")

    def test_sesion_expira_al_cerrar_navegador_salvo_recordarme(self):
        self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE})
        self.assertTrue(self.client.session.get_expire_at_browser_close())
        self.client.logout()
        self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE, "recordarme": "on"})
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_clave_incorrecta(self):
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": "mala"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Usuario o contraseña incorrectos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_usuario_sin_staff_no_entra(self):
        User.objects.create_user("cliente", password=CLAVE)
        r = self.client.post("/panel/ingresar", {"username": "cliente", "password": CLAVE})
        self.assertContains(r, "no tiene acceso al panel")
        self.assertNotIn("_auth_user_id", self.client.session)
        # Aunque tenga sesión (p. ej. por otro medio), el panel lo rechaza.
        self.client.force_login(User.objects.get(username="cliente"))
        self.assertEqual(self.client.get("/panel").status_code, 302)

    def test_usuario_desactivado_no_entra(self):
        self.staff.is_active = False
        self.staff.save()
        self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bloqueo_tras_5_intentos(self):
        for _ in range(5):
            self.client.post("/panel/ingresar", {"username": "equipo", "password": "mala"})
        # Ni con la clave correcta entra mientras está bloqueado.
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE})
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Demasiados intentos", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bloqueo_por_ip_aunque_cambie_el_usuario(self):
        for i in range(5):
            self.client.post("/panel/ingresar", {"username": f"otro{i}", "password": "mala"})
        r = self.client.post("/panel/ingresar", {"username": "equipo", "password": CLAVE})
        self.assertEqual(r.status_code, 429)

    def test_cerrar_sesion_solo_por_post(self):
        self.entrar()
        self.assertEqual(self.client.get("/panel/salir").status_code, 405)
        r = self.client.post("/panel/salir")
        self.assertRedirects(r, "/panel/ingresar", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/panel").status_code, 302)

    def test_csrf_obligatorio(self):
        from django.test import Client

        c = Client(enforce_csrf_checks=True)
        r = c.post("/panel/ingresar", {"username": "equipo", "password": CLAVE})
        self.assertEqual(r.status_code, 403)

    def test_cabeceras_privadas(self):
        self.entrar()
        r = self.client.get("/panel")
        self.assertIn("no-store", r["Cache-Control"])
        self.assertEqual(r["X-Robots-Tag"], "noindex, nofollow")
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertIn("Disallow: /panel", self.client.get("/robots.txt").content.decode())

    def test_cambiar_clave_mantiene_la_sesion(self):
        self.entrar()
        r = self.client.post("/panel/cuenta", {"old_password": CLAVE, "new_password1": "Otra-Clave-Larga-99",
                                               "new_password2": "Otra-Clave-Larga-99"})
        self.assertRedirects(r, "/panel/cuenta", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/panel").status_code, 200)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password("Otra-Clave-Larga-99"))


class Paginas(Base):
    def test_todas_cargan_vacias(self):
        self.entrar()
        for url in PAGINAS:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_todas_cargan_con_datos(self):
        p = Product.objects.create(slug="cafe", name="Café", price=0, weight=0)
        ProductSize.objects.create(product=p, name="350g", price=38700, weight=350)
        o = crear_pedido()
        crear_pedido(status=Order.PENDIENTE)
        self.entrar()
        for url in PAGINAS + [f"/panel/pedidos/{o.pk}", f"/panel/productos/{p.pk}", "/panel?dias=7"]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class Pedidos(Base):
    def setUp(self):
        super().setUp()
        self.entrar()

    def test_busqueda_y_filtros(self):
        a = crear_pedido()
        crear_pedido(status=Order.PENDIENTE, full_name="Luis Gómez", email="luis@example.com", department="Antioquia")
        r = self.client.get("/panel/pedidos", {"q": a.number})
        self.assertEqual(list(r.context["pagina"]), [a])
        self.assertEqual(self.client.get("/panel/pedidos", {"q": "luis@"}).context["total"], 1)
        self.assertEqual(self.client.get("/panel/pedidos", {"estado": "pagado"}).context["total"], 1)
        self.assertEqual(self.client.get("/panel/pedidos", {"departamento": "Antioquia"}).context["total"], 1)
        self.assertEqual(self.client.get("/panel/pedidos", {"estado": "inventado"}).context["total"], 2)

    def test_marcar_enviado(self):
        o = crear_pedido()
        self.assertEqual(self.client.get(f"/panel/pedidos/{o.pk}/enviado").status_code, 405)
        self.client.post(f"/panel/pedidos/{o.pk}/enviado")
        o.refresh_from_db()
        self.assertEqual(o.status, Order.ENVIADO)
        self.assertIsNotNone(o.shipped_at)

    def test_no_marca_enviado_si_no_esta_pagado(self):
        o = crear_pedido(status=Order.PENDIENTE)
        self.client.post(f"/panel/pedidos/{o.pk}/enviado")
        o.refresh_from_db()
        self.assertEqual(o.status, Order.PENDIENTE)

    def test_reenviar_correos(self):
        o = crear_pedido()
        with mock.patch("panel.views.send_order_emails") as send:
            self.client.post(f"/panel/pedidos/{o.pk}/correos")
        send.assert_called_once()

    def test_verificar_pago(self):
        o = crear_pedido(status=Order.PENDIENTE)
        with mock.patch("panel.views.mp.refresh_order", return_value=o) as refresh:
            r = self.client.post(f"/panel/pedidos/{o.pk}/verificar", follow=True)
        refresh.assert_called_once()
        self.assertContains(r, "Mercado Pago dice")

    def test_exportar_csv(self):
        crear_pedido(notes="=HYPERLINK(\"http://malo\")")
        r = self.client.get("/panel/pedidos/exportar")
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        contenido = r.content.decode("utf-8-sig")
        self.assertIn("Ana Pérez", contenido)
        self.assertIn("'=HYPERLINK", contenido)  # neutralizado para Excel

    def test_whatsapp_del_cliente(self):
        o = crear_pedido()
        self.assertContains(self.client.get(f"/panel/pedidos/{o.pk}"), "https://wa.me/573001234567")


class Productos(Base):
    def setUp(self):
        super().setUp()
        self.entrar()

    def datos(self, **extra):
        d = {
            "name": "Nuevo Café", "slug": "nuevo-cafe", "category": "Café", "origin": "", "description": "Rico",
            "price": "45000", "weight": "350", "grind_options": ["Grano", "Molido"], "active": "on", "order": "0",
            "tamanos-TOTAL_FORMS": "1", "tamanos-INITIAL_FORMS": "0", "tamanos-MIN_NUM_FORMS": "0",
            "tamanos-MAX_NUM_FORMS": "1000",
            "tamanos-0-name": "", "tamanos-0-price": "", "tamanos-0-weight": "", "tamanos-0-order": "0",
        }
        d.update(extra)
        return d

    def test_crear_producto(self):
        r = self.client.post("/panel/productos/nuevo", self.datos())
        self.assertRedirects(r, "/panel/productos", fetch_redirect_response=False)
        p = Product.objects.get(slug="nuevo-cafe")
        self.assertEqual((p.price, p.grind_options, p.active), (45000, ["Grano", "Molido"], True))

    def test_crear_con_tamano(self):
        self.client.post("/panel/productos/nuevo", self.datos(**{
            "price": "0", "tamanos-0-name": "500g", "tamanos-0-price": "50000", "tamanos-0-weight": "500"}))
        p = Product.objects.get(slug="nuevo-cafe")
        self.assertEqual([(s.name, s.price) for s in p.sizes.all()], [("500g", 50000)])

    def test_no_permite_precio_cero_sin_tamanos(self):
        r = self.client.post("/panel/productos/nuevo", self.datos(price="0"))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Product.objects.filter(slug="nuevo-cafe").exists())
        self.assertContains(r, "Pon un precio mayor a 0")

    def test_tamano_con_precio_cero_se_rechaza(self):
        r = self.client.post("/panel/productos/nuevo", self.datos(**{
            "tamanos-0-name": "500g", "tamanos-0-price": "0", "tamanos-0-weight": "500"}))
        self.assertContains(r, "El precio debe ser mayor a 0")

    def test_slug_repetido(self):
        Product.objects.create(slug="nuevo-cafe", name="Otro", price=1000)
        r = self.client.post("/panel/productos/nuevo", self.datos())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Product.objects.filter(slug="nuevo-cafe").count(), 1)

    def test_editar_y_quitar_tamano(self):
        p = Product.objects.create(slug="cafe", name="Café", price=0)
        s = ProductSize.objects.create(product=p, name="350g", price=38700, weight=350)
        datos = self.datos(**{
            "name": "Café editado", "slug": "cafe", "price": "40000",
            "tamanos-TOTAL_FORMS": "2", "tamanos-INITIAL_FORMS": "1",
            "tamanos-0-id": str(s.pk), "tamanos-0-product": str(p.pk), "tamanos-0-name": "350g",
            "tamanos-0-price": "38700", "tamanos-0-weight": "350", "tamanos-0-order": "0", "tamanos-0-DELETE": "on",
            "tamanos-1-name": "", "tamanos-1-price": "", "tamanos-1-weight": "", "tamanos-1-order": "0",
        })
        r = self.client.post(f"/panel/productos/{p.pk}", datos)
        self.assertRedirects(r, "/panel/productos", fetch_redirect_response=False)
        p.refresh_from_db()
        self.assertEqual((p.name, p.price, p.sizes.count()), ("Café editado", 40000, 0))

    def test_ocultar_y_mostrar(self):
        p = Product.objects.create(slug="cafe", name="Café", price=1000)
        self.client.post(f"/panel/productos/{p.pk}/visible")
        p.refresh_from_db()
        self.assertFalse(p.active)
        self.assertEqual(self.client.get("/tienda/cafe").status_code, 404)
        self.client.post(f"/panel/productos/{p.pk}/visible")
        p.refresh_from_db()
        self.assertTrue(p.active)


class Envios(Base):
    def setUp(self):
        super().setUp()
        self.entrar()
        ShippingRate.objects.all().delete()  # la migración siembra tarifas de ejemplo
        self.tarifa = ShippingRate.objects.create(zona="nacional", min_g=0, max_g=1000, price=14000)

    def datos(self, **extra):
        d = {
            "config-free_shipping_from": "150000",
            "tarifas-TOTAL_FORMS": "2", "tarifas-INITIAL_FORMS": "1", "tarifas-MIN_NUM_FORMS": "0",
            "tarifas-MAX_NUM_FORMS": "1000",
            "tarifas-0-id": str(self.tarifa.pk), "tarifas-0-zona": "nacional", "tarifas-0-departamento": "",
            "tarifas-0-min_g": "0", "tarifas-0-max_g": "1000", "tarifas-0-price": "15000", "tarifas-0-active": "on",
            # Fila vacía para agregar: como en el navegador, "activa" viene marcada.
            "tarifas-1-zona": "nacional", "tarifas-1-departamento": "", "tarifas-1-min_g": "0",
            "tarifas-1-max_g": "", "tarifas-1-price": "", "tarifas-1-active": "on",
        }
        d.update(extra)
        return d

    def test_guardar_tarifas_y_envio_gratis(self):
        r = self.client.post("/panel/envios", self.datos(**{
            "tarifas-1-departamento": "Antioquia", "tarifas-1-min_g": "0", "tarifas-1-max_g": "2000",
            "tarifas-1-price": "16000", "tarifas-1-active": "on"}))
        self.assertRedirects(r, "/panel/envios", fetch_redirect_response=False)
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.price, 15000)
        self.assertTrue(ShippingRate.objects.filter(departamento="Antioquia", price=16000).exists())
        self.assertEqual(StoreSettings.load().free_shipping_from, 150000)

    def test_rango_invertido_se_rechaza(self):
        r = self.client.post("/panel/envios", self.datos(**{"tarifas-0-min_g": "2000"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "no puede ser mayor")
        self.tarifa.refresh_from_db()
        self.assertEqual(self.tarifa.price, 14000)

    def test_borrar_tarifa(self):
        r = self.client.post("/panel/envios", self.datos(**{"tarifas-0-DELETE": "on"}))
        self.assertRedirects(r, "/panel/envios", fetch_redirect_response=False)
        self.assertFalse(ShippingRate.objects.exists())

    def test_fila_vacia_no_crea_tarifa(self):
        r = self.client.post("/panel/envios", self.datos())
        self.assertRedirects(r, "/panel/envios", fetch_redirect_response=False)
        self.assertEqual(ShippingRate.objects.count(), 1)


@override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"))
class IpTrasProxy(Base):
    def test_usa_x_forwarded_for(self):
        from panel.seguridad import ip_cliente
        from django.test import RequestFactory

        req = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.5, 10.0.0.1", REMOTE_ADDR="10.0.0.1")
        self.assertEqual(ip_cliente(req), "203.0.113.5")
