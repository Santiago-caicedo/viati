"""Pruebas del panel de estadísticas (/admin/estadisticas/)."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Order, OrderItem

URL = "/admin/estadisticas/"


def pedido(status=Order.PAGADO, total=50000, dias_pago=0, horas_creado=None, email="a@example.com",
           ciudad="Bucaramanga", depto="Santander", items=(("El Paraíso", "500g", "Molido", 1, 50000),)):
    ahora = timezone.now()
    if horas_creado is None:
        horas_creado = dias_pago * 24 + 3  # creado poco antes de pagarse
    o = Order.objects.create(
        full_name="Cliente Prueba", email=email, phone="3001234567", document="123456", address="Calle 1 # 2-3",
        city=ciudad, department=depto, subtotal=total - 9000, shipping=9000, total=total, status=status,
        paid_at=ahora - timedelta(days=dias_pago) if status in Order.PAID_STATUSES else None,
    )
    Order.objects.filter(pk=o.pk).update(created_at=ahora - timedelta(hours=horas_creado))
    for nombre, size, grind, qty, item_total in items:
        OrderItem.objects.create(order=o, product_name=nombre, size=size, grind=grind, qty=qty,
                                 unit_price=item_total // qty, total=item_total)
    return o


class Acceso(TestCase):
    def test_sin_sesion_redirige_al_login(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    def test_usuario_no_staff_no_entra(self):
        User.objects.create_user("cliente", password="x-123-prueba")
        self.client.login(username="cliente", password="x-123-prueba")
        self.assertEqual(self.client.get(URL).status_code, 302)


class Panel(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "x-123-prueba")
        self.client.force_login(self.admin)

    def test_vacio_no_falla(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Todavía no hay ventas pagadas")
        self.assertContains(r, "No hay pedidos pagados pendientes de envío")

    def test_cifras(self):
        pedido(total=100000, items=(("El Paraíso", "500g", "Molido", 2, 91000),))
        pedido(status=Order.ENVIADO, total=60000, dias_pago=3, email="b@example.com", ciudad="Bogotá", depto="Bogotá D.C.",
               items=(("Heroico", "350g", "Grano", 1, 51000),))
        pedido(status=Order.PAGADO, total=40000, dias_pago=40, email="a@example.com")  # fuera de 30 días
        pedido(status=Order.PENDIENTE, total=70000)                                    # abandonado
        pedido(status=Order.PENDIENTE, total=80000, horas_creado=0)                    # recién creado: aún no
        pedido(status=Order.RECHAZADO, total=30000)

        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        ctx = r.context
        hoy, siete, mes, total = ctx["kpis"]
        self.assertEqual((hoy["ingresos"], hoy["pedidos"]), (100000, 1))
        self.assertEqual((siete["ingresos"], siete["pedidos"]), (160000, 2))
        self.assertEqual((total["ingresos"], total["pedidos"], total["ticket"]), (200000, 3, 66667))
        self.assertEqual(ctx["periodo"]["ingresos"], 160000)
        self.assertEqual(ctx["abandonados_n"], 2)          # pendiente viejo + rechazado
        self.assertEqual(ctx["abandonados_valor"], 100000)
        self.assertEqual(ctx["rechazados_n"], 1)
        self.assertEqual(ctx["por_enviar_total"], 2)       # los PAGADO (no el ENVIADO)
        self.assertEqual(ctx["top_productos"][0]["product_name"], "El Paraíso")
        self.assertEqual(ctx["top_productos"][0]["unidades"], 2)
        self.assertEqual({d["department"] for d in ctx["por_departamento"]}, {"Santander", "Bogotá D.C."})
        self.assertEqual((ctx["total_clientes"], ctx["recurrentes"]), (2, 1))
        self.assertEqual(ctx["conversion"], 40)            # 2 de 5 creados en 30 días
        self.assertEqual(sum(d["ingresos"] for d in ctx["serie"]), 160000)
        self.assertEqual(len(ctx["serie"]), 30)
        self.assertContains(r, "$ 160.000")

    def test_filtro_de_periodo(self):
        pedido(total=40000, dias_pago=40)
        r = self.client.get(URL + "?dias=90")
        self.assertEqual(r.context["periodo"]["ingresos"], 40000)
        self.assertEqual(len(r.context["serie"]), 90)
        self.assertEqual(self.client.get(URL + "?dias=abc").context["dias"], 30)
        self.assertEqual(self.client.get(URL + "?dias=999").context["dias"], 30)

    def test_aviso_pago_por_revisar(self):
        o = pedido(status=Order.EN_PROCESO)
        Order.objects.filter(pk=o.pk).update(payment_note="monto no coincide")
        self.assertEqual(self.client.get(URL).context["revisar_n"], 1)

    def test_enlace_en_el_admin(self):
        r = self.client.get("/admin/")
        self.assertContains(r, URL)
