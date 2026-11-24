from django.db import models
from django.templatetags.static import static


class Product(models.Model):
    """Producto de la tienda (equivalente a ProductSchema del proyecto Next.js).

    Si el producto tiene tamaños (ProductSize), el precio y peso de cada tamaño
    mandan; `price`/`weight` del producto aplican solo cuando no hay tamaños.
    """

    slug = models.SlugField("slug", max_length=160, unique=True)
    name = models.CharField("nombre", max_length=200)
    description = models.TextField("descripción", blank=True)
    category = models.CharField("categoría", max_length=80, default="Café")
    image = models.CharField(
        "imagen (ruta estática)",
        max_length=300,
        blank=True,
        help_text="Ruta dentro de static/, ej: images/productos/el-paraiso.png",
    )
    image_upload = models.ImageField(
        "imagen subida", upload_to="productos/", blank=True,
        help_text="Si se sube una imagen, reemplaza la ruta estática.",
    )
    image_url_external = models.CharField("imagen externa (Odoo)", max_length=500, blank=True)
    price = models.PositiveIntegerField("precio (COP)", default=0)
    weight = models.PositiveIntegerField("peso (g)", default=0)
    featured = models.BooleanField("destacado", default=False)
    origin = models.CharField("origen", max_length=120, blank=True)
    grind_options = models.JSONField("opciones de molienda", default=list, blank=True)
    optional_products = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="+", verbose_name="productos opcionales"
    )
    accessory_products = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="+", verbose_name="accesorios"
    )
    active = models.BooleanField("activo", default=True)
    order = models.PositiveIntegerField("orden", default=0)
    odoo_id = models.PositiveIntegerField("ID en Odoo", null=True, blank=True, unique=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "producto"
        verbose_name_plural = "productos"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return f"/tienda/{self.slug}"

    @property
    def image_url(self) -> str:
        if self.image_upload:
            return self.image_upload.url
        if self.image_url_external:
            return self.image_url_external
        if self.image:
            return static(self.image.lstrip("/").removeprefix("static/"))
        return static("images/logo.png")

    @property
    def size_list(self) -> list["ProductSize"]:
        """Tamaños ordenados de menor a mayor precio (usa prefetch si existe)."""
        return sorted(self.sizes.all(), key=lambda s: (s.price, s.order))

    @property
    def base_price(self) -> int:
        sizes = self.size_list
        return sizes[0].price if sizes else self.price

    @property
    def base_weight(self) -> int:
        sizes = self.size_list
        return sizes[0].weight if sizes else self.weight

    @property
    def has_multiple_prices(self) -> bool:
        sizes = self.size_list
        return bool(sizes) and any(s.price != sizes[0].price for s in sizes)

    def resolve(self, size_name: str | None) -> tuple[int, int, str]:
        """Devuelve (precio, peso, nombre_tamaño) para el tamaño pedido.

        El precio SIEMPRE sale del servidor: nunca se confía en el navegador.
        """
        sizes = self.size_list
        if sizes:
            for size in sizes:
                if size.name == size_name:
                    return size.price, size.weight, size.name
            return sizes[0].price, sizes[0].weight, sizes[0].name
        return self.price, self.weight, ""


class ProductSize(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="sizes")
    name = models.CharField("tamaño", max_length=40)
    price = models.PositiveIntegerField("precio (COP)")
    weight = models.PositiveIntegerField("peso (g)")
    order = models.PositiveIntegerField("orden", default=0)

    class Meta:
        ordering = ["price", "order"]
        verbose_name = "tamaño"
        verbose_name_plural = "tamaños"

    def __str__(self) -> str:
        return f"{self.product.name} — {self.name}"


class OdooSyncState(models.Model):
    """Fila única (pk=1) con el estado de la sincronización automática con Odoo.

    `started_at` es además el candado: solo sincroniza quien logra actualizarlo
    (ver tienda/odoo_sync.py).
    """

    started_at = models.DateTimeField("último intento", null=True, blank=True)
    finished_at = models.DateTimeField("terminó", null=True, blank=True)
    ok = models.BooleanField("salió bien", default=False)
    message = models.TextField("resultado", blank=True)

    class Meta:
        verbose_name = "sincronización con Odoo"
        verbose_name_plural = "sincronización con Odoo"

    def __str__(self) -> str:
        return "Sincronización con Odoo"
