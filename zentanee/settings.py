from pathlib import Path

import os
import importlib.util
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from project-level .env for local/dev usage.
load_dotenv(BASE_DIR / '.env')


def _env_bool(name, default):
    raw = os.getenv(name)
    if raw is None or raw.strip() == '':
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _env_int(name, default):
    try:
        return int(os.getenv(name, '') or default)
    except (TypeError, ValueError):
        return default


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or os.getenv('SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY (or SECRET_KEY) must be set when DEBUG is off.')
    # Development-only fallback; never used in production.
    SECRET_KEY = 'django-insecure-dev-only-key'

ALLOWED_HOSTS = [h.strip() for h in os.getenv('ALLOWED_HOSTS', '*').split(',') if h.strip()]
SITE_URL = os.getenv('SITE_URL', '').rstrip('/')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '').strip()
GEMINI_PRODUCT_MODEL = os.getenv('GEMINI_PRODUCT_MODEL', 'gemini-2.5-flash').strip() or 'gemini-2.5-flash'
GEMINI_PRODUCT_FALLBACK_MODEL = os.getenv('GEMINI_PRODUCT_FALLBACK_MODEL', 'gemini-2.5-flash-lite').strip()
AI_IMAGE_GENERATOR_ENDPOINT = os.getenv('AI_IMAGE_GENERATOR_ENDPOINT', '').strip()
AI_IMAGE_GENERATOR_TOKEN = os.getenv('AI_IMAGE_GENERATOR_TOKEN', '').strip()
AI_IMAGE_GENERATOR_TIMEOUT = int(os.getenv('AI_IMAGE_GENERATOR_TIMEOUT', '300'))
AI_IMAGE_GENERATOR_RETRIES = int(os.getenv('AI_IMAGE_GENERATOR_RETRIES', '2'))
AI_IMAGE_GENERATOR_SHOTS_PER_REQUEST = int(os.getenv('AI_IMAGE_GENERATOR_SHOTS_PER_REQUEST', '1'))
AI_IMAGE_GENERATOR_FALLBACK_TO_LOCAL = os.getenv('AI_IMAGE_GENERATOR_FALLBACK_TO_LOCAL', 'False').lower() == 'true'

# Conservative AI taxonomy: auto-create a collection/brand only when Gemini says
# nothing existing fits AND is highly confident. Flip off to require manual picks.
AI_AUTO_CREATE_COLLECTIONS = os.getenv('AI_AUTO_CREATE_COLLECTIONS', 'True').lower() == 'true'
AI_AUTO_CREATE_BRANDS = os.getenv('AI_AUTO_CREATE_BRANDS', 'True').lower() == 'true'

# Store-wide policy copy shown on product pages when a product has no override.
# Returns are on-the-spot only: the customer inspects the item with the delivery
# driver present and can only hand it back before the driver leaves.
STORE_DELIVERY_NOTE = os.getenv(
    'STORE_DELIVERY_NOTE',
    'Delivery in Addis Ababa usually lands within 1-3 days after confirmation. Pay cash on delivery.',
)
STORE_RETURN_NOTE = os.getenv(
    'STORE_RETURN_NOTE',
    'Check your item with the delivery driver present — returns are accepted only on the spot, before the driver leaves.',
)

# ── Store identity (footer, policy pages, schema.org Organization) ────────────
# Fill these in the environment so the storefront can name the business behind
# the cash-on-delivery driver. Empty values are simply not rendered.
STORE_NAME = os.getenv('STORE_NAME', 'Zentanee').strip() or 'Zentanee'
STORE_LEGAL_NAME = os.getenv('STORE_LEGAL_NAME', '').strip()
STORE_PHONE = os.getenv('STORE_PHONE', '+251933392463').strip()
STORE_EMAIL = os.getenv('STORE_EMAIL', '').strip()
STORE_ADDRESS = os.getenv('STORE_ADDRESS', 'Addis Ababa, Ethiopia').strip()
STORE_TRADE_LICENSE = os.getenv('STORE_TRADE_LICENSE', '').strip()
STORE_TIN = os.getenv('STORE_TIN', '').strip()
STORE_INSTAGRAM_URL = os.getenv('STORE_INSTAGRAM_URL', 'https://instagram.com/zentanee').strip()
STORE_SUPPORT_HOURS = os.getenv('STORE_SUPPORT_HOURS', 'Monday to Saturday, 9:00 to 18:00').strip()

# Stock messaging. The catalog is largely order-on-demand, so by default the
# storefront talks about availability ("In stock", "Sold out") instead of
# inventing unit counts. Flip on once counts are real and maintained.
STORE_SHOW_STOCK_COUNTS = _env_bool('STORE_SHOW_STOCK_COUNTS', False)
# Units assigned to a newly added size when no count is entered. Set to 0 to
# force staff to enter real counts (a size with 0 units reads as sold out).
INVENTORY_DEFAULT_STOCK_PER_SIZE = _env_int('DEFAULT_STOCK_PER_SIZE', 10)

# Analytics. Empty string disables the GA4 snippet entirely.
GA_MEASUREMENT_ID = os.getenv('GA_MEASUREMENT_ID', 'G-PMSGT50Q4W').strip()

# A coupon code applied automatically to carts that arrived through an
# affiliate /ref/ link (the referred shopper's welcome discount).
REFERRAL_WELCOME_COUPON_CODE = os.getenv('REFERRAL_WELCOME_COUPON_CODE', '').strip()

# Brute-force guard for login/registration (per IP and per phone number).
LOGIN_RATE_LIMIT_ATTEMPTS = _env_int('LOGIN_RATE_LIMIT_ATTEMPTS', 10)
LOGIN_RATE_LIMIT_WINDOW_SECONDS = _env_int('LOGIN_RATE_LIMIT_WINDOW_SECONDS', 15 * 60)


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.contrib.sitemaps',
    'store',

]

if importlib.util.find_spec('cloudinary_storage'):
    INSTALLED_APPS.append('cloudinary_storage')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'store.middleware.ContentSecurityPolicyMiddleware',
]

if importlib.util.find_spec('whitenoise'):
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'zentanee.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_preprocessors.store_menu',
                'store.context_preprocessors.brand_menu',
                'store.context_preprocessors.cart_menu',
                'store.context_preprocessors.cache_versions',
                'store.context_preprocessors.merch_badges',
                'store.context_preprocessors.store_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'zentanee.wsgi.application'

DATABASE_URL = os.getenv('DATABASE_URL')
IS_VERCEL = os.getenv('VERCEL') == '1'

if DATABASE_URL:
    # Use managed DB URL in production/serverless environments.
    database_config = dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    if database_config.get('ENGINE') != 'django.db.backends.sqlite3':
        database_config.setdefault('OPTIONS', {})
        database_config['OPTIONS']['sslmode'] = 'require'
    DATABASES = {
        'default': database_config
    }
else:
    if IS_VERCEL or not DEBUG:
        raise ImproperlyConfigured('DATABASE_URL is required in production/serverless environments.')

    # Local development fallback only.
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

AUTHENTICATION_BACKENDS = [
    'store.backends.UsernameOrEmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]


# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = 'en'

LANGUAGES = [
    ('en', 'English'),
    ('am', 'አማርኛ'),
]

LOCALE_PATHS = [os.path.join(BASE_DIR, 'locale')]

TIME_ZONE = 'Africa/Addis_Ababa'

USE_I18N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'zentanee/static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles', 'static') # Automatically Created on Production

# Content-hash query strings on every static URL (see
# zentanee.staticfiles_storage) so vercel.json can serve /static/ with a
# one-year immutable Cache-Control header without stale assets. The storage
# compresses via whitenoise when it is installed and degrades to plain
# StaticFilesStorage otherwise, so it is safe to set unconditionally.
STATICFILES_STORAGE = 'zentanee.staticfiles_storage.VersionedCompressedStaticFilesStorage'

# Settings for Media
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


def _is_placeholder_secret(value):
    return value.strip().lower() in {
        'untitled',
        'changeme',
        'your-cloud-name',
        'your-api-key',
        'your-api-secret',
        'none',
        'null',
    }


CLOUDINARY_STORAGE = {
    'CLOUD_NAME': os.getenv('CLOUDINARY_CLOUD_NAME', ''),
    'API_KEY': os.getenv('CLOUDINARY_API_KEY', ''),
    'API_SECRET': os.getenv('CLOUDINARY_API_SECRET', ''),
}

CLOUDINARY_BACKEND_AVAILABLE = importlib.util.find_spec('cloudinary_storage') is not None
HAS_VALID_CLOUDINARY_CONFIG = all(
    value and not _is_placeholder_secret(value)
    for value in CLOUDINARY_STORAGE.values()
)

if HAS_VALID_CLOUDINARY_CONFIG:
    if not CLOUDINARY_BACKEND_AVAILABLE:
        raise ImproperlyConfigured(
            'cloudinary_storage package is required when Cloudinary env vars are configured.'
        )
    DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Shared cache backend. On serverless/multi-process hosting LocMem caches almost
# nothing, so production should always set REDIS_URL (e.g. Upstash on Vercel).
REDIS_URL = os.getenv('REDIS_URL', '').strip()
if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'TIMEOUT': 300,
        }
    }
    # Sessions read from cache, write through to the DB.
    SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
else:
    # Local development fallback (per-process).
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'zent-cache',
            'TIMEOUT': 300,
        }
    }

# Dev-only query debugging: `pip install django-debug-toolbar` and run with DEBUG=true.
if DEBUG and importlib.util.find_spec('debug_toolbar'):
    INSTALLED_APPS.append('debug_toolbar')
    MIDDLEWARE.insert(0, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    INTERNAL_IPS = ['127.0.0.1', 'localhost']

# Background task queue (store.tasks). Eager mode executes handlers inline at
# enqueue time — used in DEBUG/tests so local flows stay synchronous.
TASKS_EAGER = os.getenv('TASKS_EAGER', str(DEBUG)).lower() == 'true'

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Email ────────────────────────────────────────────────────────────────────
# Any SMTP provider works (Resend, Postmark, SES, Brevo all expose SMTP). When
# EMAIL_HOST is unset the console backend is used and store.checks warns in
# production, because password reset and order emails would silently go nowhere.
EMAIL_HOST = os.getenv('EMAIL_HOST', '').strip()
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = _env_int('EMAIL_PORT', 587)
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
    EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', EMAIL_PORT == 587)
    EMAIL_USE_SSL = _env_bool('EMAIL_USE_SSL', EMAIL_PORT == 465)
    EMAIL_TIMEOUT = _env_int('EMAIL_TIMEOUT', 10)
else:
    EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', STORE_EMAIL or 'no-reply@zentanee.local')
SERVER_EMAIL = os.getenv('SERVER_EMAIL', DEFAULT_FROM_EMAIL)

# ── SMS ──────────────────────────────────────────────────────────────────────
# Every cash-on-delivery customer gives a phone number, so SMS is the default
# order-confirmation channel. Backends: disabled | console | afromessage | http.
SMS_BACKEND = os.getenv('SMS_BACKEND', 'console' if DEBUG else 'disabled').strip().lower()
SMS_SENDER_ID = os.getenv('SMS_SENDER_ID', STORE_NAME).strip()
AFROMESSAGE_TOKEN = os.getenv('AFROMESSAGE_TOKEN', '').strip()
AFROMESSAGE_IDENTIFIER_ID = os.getenv('AFROMESSAGE_IDENTIFIER_ID', '').strip()
AFROMESSAGE_API_URL = os.getenv('AFROMESSAGE_API_URL', 'https://api.afromessage.com/api/send').strip()
# Generic HTTP gateway: POST JSON to SMS_HTTP_URL. Body/headers are JSON
# templates where {to}, {message} and {sender} are substituted.
SMS_HTTP_URL = os.getenv('SMS_HTTP_URL', '').strip()
SMS_HTTP_HEADERS = os.getenv('SMS_HTTP_HEADERS', '{}')
SMS_HTTP_BODY = os.getenv('SMS_HTTP_BODY', '{"to": "{to}", "message": "{message}", "from": "{sender}"}')
# Order statuses that trigger an SMS to the customer (confirmation always sends).
SMS_STATUS_NOTIFY_STATUSES = [
    value.strip() for value in os.getenv('SMS_STATUS_NOTIFY_STATUSES', 'On The Way').split(',') if value.strip()
]

# ── Online payment (optional, cash on delivery stays the default) ────────────
# Chapa aggregates Telebirr, CBE Birr, M-Pesa and cards behind one hosted
# checkout. Leave CHAPA_SECRET_KEY empty to keep the store COD-only.
CHAPA_SECRET_KEY = os.getenv('CHAPA_SECRET_KEY', '').strip()
CHAPA_WEBHOOK_SECRET = os.getenv('CHAPA_WEBHOOK_SECRET', '').strip()
CHAPA_API_BASE_URL = os.getenv('CHAPA_API_BASE_URL', 'https://api.chapa.co/v1').rstrip('/')
ONLINE_PAYMENTS_ENABLED = bool(CHAPA_SECRET_KEY)

# ── Security hardening ───────────────────────────────────────────────────────
# TLS terminates at the platform edge (Vercel / Railway), which forwards the
# original scheme in X-Forwarded-Proto.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = _env_bool('SECURE_SSL_REDIRECT', not DEBUG)
SESSION_COOKIE_SECURE = _env_bool('SESSION_COOKIE_SECURE', not DEBUG)
CSRF_COOKIE_SECURE = _env_bool('CSRF_COOKIE_SECURE', not DEBUG)
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# HSTS is emitted by the hosting edge already; set SECURE_HSTS_SECONDS when
# self-hosting so Django sends it instead.
SECURE_HSTS_SECONDS = _env_int('SECURE_HSTS_SECONDS', 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

# Content-Security-Policy emitted by store.middleware. Inline scripts remain
# allowed because the GA snippet and per-page scripts are inline; external
# script hosts are still locked down. Set CSP_REPORT_ONLY=true to trial changes.
CONTENT_SECURITY_POLICY = os.getenv('CONTENT_SECURITY_POLICY', '').strip() or "; ".join([
    "default-src 'self'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    "form-action 'self' https://checkout.chapa.co https://api.chapa.co",
    "object-src 'none'",
    "script-src 'self' 'unsafe-inline' https://www.googletagmanager.com https://www.google-analytics.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",
    "connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://*.google-analytics.com https://www.googletagmanager.com",
    "manifest-src 'self'",
    "worker-src 'self'",
])
CSP_REPORT_ONLY = _env_bool('CSP_REPORT_ONLY', False)
