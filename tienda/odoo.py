"""Integración con Odoo — Viati Café.

Port a Python de:
- src/lib/odoo/rpc.ts        → cliente JSON-RPC (login, execute_kw, cookie de sesión)
- src/lib/odoo/mappers.ts    → slugify, limpieza de texto, mapeo template → producto
- src/lib/odoo/pricing.ts    → precios desde la lista de precios web (ODOO_PRICELIST)
- src/lib/products/odoo.ts   → lectura del catálogo publicado en el sitio web
- src/app/api/odoo-image/[id]/route.ts → imagen cuadrada con fondo desenfocado (Pillow)

Las credenciales salen de settings: ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY,
ODOO_PRICELIST. Si faltan, se lanza OdooConfigError con un mensaje claro.
"""

from __future__ import annotations

import io
import logging
import math
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# RPC (rpc.ts)
# ════════════════════════════════════════════════════════════════════


class OdooError(Exception):
    """Error devuelto por Odoo o por la comunicación con Odoo."""


class OdooConfigError(OdooError):
    """Falta configuración de Odoo en settings / variables de entorno."""


class OdooImageNotFound(OdooError):
    """Odoo no devolvió imagen para el producto."""


def _config() -> dict[str, str]:
    return {
        "url": (getattr(settings, "ODOO_URL", "") or "").rstrip("/"),
        "db": getattr(settings, "ODOO_DB", "") or "",
        "user": getattr(settings, "ODOO_USER", "") or "",
        "api_key": getattr(settings, "ODOO_API_KEY", "") or "",
    }


def get_odoo_url() -> str:
    url = _config()["url"]
    if not url:
        raise OdooConfigError("ODOO_URL no está configurada")
    return url


def assert_config() -> None:
    cfg = _config()
    faltan = [
        nombre
        for nombre, valor in (
            ("ODOO_URL", cfg["url"]),
            ("ODOO_DB", cfg["db"]),
            ("ODOO_USER", cfg["user"]),
            ("ODOO_API_KEY", cfg["api_key"]),
        )
        if not valor
    ]
    if faltan:
        raise OdooConfigError(f"Falta configuración de Odoo: {', '.join(faltan)}")


def _json_rpc(service: str, method: str, args: list, timeout: float = 10):
    url = _config()["url"]
    try:
        response = requests.post(
            f"{url}/jsonrpc",
            json={"jsonrpc": "2.0", "method": "call", "params": {"service": service, "method": method, "args": args}},
            timeout=timeout,
        )
    except requests.RequestException as error:
        raise OdooError(f"No se pudo conectar con Odoo ({service}.{method}): {error}") from error

    if not response.ok:
        raise OdooError(f"Odoo respondió {response.status_code} en {service}.{method}")

    payload = response.json()
    if payload.get("error"):
        err = payload["error"]
        message = (err.get("data") or {}).get("message") or err.get("message") or "Error desconocido de Odoo JSON-RPC"
        raise OdooError(message)
    return payload.get("result")


_uid: int | None = None
_uid_lock = threading.Lock()


def _login() -> int:
    assert_config()
    cfg = _config()
    uid = _json_rpc("common", "login", [cfg["db"], cfg["user"], cfg["api_key"]])
    if not uid or uid < 0:
        raise OdooError("Login de Odoo falló: revisa ODOO_DB, ODOO_USER y ODOO_API_KEY")
    return uid


def get_uid() -> int:
    global _uid
    with _uid_lock:
        if _uid is None:
            _uid = _login()
        return _uid


def execute_kw(model: str, method: str, args: list | None = None, kwargs: dict | None = None):
    """Llama a un método de un modelo de Odoo (reintenta si la sesión expiró)."""
    global _uid
    cfg = _config()
    args = args or []
    kwargs = kwargs or {}
    uid = get_uid()
    try:
        return _json_rpc("object", "execute_kw", [cfg["db"], uid, cfg["api_key"], model, method, args, kwargs])
    except OdooError as error:
        if re.search(r"session|login|authenticat", str(error), re.I):
            with _uid_lock:
                _uid = None
            retry_uid = get_uid()
            return _json_rpc(
                "object", "execute_kw", [cfg["db"], retry_uid, cfg["api_key"], model, method, args, kwargs]
            )
        raise


_session_cookie: dict | None = None


def get_session_cookie() -> str | None:
    """Cookie session_id de Odoo (12 h) para descargar imágenes no públicas."""
    global _session_cookie
    if _session_cookie and _session_cookie["expires_at"] > time.time():
        return _session_cookie["value"]

    assert_config()
    cfg = _config()
    try:
        response = requests.post(
            f"{cfg['url']}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"db": cfg["db"], "login": cfg["user"], "password": cfg["api_key"]},
            },
            timeout=10,
        )
    except requests.RequestException:
        return None

    session_id = response.cookies.get("session_id")
    if not session_id:
        match = re.search(r"session_id=([^;]+)", response.headers.get("set-cookie", ""))
        session_id = match.group(1) if match else None
    if not session_id:
        return None

    _session_cookie = {"value": f"session_id={session_id}", "expires_at": time.time() + 12 * 3600}
    return _session_cookie["value"]


# ════════════════════════════════════════════════════════════════════
# Mappers (mappers.ts)
# ════════════════════════════════════════════════════════════════════


def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def sort_key(value: str) -> str:
    """Clave de orden aproximada a localeCompare(..., 'es')."""
    return _strip_accents(value).casefold()


def slugify(value: str) -> str:
    value = _strip_accents(value).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def clean_text(value) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]*>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def map_template(template: dict, used_slugs: set[str], category_names: dict[int, str], web_prices: dict[int, int]) -> dict:
    """Convierte un product.template de Odoo en los campos de Product."""
    name = clean_text(template.get("name")) or f"Producto {template['id']}"
    public_categ_ids = template.get("public_categ_ids")
    first_category = public_categ_ids[0] if isinstance(public_categ_ids, list) and public_categ_ids else None
    category = (first_category is not None and clean_text(category_names.get(first_category, ""))) or "General"
    description = clean_text(template.get("description_sale")) or clean_text(template.get("description"))

    slug = slugify(name)
    if not slug or slug in used_slugs:
        slug = f"{slug or 'producto'}-{template['id']}"
    used_slugs.add(slug)

    weight = template.get("weight")
    weight_kg = weight if isinstance(weight, (int, float)) and not isinstance(weight, bool) else 0
    price = web_prices.get(template["id"], template.get("list_price") or 0)

    return {
        "odoo_id": template["id"],
        "slug": slug,
        "name": name,
        "description": description,
        "category": category,
        "image": f"/api/odoo-image/{template['id']}",
        "price": price,
        "weight": round(weight_kg * 1000),
        "featured": True,
    }


# ════════════════════════════════════════════════════════════════════
# Precios (pricing.ts)
# ════════════════════════════════════════════════════════════════════

PRICELIST_ITEM_FIELDS = [
    "id", "product_tmpl_id", "product_id", "categ_id", "min_quantity", "compute_price",
    "fixed_price", "percent_price", "price_discount", "price_surcharge", "price_markup",
    "price_round", "price_min_margin", "price_max_margin", "base_pricelist_id",
    "date_start", "date_end",
]


def _num(value) -> float | None:
    """Odoo devuelve False en campos vacíos: solo se aceptan números."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _m2o_id(value) -> int | None:
    return value[0] if isinstance(value, list) and value and value[0] else None


def _js_round(value: float) -> int:
    """Math.round de JavaScript (redondea .5 hacia arriba)."""
    return math.floor(value + 0.5)


def _parse_odoo_date(value) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace(" ", "T"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _item_active(item: dict, now: float) -> bool:
    start = _parse_odoo_date(item.get("date_start"))
    end = _parse_odoo_date(item.get("date_end"))
    if start is not None and now < start:
        return False
    if end is not None and now > end:
        return False
    return True


def _uses_unsupported_features(item: dict) -> bool:
    return bool(item.get("base_pricelist_id")) or any(
        _num(item.get(field)) not in (None, 0)
        for field in ("price_round", "price_min_margin", "price_max_margin", "price_markup")
    )


def _compute_rule_price(item: dict, base_price: float) -> int | None:
    compute = item.get("compute_price")
    if compute == "fixed":
        fixed = _num(item.get("fixed_price"))
        return fixed if fixed is not None and fixed > 0 else None
    if compute == "percentage":
        percent = _num(item.get("percent_price")) or 0
        return _js_round(base_price * (1 - percent / 100))
    if compute == "formula":
        if _uses_unsupported_features(item):
            return None
        discount = _num(item.get("price_discount")) or 0
        surcharge = _num(item.get("price_surcharge")) or 0
        return _js_round(base_price - (base_price * discount) / 100 + surcharge)
    return None


def _item_specificity(item: dict) -> int:
    if _m2o_id(item.get("product_tmpl_id")):
        return 3
    if _m2o_id(item.get("categ_id")):
        return 2
    return 1


def _item_rank(item: dict) -> float:
    quantity = _num(item.get("min_quantity")) or 0
    return quantity * 1_000_000 + item["id"]


def _item_applies(item: dict, template: dict, category_chains: dict[int, set[int]]) -> bool:
    if _m2o_id(item.get("product_id")):
        return False
    tmpl_id = _m2o_id(item.get("product_tmpl_id"))
    if tmpl_id:
        return tmpl_id == template["id"]
    categ_id = _m2o_id(item.get("categ_id"))
    if categ_id:
        template_category = _m2o_id(template.get("categ_id"))
        if not template_category:
            return False
        chain = category_chains.get(template_category)
        return bool(chain) and categ_id in chain
    return True


def _build_category_chains() -> dict[int, set[int]]:
    categories = execute_kw("product.category", "search_read", [[]], {"fields": ["id", "parent_id"], "limit": 500}) or []
    parents = {c["id"]: _m2o_id(c.get("parent_id")) for c in categories}
    chains: dict[int, set[int]] = {}
    for category in categories:
        cid = category["id"]
        if cid in chains:
            continue
        chain = {cid}
        chains[cid] = chain
        parent = parents.get(cid)
        while parent is not None and parent not in chain:
            chain.add(parent)
            parent = parents.get(parent)
    return chains


def resolve_pricelist_prices(templates: list[dict]) -> dict[int, int]:
    """Precio web por template según la lista de precios ODOO_PRICELIST (en COP)."""
    prices: dict[int, int] = {}
    pricelist_name = getattr(settings, "ODOO_PRICELIST", "")
    if not pricelist_name or not templates:
        return prices

    try:
        pricelists = execute_kw(
            "product.pricelist", "search_read", [[["name", "=", pricelist_name]]],
            {"fields": ["id", "name", "currency_id"], "limit": 1},
        )
    except OdooError as error:
        logger.warning('[odoo] No se pudo consultar la lista de precios "%s": %s', pricelist_name, error)
        return prices

    if not pricelists:
        logger.warning('[odoo] La lista de precios "%s" (ODOO_PRICELIST) no existe; se usa list_price', pricelist_name)
        return prices

    currency = pricelists[0].get("currency_id")
    if not currency or not re.search(r"COP", str(currency[1]), re.I):
        logger.warning(
            '[odoo] La lista de precios "%s" no está en COP (%s); se usa list_price',
            pricelist_name, currency[1] if currency else "sin moneda",
        )
        return prices

    try:
        items = execute_kw(
            "product.pricelist.item", "search_read", [[["pricelist_id", "=", pricelists[0]["id"]]]],
            {"fields": PRICELIST_ITEM_FIELDS, "limit": 500},
        )
    except OdooError as error:
        logger.warning('[odoo] No se pudieron leer las reglas de la lista "%s": %s', pricelist_name, error)
        return prices

    if not items:
        return prices

    category_chains: dict[int, set[int]] = {}
    if any(_m2o_id(item.get("categ_id")) for item in items):
        try:
            category_chains = _build_category_chains()
        except OdooError:
            logger.warning("[odoo] No se pudo construir el árbol de categorías; las reglas por categoría se ignoran")

    now = time.time()
    warned_unsupported = False

    for template in templates:
        best = None
        best_specificity = 0
        for item in items:
            if not _item_active(item, now):
                continue
            min_qty = _num(item.get("min_quantity"))
            if min_qty is not None and min_qty > 1:
                continue
            if not _item_applies(item, template, category_chains):
                continue
            specificity = _item_specificity(item)
            if best is None or specificity > best_specificity or (
                specificity == best_specificity and _item_rank(item) > _item_rank(best)
            ):
                best = item
                best_specificity = specificity

        if best is None:
            continue

        price = _compute_rule_price(best, template.get("list_price") or 0)
        if price is not None and price > 0:
            prices[template["id"]] = round(price)
        elif best.get("compute_price") == "formula" and _uses_unsupported_features(best) and not warned_unsupported:
            warned_unsupported = True
            logger.warning(
                "[odoo] Hay reglas de precio con fórmula avanzada (base en otra lista, redondeo, "
                "márgenes o markup); esos productos usan list_price"
            )

    return prices


# ════════════════════════════════════════════════════════════════════
# Catálogo (products/odoo.ts)
# ════════════════════════════════════════════════════════════════════

TEMPLATE_FIELDS = [
    "id", "name", "list_price", "description_sale", "description", "categ_id",
    "public_categ_ids", "weight", "optional_product_ids", "accessory_product_ids",
]
PRODUCT_LIMIT = 200


def _dedupe(values) -> list[int]:
    seen: list[int] = []
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool) and value not in seen:
            seen.append(value)
    return seen


def _ids(template: dict, field: str) -> list[int]:
    value = template.get(field)
    return _dedupe(value) if isinstance(value, list) else []


def fetch_products() -> list[dict]:
    """Lee el catálogo publicado (sale_ok + website_published) desde Odoo.

    Devuelve dicts con los campos de Product más `optional_slugs` y
    `accessory_slugs` (slugs de otros productos del catálogo).
    """
    assert_config()

    public_categories = execute_kw(
        "product.public.category", "search_read", [[]], {"fields": ["id", "name"], "limit": 200}
    ) or []
    category_names = {c["id"]: c["name"] for c in public_categories}

    templates = execute_kw(
        "product.template", "search_read",
        [[["sale_ok", "=", True], ["website_published", "=", True]]],
        {"fields": TEMPLATE_FIELDS, "order": "name asc", "limit": PRODUCT_LIMIT},
    ) or []
    if not templates:
        return []

    accessory_variant_ids = _dedupe(i for t in templates for i in _ids(t, "accessory_product_ids"))
    variant_to_template: dict[int, int] = {}
    if accessory_variant_ids:
        variants = execute_kw(
            "product.product", "search_read", [[["id", "in", accessory_variant_ids]]],
            {"fields": ["product_tmpl_id"], "limit": PRODUCT_LIMIT},
        ) or []
        for variant in variants:
            tmpl_id = _m2o_id(variant.get("product_tmpl_id"))
            if tmpl_id:
                variant_to_template[variant["id"]] = tmpl_id

    base_ids = [t["id"] for t in templates]
    optional_ids = _dedupe(i for t in templates for i in _ids(t, "optional_product_ids"))
    all_ids = _dedupe([*base_ids, *optional_ids, *variant_to_template.values()])
    extra_ids = [i for i in all_ids if i not in base_ids]

    full_templates = list(templates)
    if extra_ids:
        extra = execute_kw(
            "product.template", "search_read", [[["id", "in", extra_ids]]],
            {"fields": TEMPLATE_FIELDS, "limit": PRODUCT_LIMIT},
        ) or []
        seen = set(base_ids)
        for template in extra:
            if template["id"] not in seen:
                seen.add(template["id"])
                full_templates.append(template)

    web_prices = resolve_pricelist_prices(full_templates)

    used_slugs: set[str] = set()
    by_template: dict[int, dict] = {}
    for template in full_templates:
        product = map_template(template, used_slugs, category_names, web_prices)
        if product["price"] <= 0:
            continue
        by_template[template["id"]] = product

    result = []
    for template in templates:
        product = by_template.get(template["id"])
        if not product:
            continue
        optional_slugs = _unique(
            by_template[i]["slug"] for i in _ids(template, "optional_product_ids") if i in by_template
        )
        accessory_slugs = _unique(
            by_template[variant_to_template[v]]["slug"]
            for v in _ids(template, "accessory_product_ids")
            if variant_to_template.get(v) in by_template
        )
        result.append({**product, "optional_slugs": optional_slugs, "accessory_slugs": accessory_slugs})
    return result


def _unique(values) -> list[str]:
    out: list[str] = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


# ════════════════════════════════════════════════════════════════════
# Imagen cuadrada (api/odoo-image/[id]/route.ts) — sharp → Pillow
# ════════════════════════════════════════════════════════════════════

SQUARE_SIZE = 1200
BLUR_SIGMA = 14
WEBP_QUALITY = 84
AREA_FRACTION_CARD = 0.62
AREA_FRACTION_MIN = 0.1
AREA_FRACTION_MAX = 0.95
FIT_FRACTION_CARD = 0.92
FIT_FRACTION_MIN = 0.3
FIT_FRACTION_MAX = 0.95
BOX_MIN = 280
BOX_MAX = SQUARE_SIZE - 80
TRIM_THRESHOLD = 12
TRIM_MIN_EDGE = 160
WASH_COLOR = (46, 38, 26, 48)
IMAGE_CACHE_SECONDS = 3600


def _to_number(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def clamp_area_fraction(value) -> float:
    number = _to_number(value)
    if not math.isfinite(number) or number <= 0:
        return AREA_FRACTION_CARD
    return min(max(number / 100, AREA_FRACTION_MIN), AREA_FRACTION_MAX)


def clamp_fit_fraction(value) -> float:
    number = _to_number(value)
    if not math.isfinite(number) or number <= 0:
        return FIT_FRACTION_CARD
    return min(max(number / 100, FIT_FRACTION_MIN), FIT_FRACTION_MAX)


def _fetch_odoo_image(template_id: int) -> bytes:
    url = f"{get_odoo_url()}/web/image/product.template/{template_id}/image_1920"
    response = requests.get(url, timeout=20)
    if not response.ok:
        cookie = get_session_cookie()
        if cookie:
            response = requests.get(url, headers={"Cookie": cookie}, timeout=20)
    if not response.ok or not response.content:
        raise OdooImageNotFound(f"Odoo no devolvió imagen para el template {template_id}")
    return response.content


def _trim_neutral_border(image):
    """Recorta el borde del color de la esquina superior izquierda (sharp.trim)."""
    from PIL import Image, ImageChops

    try:
        rgba = image.convert("RGBA")
        corner = rgba.getpixel((0, 0))
        background = Image.new("RGBA", rgba.size, corner)
        diff = ImageChops.difference(rgba, background)
        r, g, b, a = diff.split()
        mask = ImageChops.lighter(ImageChops.lighter(r, g), ImageChops.lighter(b, a))
        mask = mask.point(lambda p: 255 if p > TRIM_THRESHOLD else 0)
        bbox = mask.getbbox()
        if bbox:
            trimmed = image.crop(bbox)
            if trimmed.width >= TRIM_MIN_EDGE and trimmed.height >= TRIM_MIN_EDGE:
                return trimmed
    except Exception:  # noqa: BLE001 — trim no apto: se usa la original
        pass
    return image


def _radial_mask(size: int, cx: float, cy: float, radius: float, stops: list[tuple[float, float]]):
    """Máscara L de un degradado radial (offset 0..1 → opacidad 0..1)."""
    from PIL import Image

    small = 300
    scale = size / small
    pixels = []
    for y in range(small):
        dy = (y + 0.5) * scale - cy
        for x in range(small):
            dx = (x + 0.5) * scale - cx
            t = min(math.hypot(dx, dy) / radius, 1.0)
            alpha = stops[-1][1]
            for (o1, a1), (o2, a2) in zip(stops, stops[1:]):
                if o1 <= t <= o2:
                    alpha = a1 + (a2 - a1) * ((t - o1) / (o2 - o1) if o2 > o1 else 0)
                    break
            pixels.append(round(alpha * 255))
    mask = Image.new("L", (small, small))
    mask.putdata(pixels)
    return mask.resize((size, size), Image.BILINEAR)


def to_square_image(raw: bytes, area_fraction: float, fit_fraction: float) -> bytes:
    """Lienzo cuadrado: fondo desenfocado + producto centrado + glow y viñeta."""
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

    source = Image.open(io.BytesIO(raw))
    source = ImageOps.exif_transpose(source).convert("RGBA")
    source = _trim_neutral_border(source)
    width, height = source.size
    if width <= 0 or height <= 0:
        raise ValueError("Dimensiones de imagen inválidas")

    max_dim, min_dim = max(width, height), min(width, height)
    stage_box = round(SQUARE_SIZE * fit_fraction)
    area_box = round(SQUARE_SIZE * math.sqrt(area_fraction) * math.sqrt(max_dim / min_dim))
    foreground_box = min(max(min(area_box, stage_box), BOX_MIN), BOX_MAX)

    # Fondo: cover + blur + menos saturación y brillo
    background = ImageOps.fit(source, (SQUARE_SIZE, SQUARE_SIZE), Image.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(BLUR_SIGMA))
    alpha = background.getchannel("A")
    rgb = background.convert("RGB")
    rgb = ImageEnhance.Color(rgb).enhance(0.45)
    rgb = ImageEnhance.Brightness(rgb).enhance(0.96)

    # Velo cálido en modo multiply
    r, g, b, a = WASH_COLOR
    washed = ImageChops.multiply(rgb, Image.new("RGB", rgb.size, (r, g, b)))
    rgb = Image.blend(rgb, washed, a / 255)

    # Glow en modo screen
    glow_color = Image.new("RGB", rgb.size, (255, 241, 222))
    glow_mask = _radial_mask(
        SQUARE_SIZE, SQUARE_SIZE / 2, SQUARE_SIZE * 0.46, SQUARE_SIZE * 0.6,
        [(0, 0.16), (0.55, 0.05), (1, 0)],
    )
    rgb = Image.composite(ImageChops.screen(rgb, glow_color), rgb, glow_mask)

    canvas = rgb.convert("RGBA")
    canvas.putalpha(alpha)

    # Producto centrado (fit inside, también amplía como sharp)
    scale = foreground_box / max(width, height)
    fg_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    foreground = source.resize(fg_size, Image.LANCZOS)
    offset = ((SQUARE_SIZE - fg_size[0]) // 2, (SQUARE_SIZE - fg_size[1]) // 2)
    canvas.alpha_composite(foreground, offset)

    # Viñeta en modo multiply
    vignette_mask = _radial_mask(
        SQUARE_SIZE, SQUARE_SIZE / 2, SQUARE_SIZE / 2, SQUARE_SIZE * 0.75,
        [(0, 0), (0.72, 0), (1, 0.22)],
    )
    final_alpha = canvas.getchannel("A")
    rgb = canvas.convert("RGB")
    darkened = ImageChops.multiply(rgb, Image.new("RGB", rgb.size, (9, 13, 10)))
    rgb = Image.composite(darkened, rgb, vignette_mask)
    result = rgb.convert("RGBA")
    result.putalpha(final_alpha)

    out = io.BytesIO()
    if final_alpha.getextrema() == (255, 255):
        result = result.convert("RGB")
    result.save(out, "WEBP", quality=WEBP_QUALITY)
    return out.getvalue()


def _cache_path(template_id: int, area: float, fit: float) -> Path:
    folder = Path(settings.MEDIA_ROOT) / "odoo"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{template_id}-a{round(area * 100)}-f{round(fit * 100)}.webp"


def get_square_image(template_id: int, area: float, fit: float) -> bytes:
    """Devuelve la imagen procesada usando la caché en MEDIA_ROOT/odoo/ (1 h).

    Si Odoo falla y existe una versión anterior en caché, se sirve esa.
    """
    path = _cache_path(template_id, area, fit)
    if path.exists() and time.time() - path.stat().st_mtime < IMAGE_CACHE_SECONDS:
        return path.read_bytes()

    try:
        raw = _fetch_odoo_image(template_id)
        data = to_square_image(raw, area, fit)
    except Exception:
        if path.exists():
            return path.read_bytes()
        raise

    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return data
