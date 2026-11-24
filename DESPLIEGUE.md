# Guía de despliegue — Viati Café (Django)

Esta guía es para quien va a poner el sitio en producción **sin experiencia previa en
Django**. Síguela en orden. Cada paso dice qué hacer y por qué.

---

## 1. Qué es este proyecto

| Pieza | Tecnología |
|---|---|
| Lenguaje | **Python 3.12** (ver `.python-version`) |
| Framework web | **Django 6.1** |
| Servidor de aplicación | **Gunicorn** (comando en `Procfile`) |
| Archivos estáticos (CSS, JS, imágenes) | **WhiteNoise**: los sirve el propio Django, no hace falta Nginx ni CDN |
| Base de datos | **PostgreSQL** en producción (SQLite solo en el computador del desarrollador) |
| Pagos | **Mercado Pago Checkout Pro** (redirección + webhook) |
| Correo | **SMTP de Gmail / Google Workspace** (o Resend como alternativa) |
| Catálogo | Productos en la base de datos; opcionalmente se sincronizan solos desde **Odoo** |
| Estilos | Tailwind CSS, **ya compilado** en `static/css/app.css`. No se necesita Node.js para desplegar |

Todas las dependencias de Python están en `requirements.txt`.

### Conceptos de Django que vas a ver

- **`manage.py`**: la "consola" de Django. Todos los comandos son `python manage.py <comando>`.
- **Migraciones** (`python manage.py migrate`): crean y actualizan las tablas de la base de
  datos. Se ejecutan **en cada despliegue**; si no hay cambios no hacen nada.
- **`collectstatic`**: copia todos los archivos estáticos a la carpeta `staticfiles/`, de donde
  los sirve WhiteNoise. También se ejecuta en cada despliegue.
- **Superusuario**: el usuario administrador que entra a `/admin` y `/panel`.
- **`.env` / variables de entorno**: toda la configuración secreta (claves, contraseñas,
  dominio) se lee de variables de entorno. **Nada secreto va en el código.**

---

## 2. Requisitos del hosting

Sirve cualquier hosting que ejecute Python (Railway, Render, Fly.io, Heroku, un VPS con
Ubuntu, cPanel con "Setup Python App", etc.). Necesitas:

1. **Python 3.12**.
2. **Una base de datos PostgreSQL** (casi todos los hostings la ofrecen con un clic).
3. **HTTPS** con el dominio final (Mercado Pago exige https para el webhook).
4. **Un disco persistente** si se van a subir fotos de productos desde el panel
   (ver sección 7). Sin disco persistente las fotos subidas se borran en cada despliegue.

---

## 3. Variables de entorno

En el hosting se configuran en su panel ("Variables", "Environment", "Config Vars").
En un VPS se pone un archivo `.env` en la raíz del proyecto (al lado de `manage.py`).
**El archivo `.env` nunca se sube a GitHub** (ya está excluido en `.gitignore`).

> 🔐 **Las credenciales reales (contraseña del correo, token de Mercado Pago, etc.) NO
> están en este repositorio**, porque es público. El dueño del proyecto te las entrega
> por un canal privado (el archivo `.env` directamente, o un gestor de contraseñas).

### Plantilla de producción

Copia esto y reemplaza lo que está entre `< >`:

```env
# ===== Django =====
DJANGO_SECRET_KEY=<clave larga y aleatoria, ver abajo cómo generarla>
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=www.viaticafe.com,viaticafe.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://www.viaticafe.com,https://viaticafe.com
SITE_URL=https://www.viaticafe.com

# ===== Base de datos PostgreSQL =====
DATABASE_URL=postgres://<usuario>:<contraseña>@<host>:5432/<nombre_bd>

# ===== Correo (Gmail / Google Workspace) =====
EMAIL_PROVIDER=smtp
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=gerencia@agroambientec.com
EMAIL_HOST_PASSWORD=<contraseña de APLICACIÓN de Google, 16 letras>
EMAIL_FROM=Viati Café <gerencia@agroambientec.com>
EMAIL_GERENCIA=gerencia@agroambientec.com
EMAIL_DRY_RUN=false
RESEND_API_KEY=

# ===== Mercado Pago (credenciales de PRODUCCIÓN, empiezan por APP_USR-) =====
MP_ACCESS_TOKEN=<access token de producción>
MP_WEBHOOK_SECRET=<clave secreta de webhooks>

# ===== Google Analytics 4 (opcional) =====
GA_MEASUREMENT_ID=<G-XXXXXXXXXX>

# ===== Fotos subidas desde el panel =====
MEDIA_ROOT=/data/media
SERVE_MEDIA=true

# ===== Odoo (opcional) =====
ODOO_URL=
ODOO_DB=
ODOO_USER=
ODOO_API_KEY=
ODOO_PRICELIST=Precios Web
ODOO_SYNC_MINUTOS=0
ODOO_SYNC_SOLO_ODOO=false
```

### Qué es cada variable

#### Django

| Variable | Qué poner | Cuidado |
|---|---|---|
| `DJANGO_SECRET_KEY` | Una clave aleatoria de 50+ caracteres. Generarla con: `python -c "import secrets; print(secrets.token_urlsafe(50))"` | Nunca compartirla ni reutilizar la de ejemplo. Si cambia, se cierran las sesiones abiertas y se vacían los carritos. |
| `DJANGO_DEBUG` | `false` en producción, **siempre**. | Con `true` se muestran errores con datos internos a cualquier visitante y se desactivan las protecciones de https. |
| `DJANGO_ALLOWED_HOSTS` | Los dominios por los que se entra al sitio, separados por coma, **sin** `https://` ni `/`. Ej: `www.viaticafe.com,viaticafe.com`. Si el hosting da un dominio propio (ej. `viati.up.railway.app`), agrégalo también. | Si falta un dominio, Django responde **"Bad Request (400)"**. Es el error más común del primer despliegue. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Los mismos dominios **con** `https://`, separados por coma. | Si falta, los formularios (checkout, contacto, login de `/admin` y `/panel`) fallan con **"Forbidden (403) CSRF"**. |
| `SITE_URL` | La URL pública **final**, con `https://` y **sin** `/` al final. | Debe ser el dominio que **no redirige**. Si `viaticafe.com` redirige a `www.viaticafe.com`, usa la de `www`. Mercado Pago no sigue redirecciones: si esto está mal, los pagos no se confirman (ese fue el fallo del sitio anterior). |
| `DJANGO_SSL_REDIRECT` | Opcional. Por defecto `true` (redirige http → https). | Ponla en `false` solo si el hosting ya redirige y aparece un bucle de redirecciones. |
| `DJANGO_HSTS_SECONDS` | Opcional. Por defecto `0`. | Cuando el sitio lleve unos días funcionando bien con https, subir a `31536000`. |

#### Base de datos

| Variable | Qué poner |
|---|---|
| `DATABASE_URL` | La URL de conexión de PostgreSQL: `postgres://usuario:contraseña@host:5432/nombre_bd`. Railway, Render, etc. la dan lista para copiar. Si el hosting exige SSL, agregar `?sslmode=require` al final. |

Si se deja vacía, Django usa un archivo SQLite local. **No hacer eso en producción**: los
datos se pierden en cada despliegue en la mayoría de hostings.

#### Correo

El sitio envía correos al cliente y a gerencia cuando entra un pago, y a gerencia cuando
alguien usa los formularios de contacto e institucional.

| Variable | Qué poner |
|---|---|
| `EMAIL_PROVIDER` | `smtp` (Gmail / Google Workspace) o `resend`. |
| `EMAIL_HOST`, `EMAIL_PORT` | `smtp.gmail.com` y `587`. |
| `EMAIL_HOST_USER` | La cuenta que envía: `gerencia@agroambientec.com`. |
| `EMAIL_HOST_PASSWORD` | Una **contraseña de aplicación** de Google (16 letras), **no** la contraseña normal de la cuenta. Se crea en <https://myaccount.google.com/apppasswords> (la cuenta necesita verificación en dos pasos activa). |
| `EMAIL_FROM` | Remitente visible. Debe usar la misma cuenta de `EMAIL_HOST_USER` (o un alias verificado en Gmail). |
| `EMAIL_GERENCIA` | A dónde llegan los avisos de pedidos y formularios. |
| `EMAIL_DRY_RUN` | `false` en producción. Con `true` los correos **no se envían**, solo se guardan en `tmp_emails/`. |
| `RESEND_API_KEY` | Solo si `EMAIL_PROVIDER=resend`. |

Probar el correo después de desplegar:

```bash
python manage.py probar_correo --para tu-correo@ejemplo.com
```

#### Mercado Pago

| Variable | Qué poner |
|---|---|
| `MP_ACCESS_TOKEN` | En <https://www.mercadopago.com.co/developers/panel/app> → tu aplicación → **Credenciales de producción** → *Access Token* (empieza por `APP_USR-`). Las de prueba empiezan por `TEST-` y no cobran de verdad. |
| `MP_WEBHOOK_SECRET` | En el mismo panel → **Webhooks** → *Clave secreta*. Con ella el servidor verifica que los avisos vienen de verdad de Mercado Pago. |

#### Fotos subidas desde el panel

| Variable | Qué poner |
|---|---|
| `MEDIA_ROOT` | Carpeta de un **disco persistente** del hosting, ej. `/data/media` (en Railway: crear un *Volume* montado en `/data`). |
| `SERVE_MEDIA` | `true` para que Django sirva esas fotos. Si las sirve Nginx u otro servicio, `false`. |

Las imágenes del diseño (logo, fotos de orígenes, productos iniciales) **no** dependen de
esto: están en `static/` y van en el repositorio.

#### Odoo (opcional)

El catálogo se puede sincronizar **automáticamente** desde Odoo: cuando alguien visita la
tienda y ya pasaron `ODOO_SYNC_MINUTOS` desde la última vez, el servidor lee Odoo en
segundo plano (la página no se pone lenta). **No hace falta cron ni tareas programadas.**

| Variable | Qué poner |
|---|---|
| `ODOO_URL` | URL de Odoo, ej. `https://empresa.odoo.com` (sin `/` final). |
| `ODOO_DB` | Nombre de la base de datos de Odoo. |
| `ODOO_USER` | Usuario (correo) de Odoo. |
| `ODOO_API_KEY` | API key del usuario (Odoo → Preferencias → Seguridad de la cuenta → Nueva clave API). |
| `ODOO_PRICELIST` | Lista de precios a usar. Por defecto `Precios Web`. |
| `ODOO_SYNC_MINUTOS` | Cada cuántos minutos se sincroniza. `5` es un buen valor; `0` apaga la sincronización. Solo funciona si los 4 datos de arriba están completos. |
| `ODOO_SYNC_SOLO_ODOO` | `true` oculta los productos que no existen en Odoo. |

Para forzar una sincronización a mano (o ver qué cambiaría sin tocar nada):

```bash
python manage.py sincronizar_odoo --dry-run   # solo muestra
python manage.py sincronizar_odoo             # aplica
```

---

## 4. Comandos de despliegue

### Primera vez

```bash
pip install -r requirements.txt
python manage.py migrate              # crea las tablas en PostgreSQL
python manage.py createcachetable     # tabla de caché (bloqueo de intentos de login)
python manage.py collectstatic --noinput
python manage.py cargar_productos     # carga los 8 productos iniciales (content/productos/*.md)
python manage.py createsuperuser      # pide usuario, correo y contraseña del administrador
```

Y para arrancar el servidor (es lo que dice el `Procfile`, la mayoría de hostings lo lee solo):

```bash
gunicorn config.wsgi --bind 0.0.0.0:$PORT --workers 3 --timeout 60 --access-logfile -
```

> `cargar_productos` y `createsuperuser` se ejecutan **solo la primera vez**.
> `createcachetable` es seguro repetirlo.

### Cada nuevo despliegue (cuando cambia el código)

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
# reiniciar gunicorn (en Railway/Render es automático)
```

En hostings tipo Railway/Render se configura así:

| Campo del hosting | Valor |
|---|---|
| Build command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Pre-deploy / Release command | `python manage.py migrate && python manage.py createcachetable` |
| Start command | el del `Procfile` (se detecta solo) |

### En un VPS (Ubuntu) sin plataforma

1. Instalar Python 3.12, PostgreSQL y Nginx.
2. Clonar el repo, crear entorno: `python3.12 -m venv .venv && source .venv/bin/activate`.
3. Crear el archivo `.env` con la plantilla de la sección 3.
4. Ejecutar los comandos de "Primera vez".
5. Dejar gunicorn como servicio de `systemd` escuchando en `127.0.0.1:8000`.
6. Nginx como proxy hacia `127.0.0.1:8000`, con certificado de Let's Encrypt (`certbot`).
   Nginx **debe** enviar la cabecera `X-Forwarded-Proto $scheme`; sin ella Django cree que
   la petición es http y entra en un bucle de redirecciones.

---

## 5. Configurar Mercado Pago

1. En el panel de desarrolladores de Mercado Pago → tu aplicación → **Webhooks**:
   - URL de producción: `https://www.viaticafe.com/api/mercadopago/webhook`
     (es `SITE_URL` + `/api/mercadopago/webhook`).
   - Evento: **Pagos**.
   - Copiar la **clave secreta** a `MP_WEBHOOK_SECRET`.
2. Poner el Access Token de **producción** en `MP_ACCESS_TOKEN`.
3. Hacer una compra real de bajo valor y verificar que:
   - el pedido aparece como **pagado** en `/panel` → Pedidos;
   - llegan los correos al cliente y a gerencia.

Cómo funciona: el cliente paga en Mercado Pago, Mercado Pago avisa al webhook, el
servidor **consulta el pago a la API de Mercado Pago** (no confía en el aviso), revisa que
el monto y la moneda coincidan y marca el pedido como pagado. Los correos se envían una
sola vez por pedido.

---

## 6. Primeros pasos después de desplegar

1. Entrar a `https://<dominio>/panel` (o `/admin`) con el superusuario.
2. **Tarifas de envío**: las que trae el sistema son **de ejemplo**. Reemplazarlas por
   las reales en el panel → Envíos.
3. Revisar precios, tamaños y fotos de los productos.
4. Probar el formulario de contacto y `python manage.py probar_correo`.
5. Hacer la compra de prueba de la sección 5.

Direcciones útiles:

| Ruta | Qué es |
|---|---|
| `/panel` | Panel de gestión propio (pedidos, productos, envíos, estadísticas) |
| `/admin` | Administrador de Django (todo, más técnico) |
| `/sitemap.xml`, `/robots.txt` | SEO |

---

## 7. Base de datos y copias de seguridad

- Toda la información importante (pedidos, clientes, productos, tarifas) vive en
  **PostgreSQL**. Activar las **copias automáticas** del hosting.
- Copia manual: `pg_dump "$DATABASE_URL" > viati-$(date +%F).sql`
- Restaurar: `psql "$DATABASE_URL" < viati-AAAA-MM-DD.sql`
- Las **fotos subidas desde el panel** viven en `MEDIA_ROOT` (no en la base de datos):
  incluir esa carpeta en las copias.
- Los archivos `db.sqlite3` del desarrollador **no se suben** al repo (tienen datos de
  clientes de pruebas) y no se usan en producción.

---

## 8. Seguridad — lista de verificación

- [ ] `DJANGO_DEBUG=false`
- [ ] `DJANGO_SECRET_KEY` nueva, aleatoria y secreta
- [ ] `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` solo con los dominios reales
- [ ] El sitio carga con `https://` y el candado
- [ ] `.env` **no** está en GitHub (el repo es público)
- [ ] Contraseña fuerte para el superusuario
- [ ] Credenciales de Mercado Pago de **producción** y `MP_WEBHOOK_SECRET` configurado
- [ ] `EMAIL_DRY_RUN=false` y correo de prueba recibido
- [ ] Copias automáticas de PostgreSQL activadas
- [ ] Tras unos días estable, `DJANGO_HSTS_SECONDS=31536000`

---

## 9. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| **Bad Request (400)** en todas las páginas | El dominio no está en `DJANGO_ALLOWED_HOSTS` | Agregarlo (sin `https://`) y reiniciar |
| **Forbidden (403) CSRF** al enviar formularios o al iniciar sesión | Falta el dominio en `DJANGO_CSRF_TRUSTED_ORIGINS` | Agregarlo **con** `https://` |
| **"Demasiadas redirecciones"** | El proxy no envía `X-Forwarded-Proto` | Configurarlo en Nginx, o `DJANGO_SSL_REDIRECT=false` si el hosting ya fuerza https |
| La página sale **sin estilos** | No se ejecutó `collectstatic` | `python manage.py collectstatic --noinput` y reiniciar |
| **Server Error (500)** al arrancar o en el panel | Faltan migraciones o la tabla de caché | `python manage.py migrate` y `python manage.py createcachetable`; revisar los logs del hosting |
| El cliente paga pero el pedido sigue **pendiente** | `SITE_URL` incorrecta o redirige; webhook mal configurado | `SITE_URL` = dominio final sin redirección; revisar la URL del webhook en Mercado Pago. En `/admin` → Pedidos existe la acción *consultar pago en Mercado Pago* |
| No llegan correos | Contraseña normal en vez de contraseña de aplicación; `EMAIL_DRY_RUN=true` | Crear contraseña de aplicación; `EMAIL_DRY_RUN=false`; probar con `probar_correo` |
| Las fotos subidas desaparecen tras desplegar | `MEDIA_ROOT` no está en un disco persistente | Montar un volumen y apuntar `MEDIA_ROOT` ahí |
| Los productos no se actualizan desde Odoo | `ODOO_SYNC_MINUTOS=0` o datos `ODOO_*` incompletos | Completar los 4 datos y poner `ODOO_SYNC_MINUTOS=5`; probar `sincronizar_odoo --dry-run` |

Los errores se ven en los **logs** del hosting (gunicorn escribe en consola).

---

## 10. Estructura del código (referencia)

| Carpeta | Contenido |
|---|---|
| `config/` | Configuración de Django (`settings.py`, `urls.py`, `wsgi.py`) |
| `core/` | Datos del sitio, correo, middlewares de seguridad |
| `tienda/` | Productos, tienda, sincronización con Odoo |
| `paginas/` | Páginas informativas, contacto, SEO, redirecciones del sitio anterior (Wix) |
| `carrito/` | Carrito, checkout, envíos, pedidos, Mercado Pago, correos |
| `panel/` | Panel de gestión en `/panel` |
| `templates/` | Plantillas HTML generales |
| `static/` | CSS ya compilado, JavaScript e imágenes |
| `content/` | Textos en Markdown de productos, orígenes y nosotros |
