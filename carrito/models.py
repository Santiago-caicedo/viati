"""Modelos de la app carrito: tarifas de envío, configuración de la tienda y pedidos.

Reemplazan lo que antes vivía en Snipcart (tarifas de envío en su dashboard y
órdenes en su backoffice). El pago se procesa con Mercado Pago Checkout Pro.
"""

import uuid

from django.db import models
from django.utils import timezone

from .shipping import DEPARTAMENTOS, ZONA_LOCAL_DEPARTAMENTOS

DEPARTAMENTO_CHOICES = [(d, d) for d in DEPARTAMENTOS]


class ShippingRate(models.Model):
    """Tarifa de envío nacional por rango de peso.

    Prioridad al cotizar: 1) tarifa con el mismo departamento del pedido;
    2) tarifa de la zona (local = Bogotá D.C., nacional = resto del país).
    """

    ZONA_LOCAL = "local"
    ZONA_NACIONAL = "nacional"
    ZONA_CHOICES = [
        (ZONA_LOCAL, "Local (Bogotá D.C.)"),
        (ZONA_NACIONAL, "Nacional (resto de Colombia)"),
    ]

    zona = models.CharField("zona", max_length=20, choices=ZONA_CHOICES, default=ZONA_NACIONAL)
    departamento = models.CharField(
        "departamento (opcional)",
        max_length=60,
        blank=True,
        choices=DEPARTAMENTO_CHOICES,
        help_text="Si se elige, esta tarifa reemplaza a la de la zona para ese departamento.",
    )
    min_g = models.PositiveIntegerField("peso mínimo (g)", default=0)
    max_g = models.PositiveIntegerField("peso máximo (g)", help_text="Incluido. Ej: 0 – 1000 g.")
    price = models.PositiveIntegerField(
        "precio (COP)",
        help_text=(
            "⚠️ VALOR DE REFERENCIA (PLACEHOLDER): las tarifas reales estaban en el panel de "
            "Snipcart y no se conocen. Ajústalas con la tarifa real de la transportadora."
        ),
    )
    active = models.BooleanField("activa", default=True)

    class Meta:
        ordering = ["zona", "departamento", "min_g"]
        verbose_name = "tarifa de envío"
        verbose_name_plural = "tarifas de envío"

    def __str__(self) -> str:
        donde = self.departamento or self.get_zona_display()
        return f"{donde}: {self.min_g}–{self.max_g} g → $ {self.price:,}".replace(",", ".")

    @staticmethod
    def zona_para(departamento: str) -> str:
        return ShippingRate.ZONA_LOCAL if departamento in ZONA_LOCAL_DEPARTAMENTOS else ShippingRate.ZONA_NACIONAL


class StoreSettings(models.Model):
    """Configuración única de la tienda (singleton, se edita desde el admin)."""

    free_shipping_from = models.PositiveIntegerField(
        "envío gratis desde (COP)",
        default=0,
        help_text="Subtotal a partir del cual el envío es gratis. 0 = desactivado.",
    )

    class Meta:
        verbose_name = "configuración de la tienda"
        verbose_name_plural = "configuración de la tienda"

    def __str__(self) -> str:
        return "Configuración de la tienda"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "StoreSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Order(models.Model):
    """Pedido creado en el checkout. Los montos quedan congelados al crearlo."""

    PENDIENTE = "pendiente"
    EN_PROCESO = "en_proceso"
    PAGADO = "pagado"
    RECHAZADO = "rechazado"
    CANCELADO = "cancelado"
    ENVIADO = "enviado"
    STATUS_CHOICES = [
        (PENDIENTE, "Pendiente de pago"),
        (EN_PROCESO, "Pago en proceso"),
        (PAGADO, "Pagado"),
        (RECHAZADO, "Pago rechazado"),
        (CANCELADO, "Cancelado / reembolsado"),
        (ENVIADO, "Enviado"),
    ]
    PAID_STATUSES = (PAGADO, ENVIADO)

    DOC_CHOICES = [
        ("CC", "Cédula de ciudadanía"),
        ("CE", "Cédula de extranjería"),
        ("NIT", "NIT"),
        ("Otro", "Pasaporte / otro"),
    ]

    token = models.UUIDField("token público", default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField("estado", max_length=20, choices=STATUS_CHOICES, default=PENDIENTE, db_index=True)

    # Cliente
    full_name = models.CharField("nombre completo", max_length=150)
    email = models.EmailField("email")
    phone = models.CharField("celular", max_length=30)
    document_type = models.CharField("tipo de documento", max_length=10, choices=DOC_CHOICES, default="CC")
    document = models.CharField("documento", max_length=30)

    # Dirección de envío
    address = models.CharField("dirección", max_length=200)
    address2 = models.CharField("complemento", max_length=200, blank=True)
    city = models.CharField("ciudad / municipio", max_length=100)
    department = models.CharField("departamento", max_length=60, choices=DEPARTAMENTO_CHOICES)
    notes = models.TextField("notas del cliente", blank=True)

    # Montos (COP, enteros)
    subtotal = models.PositiveIntegerField("subtotal", default=0)
    shipping = models.PositiveIntegerField("envío", default=0)
    total = models.PositiveIntegerField("total", default=0)
    total_weight = models.PositiveIntegerField("peso total (g)", default=0)

    # Mercado Pago
    mp_preference_id = models.CharField("ID preferencia MP", max_length=100, blank=True)
    mp_payment_id = models.CharField("ID pago MP", max_length=50, blank=True, db_index=True)
    mp_status = models.CharField("estado MP", max_length=40, blank=True)
    mp_status_detail = models.CharField("detalle MP", max_length=100, blank=True)
    paid_at = models.DateTimeField("pagado el", null=True, blank=True)
    payment_note = models.TextField("observaciones del pago", blank=True)

    emails_sent = models.BooleanField("correos enviados", default=False)
    shipped_at = models.DateTimeField("enviado el", null=True, blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido"
        verbose_name_plural = "pedidos"

    def __str__(self) -> str:
        return f"{self.number} — {self.full_name}"

    @property
    def number(self) -> str:
        """Número legible del pedido (ej: VC-00012)."""
        return f"VC-{self.pk:05d}" if self.pk else "VC-nuevo"

    @property
    def is_paid(self) -> bool:
        return self.status in self.PAID_STATUSES

    @property
    def is_waiting(self) -> bool:
        return self.status in (self.PENDIENTE, self.EN_PROCESO)

    def get_absolute_url(self) -> str:
        return f"/pedido/{self.token}"

    def mark_paid(self) -> None:
        self.status = self.PAGADO
        if not self.paid_at:
            self.paid_at = timezone.now()


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "tienda.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="producto"
    )
    product_name = models.CharField("producto", max_length=200)
    product_slug = models.CharField("slug", max_length=160, blank=True)
    size = models.CharField("tamaño", max_length=40, blank=True)
    grind = models.CharField("molienda", max_length=60, blank=True)
    qty = models.PositiveIntegerField("cantidad")
    unit_price = models.PositiveIntegerField("precio unitario")
    unit_weight = models.PositiveIntegerField("peso unitario (g)", default=0)
    total = models.PositiveIntegerField("total")

    class Meta:
        verbose_name = "artículo"
        verbose_name_plural = "artículos"

    def __str__(self) -> str:
        return f"{self.qty}x {self.product_name}"

    @property
    def options_label(self) -> str:
        return " · ".join(part for part in (self.size, self.grind) if part)
