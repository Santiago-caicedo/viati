"""Carrito de compras guardado en la sesión de Django.

Contrato compartido (lo usan tienda, carrito y el JS del frontend):
- En sesión solo se guarda {clave: {"slug", "size", "grind", "qty"}}.
- Precios y pesos se recalculan SIEMPRE desde la base de datos al leer el
  carrito, así un cliente no puede manipular el precio desde el navegador.
"""

from dataclasses import dataclass

from tienda.models import Product

SESSION_KEY = "carrito"
MAX_QTY = 99


@dataclass
class CartLine:
    key: str
    product: Product
    size: str
    grind: str
    qty: int
    unit_price: int
    unit_weight: int

    @property
    def total(self) -> int:
        return self.unit_price * self.qty

    @property
    def total_weight(self) -> int:
        return self.unit_weight * self.qty

    @property
    def options_label(self) -> str:
        return " · ".join(part for part in (self.size, self.grind) if part)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "slug": self.product.slug,
            "name": self.product.name,
            "image": self.product.image_url,
            "url": self.product.get_absolute_url(),
            "size": self.size,
            "grind": self.grind,
            "options": self.options_label,
            "qty": self.qty,
            "unit_price": self.unit_price,
            "total": self.total,
        }


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.data: dict = self.session.get(SESSION_KEY) or {}

    @staticmethod
    def make_key(slug: str, size: str, grind: str) -> str:
        return f"{slug}|{size}|{grind}"

    def _save(self) -> None:
        self.session[SESSION_KEY] = self.data
        self.session.modified = True

    def add(self, product: Product, size: str = "", grind: str = "", qty: int = 1) -> CartLine:
        _, _, size = product.resolve(size or None)
        grinds = product.grind_options or []
        if grinds:
            grind = grind if grind in grinds else grinds[0]
        else:
            grind = ""
        key = self.make_key(product.slug, size, grind)
        current = self.data.get(key, {"slug": product.slug, "size": size, "grind": grind, "qty": 0})
        current["qty"] = max(1, min(MAX_QTY, int(current["qty"]) + max(1, int(qty))))
        self.data[key] = current
        self._save()
        return next(line for line in self.lines() if line.key == key)

    def update(self, key: str, qty: int) -> None:
        if key not in self.data:
            return
        if qty <= 0:
            self.data.pop(key)
        else:
            self.data[key]["qty"] = min(MAX_QTY, qty)
        self._save()

    def remove(self, key: str) -> None:
        self.data.pop(key, None)
        self._save()

    def clear(self) -> None:
        self.data = {}
        self._save()

    def lines(self) -> list[CartLine]:
        slugs = {item["slug"] for item in self.data.values()}
        products = {
            p.slug: p
            for p in Product.objects.filter(slug__in=slugs, active=True).prefetch_related("sizes")
        }
        result: list[CartLine] = []
        stale: list[str] = []
        for key, item in self.data.items():
            product = products.get(item["slug"])
            if product is None:
                stale.append(key)
                continue
            price, weight, size = product.resolve(item.get("size") or None)
            result.append(
                CartLine(
                    key=key,
                    product=product,
                    size=size,
                    grind=item.get("grind", ""),
                    qty=int(item["qty"]),
                    unit_price=price,
                    unit_weight=weight,
                )
            )
        if stale:
            for key in stale:
                self.data.pop(key, None)
            self._save()
        return result

    @property
    def count(self) -> int:
        return sum(int(item["qty"]) for item in self.data.values())

    def subtotal(self, lines: list[CartLine] | None = None) -> int:
        return sum(line.total for line in (lines if lines is not None else self.lines()))

    def total_weight(self, lines: list[CartLine] | None = None) -> int:
        return sum(line.total_weight for line in (lines if lines is not None else self.lines()))
