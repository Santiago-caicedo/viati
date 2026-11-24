# Viati Café — Django

Versión en Django del sitio de Viati Café (antes Next.js + Snipcart). Mismo diseño
(Tailwind v4 con los mismos tokens de color y fuentes), con **carrito propio** y
pago directo con **Mercado Pago Checkout Pro**.

## Arrancar en local (Windows)

```powershell
cd C:\Users\ASUS\Downloads\viati-django
.\.venv\Scripts\activate
python manage.py migrate
python manage.py cargar_productos        # carga content/productos/*.md (solo la primera vez)
python manage.py createsuperuser         # usuario para /admin
python manage.py runserver               # http://localhost:8000
```

El CSS de Tailwind ya está compilado en `static/css/app.css`; no se necesita Node.js
para ejecutar ni desplegar el sitio.

## Estructura

| App | Qué contiene |
|---|---|
| `core/` | Constantes del sitio, context processors, filtro `\|cop`, correo (Gmail SMTP o Resend), middlewares |
| `tienda/` | Productos (modelo + admin), inicio, `/tienda`, `/tienda/<slug>`, sincronización con Odoo |
| `paginas/` | Orígenes, Nosotros, Institucional, Contacto, Políticas, sitemap, robots, redirects de Wix |
| `carrito/` | Carrito en sesión, checkout, envíos, pedidos, Mercado Pago (preferencia + webhook), correos, estadísticas |
| `panel/` | Panel de gestión propio en `/panel` (login seguro, estadísticas, pedidos, productos, envíos) |
| `templates/` | `base.html`, header, footer, logo, 404/500, ajustes del `/admin` |
| `static/` | `css/app.css` (compilado, se sube al repo), `js/`, `images/` |
| `content/` | Markdown de productos, orígenes y nosotros |

## Panel de administración (`/admin`)

- **Productos:** precios, tamaños, moliendas, destacados, orden, activos.
- **Pedidos:** estado del pago, datos del cliente, acciones *marcar como enviado*,
  *reenviar correos* y *consultar pago en Mercado Pago*.
- **Tarifas de envío:** ⚠️ las tarifas cargadas son **de ejemplo**. Reemplázalas por
  las reales (en el sitio anterior vivían en el panel de Snipcart).

## Flujo de compra

1. El cliente agrega productos (el precio siempre se recalcula en el servidor).
2. `/checkout` → se crea el pedido y la preferencia de Mercado Pago → pago en MP.
3. Mercado Pago avisa a `SITE_URL/api/mercadopago/webhook`; el servidor consulta el pago
   en la API de MP, verifica monto y moneda, y marca el pedido como pagado.
4. Se envían una sola vez los correos a gerencia y al cliente.
5. El cliente vuelve a `/pedido/<token>`, que también verifica el pago (sirve en local,
   donde el webhook no puede llegar).

**Importante:** `SITE_URL` debe ser el dominio final (ej. `https://www.viaticafe.com`),
porque Mercado Pago no sigue redirecciones. Ese era el error del sitio anterior.

## Probar pagos

Usa credenciales de **prueba** de Mercado Pago (`MP_ACCESS_TOKEN=TEST-...`) y las
[tarjetas de prueba](https://www.mercadopago.com.co/developers/es/docs/checkout-pro/additional-content/your-integrations/test/cards).
En local el retorno a `/pedido/<token>` confirma el pago; para probar el webhook
real necesitas una URL pública (ngrok) en `SITE_URL`.

En desarrollo `EMAIL_DRY_RUN=true`: los correos no se envían, se guardan en `tmp_emails/`.

## Odoo (opcional)

Completa los datos `ODOO_*` en `.env` y pon `ODOO_SYNC_MINUTOS=5`: el catálogo se
sincroniza **solo** al visitar la tienda (en segundo plano, sin cron). El comando
`python manage.py sincronizar_odoo` (acepta `--dry-run`) queda para forzarlo a mano.

## Pruebas

```powershell
python manage.py test
```

## Producción

Todo el paso a paso (hosting, variables de entorno, base de datos, migraciones,
Mercado Pago, correo, Odoo y solución de problemas) está en **[DESPLIEGUE.md](DESPLIEGUE.md)**.
