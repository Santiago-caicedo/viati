from django.contrib import admin, messages
from django.utils import timezone

from . import mercadopago as mp
from .emails import send_order_emails
from .models import Order, OrderItem, ShippingRate, StoreSettings


@admin.register(ShippingRate)
class ShippingRateAdmin(admin.ModelAdmin):
    list_display = ("__str__", "zona", "departamento", "min_g", "max_g", "price", "active")
    list_editable = ("price", "active")
    list_filter = ("zona", "active")
    ordering = ("zona", "departamento", "min_g")

    def changelist_view(self, request, extra_context=None):
        self.message_user(
            request,
            "Las tarifas sembradas son VALORES DE REFERENCIA (placeholder): las reales estaban en "
            "Snipcart. Ajústalas con las tarifas de la transportadora antes de vender.",
            messages.WARNING,
        )
        return super().changelist_view(request, extra_context)


@admin.register(StoreSettings)
class StoreSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not StoreSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ("product_name", "size", "grind", "qty", "unit_price", "total", "product")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "created_at", "full_name", "city", "department", "total", "status", "mp_status", "emails_sent")
    list_filter = ("status", "emails_sent", "department", "created_at")
    search_fields = ("token", "full_name", "email", "phone", "document", "mp_payment_id", "mp_preference_id")
    date_hierarchy = "created_at"
    inlines = [OrderItemInline]
    readonly_fields = (
        "number", "token", "subtotal", "shipping", "total", "total_weight",
        "mp_preference_id", "mp_payment_id", "mp_status", "mp_status_detail", "paid_at",
        "payment_note", "emails_sent", "shipped_at", "created_at", "updated_at",
    )
    fieldsets = (
        ("Pedido", {"fields": ("number", "token", "status", "created_at", "updated_at")}),
        ("Cliente", {"fields": ("full_name", "email", "phone", "document_type", "document")}),
        ("Envío", {"fields": ("address", "address2", "city", "department", "notes", "shipped_at")}),
        ("Montos", {"fields": ("subtotal", "shipping", "total", "total_weight")}),
        ("Mercado Pago", {"fields": (
            "mp_preference_id", "mp_payment_id", "mp_status", "mp_status_detail", "paid_at", "payment_note", "emails_sent",
        )}),
    )
    actions = ["marcar_enviado", "reenviar_correos", "verificar_pago"]

    @admin.display(description="número", ordering="pk")
    def number(self, obj):
        return obj.number

    @admin.action(description="Marcar como enviado")
    def marcar_enviado(self, request, queryset):
        updated = 0
        for order in queryset:
            if order.status == Order.PAGADO:
                order.status = Order.ENVIADO
                order.shipped_at = timezone.now()
                order.save(update_fields=["status", "shipped_at", "updated_at"])
                updated += 1
        self.message_user(request, f"{updated} pedido(s) marcados como enviados (solo aplica a pedidos pagados).")

    @admin.action(description="Reenviar correos (gerencia + cliente)")
    def reenviar_correos(self, request, queryset):
        sent = 0
        for order in queryset:
            if not order.is_paid:
                continue
            try:
                send_order_emails(order, force=True)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                self.message_user(request, f"{order.number}: {exc}", messages.ERROR)
        self.message_user(request, f"Correos reenviados para {sent} pedido(s) pagados.")

    @admin.action(description="Verificar pago en Mercado Pago")
    def verificar_pago(self, request, queryset):
        for order in queryset:
            try:
                updated = mp.refresh_order(order)
            except mp.MercadoPagoError as exc:
                self.message_user(request, f"{order.number}: {exc}", messages.ERROR)
                continue
            if updated.is_paid and not updated.emails_sent:
                try:
                    send_order_emails(updated)
                except Exception as exc:  # noqa: BLE001
                    self.message_user(request, f"{order.number}: correos fallaron ({exc})", messages.ERROR)
            self.message_user(request, f"{order.number}: {updated.get_status_display()}")
