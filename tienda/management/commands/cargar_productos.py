"""Carga/actualiza el catálogo desde content/productos/*.md.

Uso: python manage.py cargar_productos
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.content import content_path, read_markdown
from tienda.models import Product, ProductSize


class Command(BaseCommand):
    help = "Carga los productos de content/productos/*.md en la base de datos"

    @transaction.atomic
    def handle(self, *args, **options):
        files = sorted(content_path("productos").glob("*.md"))
        links: dict[str, dict[str, list[str]]] = {}

        for index, file in enumerate(files):
            data, _ = read_markdown(file)
            slug = data.get("slug") or file.stem
            product, created = Product.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": data["name"],
                    "description": (data.get("description") or "").strip(),
                    "category": data.get("category", "Café"),
                    "image": (data.get("image") or "").lstrip("/"),
                    "price": int(data.get("price") or 0),
                    "weight": int(data.get("weight") or 0),
                    "featured": bool(data.get("featured", False)),
                    "origin": data.get("origin") or "",
                    "grind_options": data.get("grindOptions") or [],
                    "order": index,
                    "active": True,
                },
            )
            product.sizes.all().delete()
            for order, size in enumerate(data.get("sizes") or []):
                ProductSize.objects.create(
                    product=product,
                    name=str(size["name"]),
                    price=int(size["price"]),
                    weight=int(size["weight"]),
                    order=order,
                )
            links[slug] = {
                "optional": data.get("optionalProducts") or [],
                "accessory": data.get("accessoryProducts") or [],
            }
            self.stdout.write(f"{'Creado' if created else 'Actualizado'}: {product.name}")

        for slug, rel in links.items():
            product = Product.objects.get(slug=slug)
            product.optional_products.set(Product.objects.filter(slug__in=rel["optional"]))
            product.accessory_products.set(Product.objects.filter(slug__in=rel["accessory"]))

        self.stdout.write(self.style.SUCCESS(f"{len(files)} productos cargados."))
