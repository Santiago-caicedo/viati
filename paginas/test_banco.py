"""Banco de pruebas del sitio en general: páginas, catálogo real, SEO, redirecciones y formularios.

Carga el catálogo real (content/productos/*.md) con el comando cargar_productos.
Correr solo este banco:  python manage.py test paginas.test_banco -v 2
"""

import json
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.email import EmailError
from tienda.models import Product

SITE = "https://www.viaticafe.com"


@override_settings(SITE_URL=SITE, EMAIL_GERENCIA="gerencia@example.com")
class Sitio(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("cargar_productos", verbosity=0)

    def test_catalogo_real_se_carga_completo(self):
        self.assertEqual(Product.objects.filter(active=True).count(), 8)
        sin_precio = [p.slug for p in Product.objects.all() if p.base_price <= 0]
        self.assertEqual(sin_precio, [], "productos con precio 0")

    def test_paginas_publicas_responden_200(self):
        rutas = ["/", "/tienda", "/origenes", "/nosotros", "/institucional", "/contacto",
                 "/politicas/envios", "/politicas/devoluciones", "/politicas/faq",
                 "/sitemap.xml", "/robots.txt", "/manifest.webmanifest", "/carrito/estado"]
        rutas += [f"/tienda/{slug}" for slug in Product.objects.values_list("slug", flat=True)]
        rutas += [f"/origenes/{slug}" for slug in ("el-paraiso", "heroico", "oromiel")]
        for ruta in rutas:
            with self.subTest(ruta=ruta):
                self.assertEqual(self.client.get(ruta).status_code, 200)

    def test_cada_producto_se_puede_agregar_al_carrito(self):
        for p in Product.objects.filter(active=True):
            with self.subTest(slug=p.slug):
                r = self.client.post("/carrito/agregar", json.dumps({"slug": p.slug}), content_type="application/json")
                self.assertEqual(r.status_code, 200)
                self.assertGreater(r.json()["added"]["unit_price"], 0)

    def test_imagenes_de_productos_existen(self):
        from django.contrib.staticfiles import finders

        faltan = []
        for p in Product.objects.filter(active=True):
            if p.image and not finders.find(p.image.removeprefix("static/")):
                faltan.append(f"{p.slug}: {p.image}")
        self.assertEqual(faltan, [])

    def test_productos_relacionados_existen(self):
        """Los optionalProducts/accessoryProducts de los .md deben apuntar a slugs reales."""
        from core.content import content_path, read_markdown

        slugs = set(Product.objects.values_list("slug", flat=True))
        rotos = []
        for f in content_path("productos").glob("*.md"):
            data, _ = read_markdown(f)
            for rel in (data.get("optionalProducts") or []) + (data.get("accessoryProducts") or []):
                if rel not in slugs:
                    rotos.append(f"{f.stem} → {rel}")
        self.assertEqual(rotos, [])

    def test_404_personalizado(self):
        for ruta in ("/tienda/no-existe", "/origenes/no-existe", "/una-ruta-cualquiera"):
            with self.subTest(ruta=ruta):
                r = self.client.get(ruta)
                self.assertEqual(r.status_code, 404)
                self.assertTemplateUsed(r, "404.html")

    def test_producto_desactivado_da_404_y_sale_del_sitemap(self):
        Product.objects.filter(slug="heroico").update(active=False)
        self.assertEqual(self.client.get("/tienda/heroico").status_code, 404)
        self.assertNotIn("/tienda/heroico<", self.client.get("/sitemap.xml").content.decode())

    def test_sitemap_usa_el_dominio_y_lista_productos(self):
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertIn(f"<loc>{SITE}/tienda/oromiel</loc>", xml)
        self.assertIn(f"<loc>{SITE}/origenes/heroico</loc>", xml)
        self.assertNotIn("localhost", xml)

    def test_robots_apunta_al_sitemap(self):
        self.assertIn(f"{SITE}/sitemap.xml", self.client.get("/robots.txt").content.decode())

    def test_barra_final_redirige_301(self):
        r = self.client.get("/tienda/?utm_source=ig")
        self.assertEqual((r.status_code, r["Location"]), (301, "/tienda?utm_source=ig"))
        self.assertNotEqual(self.client.get("/admin/").status_code, 301)

    def test_redirecciones_de_wix(self):
        casos = {
            "/product-page/heroico": "/tienda/heroico",
            "/product-page/maletín-los-sabores-de-mi-tierra": "/tienda/maletin-sabores",
            "/category/all-products": "/tienda",
            "/contactanos": "/contacto",
            "/faq?x=1": "/politicas/faq?x=1",
        }
        for origen, destino in casos.items():
            with self.subTest(origen=origen):
                r = self.client.get(origen)
                self.assertEqual((r.status_code, r["Location"]), (301, destino))
                self.assertEqual(self.client.get(destino).status_code, 200)

    def test_cabeceras_de_seguridad(self):
        r = self.client.get("/")
        for h in ("X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "X-Frame-Options"):
            with self.subTest(h=h):
                self.assertIn(h, r.headers)

    def test_imagen_odoo_sin_configurar_no_revienta(self):
        self.assertIn(self.client.get("/api/odoo-image/1").status_code, (404, 503))


@override_settings(EMAIL_GERENCIA="gerencia@example.com")
class Formularios(TestCase):
    CONTACTO = {"nombre": "Ana", "apellido": "Pérez", "email": "ana@example.com",
                "celular": "3001234567", "mensaje": "Quiero comprar café al por mayor."}
    INSTITUCIONAL = {"name": "Ana", "company": "Hotel X", "email": "ana@example.com",
                     "message": "Cotización", "newsletter": True}

    def post(self, url, data):
        return self.client.post(url, json.dumps(data), content_type="application/json")

    def test_contacto_ok_envia_a_gerencia(self):
        with mock.patch("paginas.views.send_email") as send:
            r = self.post("/api/contact", self.CONTACTO)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(send.call_args.kwargs["to"], "gerencia@example.com")
        self.assertEqual(send.call_args.kwargs["reply_to"], "ana@example.com")

    def test_contacto_validaciones(self):
        malos = {"email": "x@", "nombre": "A", "celular": "12", "mensaje": "corto"}
        for campo, valor in malos.items():
            with self.subTest(campo=campo), mock.patch("paginas.views.send_email") as send:
                r = self.post("/api/contact", {**self.CONTACTO, campo: valor})
                self.assertEqual(r.status_code, 400)
                self.assertTrue(r.json()["error"])
                send.assert_not_called()

    def test_contacto_honeypot_no_envia(self):
        with mock.patch("paginas.views.send_email") as send:
            r = self.post("/api/contact", {**self.CONTACTO, "website": "http://spam"})
        self.assertEqual(r.status_code, 200)
        send.assert_not_called()

    def test_asunto_sin_saltos_de_linea_inyectados(self):
        with mock.patch("paginas.views.send_email") as send:
            self.post("/api/contact", {**self.CONTACTO, "nombre": "Ana\r\nBcc: x@y.com"})
        self.assertNotIn("\n", send.call_args.kwargs["subject"])

    def test_html_en_mensaje_se_escapa(self):
        with mock.patch("paginas.views.send_email") as send:
            self.post("/api/contact", {**self.CONTACTO, "mensaje": "<img src=x onerror=alert(1)> hola hola"})
        self.assertNotIn("<img src=x", send.call_args.kwargs["html"])

    def test_contacto_correo_caido_da_500(self):
        with mock.patch("paginas.views.send_email", side_effect=EmailError("caído")):
            self.assertEqual(self.post("/api/contact", self.CONTACTO).status_code, 500)

    def test_contacto_get_no_permitido(self):
        self.assertEqual(self.client.get("/api/contact").status_code, 405)

    def test_contacto_json_roto_no_da_error_interno(self):
        """Un cuerpo que no es JSON es un error del cliente (400), no del servidor (500)."""
        r = self.client.post("/api/contact", "{roto", content_type="application/json")
        self.assertLess(r.status_code, 500)

    def test_institucional_ok_y_newsletter_invalido(self):
        with mock.patch("paginas.views.send_email") as send:
            self.assertEqual(self.post("/api/institucional", self.INSTITUCIONAL).status_code, 200)
            self.assertEqual(self.post("/api/institucional", {**self.INSTITUCIONAL, "newsletter": "si"}).status_code, 400)
        self.assertEqual(send.call_count, 1)
