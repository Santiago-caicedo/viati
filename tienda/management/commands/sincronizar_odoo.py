"""Sincroniza el catálogo desde Odoo (equivale a PRODUCTS_SOURCE=odoo).

Uso:
    python manage.py sincronizar_odoo             # crea/actualiza por odoo_id
    python manage.py sincronizar_odoo --dry-run   # solo muestra lo que haría
    python manage.py sincronizar_odoo --solo-odoo # además oculta los productos que no vienen de Odoo

Reglas:
- Se upsertea por `odoo_id`. Si no existe pero hay un producto con el mismo slug
  sin odoo_id (p. ej. cargado desde markdown), se adopta ese producto.
- Los productos de Odoo no tienen tamaños: se eliminan los tamaños del producto
  para que mande el precio de Odoo (lista ODOO_PRICELIST o list_price).
- Los productos sincronizados antes que ya no vienen de Odoo quedan inactivos.
- Si Odoo devuelve 0 productos no se cambia nada (igual que el fallback a markdown).
"""

from django.core.management.base import BaseCommand, CommandError

from tienda import odoo, odoo_sync


class Command(BaseCommand):
    help = "Crea/actualiza los productos de la tienda desde Odoo (por odoo_id)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="No guarda cambios")
        parser.add_argument(
            "--solo-odoo",
            action="store_true",
            help="Desactiva los productos que no provienen de Odoo",
        )

    def handle(self, *args, **options):
        try:
            data = odoo.fetch_products()
        except odoo.OdooConfigError as error:
            raise CommandError(
                f"{error}. Define ODOO_URL, ODOO_DB, ODOO_USER y ODOO_API_KEY en el entorno (.env)."
            ) from error
        except odoo.OdooError as error:
            raise CommandError(f"Error consumiendo la API de Odoo: {error}") from error

        if not data:
            self.stdout.write(self.style.WARNING("Odoo devolvió 0 productos; no se modificó el catálogo."))
            return

        if options["dry_run"]:
            for item in data:
                self.stdout.write(f"  {item['odoo_id']:>6}  {item['slug']:<40} {item['price']:>10}  {item['category']}")
            self.stdout.write(self.style.SUCCESS(f"{len(data)} productos leídos (dry-run, sin cambios)."))
            return

        creados, actualizados, ocultos = odoo_sync.aplicar(data, solo_odoo=options["solo_odoo"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Odoo sincronizado: {creados} creados, {actualizados} actualizados, {ocultos} desactivados."
            )
        )
