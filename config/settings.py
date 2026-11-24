"""Configuración de Django — Viati Café.

Todas las claves y datos sensibles se leen de variables de entorno (archivo .env
en desarrollo). Ver .env.example para la lista completa.
"""

import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-inseguro-cambiar-en-produccion")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# URL pública del sitio (con https y sin "/" final). Se usa para armar las URLs
# que reciben servicios externos (webhook y retorno de Mercado Pago, correos).
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    "core",
    "tienda",
    "paginas",
    "carrito",
    "panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.RemoveTrailingSlashMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.sitio",
                "carrito.context_processors.carrito",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Base de datos: SQLite en desarrollo; en producción definir DATABASE_URL
# (PostgreSQL, ej: postgres://usuario:clave@host:5432/viati).
DATABASES = {
    "default": dj_database_url.parse(
        os.getenv("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
# Fotos subidas desde el panel. En producción apúntala a un disco persistente
# (p. ej. un "Volume" de Railway montado en /data → MEDIA_ROOT=/data/media).
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT") or BASE_DIR / "media")
# true = Django sirve /media/ también en producción (sitio pequeño con disco propio).
SERVE_MEDIA = env_bool("SERVE_MEDIA", DEBUG)
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Carpeta con el contenido Markdown (productos, orígenes, nosotros).
CONTENT_DIR = BASE_DIR / "content"

# ── Integraciones ──
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Viati Café <noreply@notificaciones.viaticafe.com>")
EMAIL_GERENCIA = os.getenv("EMAIL_GERENCIA", "gerencia@agroambientec.com")
# En desarrollo, true = no enviar correos reales (se guardan en tmp_emails/).
EMAIL_DRY_RUN = env_bool("EMAIL_DRY_RUN", DEBUG)
# Proveedor de correo: "smtp" (Gmail / Google Workspace) o "resend".
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend").strip().lower()
# SMTP de Google Workspace: EMAIL_HOST_PASSWORD es una CONTRASEÑA DE APLICACIÓN
# (16 letras), no la contraseña normal de la cuenta. EMAIL_FROM debe usar la
# misma cuenta (o un alias verificado en Gmail), si no Gmail cambia el remitente.
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "").replace(" ", "")
EMAIL_TIMEOUT = 20

MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
# Clave secreta de firma de webhooks (panel de Mercado Pago → Webhooks). Opcional
# pero recomendada: si está definida se valida la cabecera x-signature.
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")

GA_MEASUREMENT_ID = os.getenv("GA_MEASUREMENT_ID", "")

ODOO_URL = os.getenv("ODOO_URL", "").rstrip("/")
ODOO_DB = os.getenv("ODOO_DB", "")
ODOO_USER = os.getenv("ODOO_USER", "")
ODOO_API_KEY = os.getenv("ODOO_API_KEY", "")
ODOO_PRICELIST = os.getenv("ODOO_PRICELIST", "Precios Web")
# Sincronización automática del catálogo (como el revalidate de Next.js): cada
# cuántos minutos se vuelve a leer Odoo al visitar la tienda. 0 = apagada.
ODOO_SYNC_MINUTOS = max(0, int(os.getenv("ODOO_SYNC_MINUTOS") or 0))
# true = ocultar también los productos que no vienen de Odoo.
ODOO_SYNC_SOLO_ODOO = env_bool("ODOO_SYNC_SOLO_ODOO", False)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Redirige http → https (el proxy del hosting avisa con X-Forwarded-Proto).
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    # HSTS: el navegador recordará usar solo https. Empezar en 0 y subir (ej. 31536000)
    # cuando el dominio funcione bien con https.
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_HSTS_SECONDS") or 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False

# Caché: en producción se guarda en la base de datos para que el bloqueo de
# intentos de login y los límites funcionen igual en todos los procesos del
# servidor. Requiere una vez: python manage.py createcachetable
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    if DEBUG
    else {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache_viati"}
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
