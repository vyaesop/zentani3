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

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY') or os.getenv('SECRET_KEY') or 'django-insecure-3%y3laftm62q0zaj+s7#p-xqq9(&#q+)s8)p-&#&bz*0$!xu$0'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

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


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'store',

]

if importlib.util.find_spec('cloudinary_storage'):
    INSTALLED_APPS.append('cloudinary_storage')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

if importlib.util.find_spec('whitenoise'):
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'jewelryshop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'store.context_preprocessors.store_menu',
                'store.context_preprocessors.brand_menu',
                'store.context_preprocessors.cart_menu',
            ],
        },
    },
]

WSGI_APPLICATION = 'jewelryshop.wsgi.application'

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }


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
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'postgres',  # Supabase DB name
#         'USER': 'postgres',
#         'PASSWORD': 'x9KpmtFXiPIWg92f',
#         'HOST': 'db.hndfdrhwatomdlqnnthz.supabase.co',  # or from Supabase host setting
#         'PORT': 5432,
#         'OPTIONS': {
#             'sslmode': 'require',
#             # Optional: if Supabase gives a root cert
#             # 'sslrootcert': os.path.join(BASE_DIR, 'ssl', 'supabase_root.crt'),
#         },
#     }
# }
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'railway',
#         'USER':'postgres',
#         'PASSWORD':'hCiUyBWsBsTmWKQutUnEeoMuDjqpvMAQ',
#         'HOST':'caboose.proxy.rlwy.net',
#         'PORT':'24537'
        
#     }
# }

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

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Europe/Moscow'

USE_I18N = True

USE_TZ = False


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'jewelryshop/static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles', 'static') # Automatically Created on Production

if importlib.util.find_spec('whitenoise'):
    # Use non-manifest storage to avoid build failures when vendor CSS contains
    # unresolved relative references that are not shipped in this project.
    STATICFILES_STORAGE = 'whitenoise.storage.CompressedStaticFilesStorage'

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

# Default cache backend powers menu caching and can be replaced by Redis in production.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'zent-cache',
        'TIMEOUT': 300,
    }
}

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
