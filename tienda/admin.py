from django.contrib import admin

from .models import OdooSyncState, Product, ProductSize


class ProductSizeInline(admin.TabularInline):
    model = ProductSize
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "base_price", "featured", "active", "order")
    list_editable = ("featured", "active", "order")
    list_filter = ("category", "featured", "active")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    filter_horizontal = ("optional_products", "accessory_products")
    inlines = [ProductSizeInline]


@admin.register(OdooSyncState)
class OdooSyncStateAdmin(admin.ModelAdmin):
    """Solo lectura: muestra cuándo fue la última sincronización y cómo salió."""

    list_display = ("__str__", "started_at", "finished_at", "ok", "message")
    readonly_fields = ("started_at", "finished_at", "ok", "message")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
