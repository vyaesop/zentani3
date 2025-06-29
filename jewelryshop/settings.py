from pathlib import Path

import os
import socket
import cloudinary_storage
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-3%y3laftm62q0zaj+s7#p-xqq9(&#q+)s8)p-&#&bz*0$!xu$0'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*']


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
    'cloudinary_storage'

]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

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


# DATABASE_URL = 'postgresql://zedb_owner:npg_jNIz92hOJGFY@ep-steep-hat-a9oq073s-pooler.gwc.azure.neon.tech/zedb?sslmode=require'

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'zedb',
#         'USER': 'zedb_owner',
#         'PASSWORD': 'npg_jNIz92hOJGFY',
#         'HOST': 'ep-steep-hat-a9oq073s-pooler.gwc.azure.neon.tech',
#         'PORT': 5432,
#         'OPTIONS': {
#             'sslmode': 'require',
#             # You might also need this if connecting to Neon or other cloud DBs
#             'sslrootcert': os.path.join(BASE_DIR, 'ssl', 'root.crt'),  # optional path to root cert
#         }
#     }
# }
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'railway',
        'USER':'postgres',
        'PASSWORD':'hCiUyBWsBsTmWKQutUnEeoMuDjqpvMAQ',
        'HOST':'caboose.proxy.rlwy.net',
        'PORT':'24537'
        
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

# Settings for Media
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': 'dzak0zcmt',
    'API_KEY': '813736585371732',
    'API_SECRET': 'bf0HW5o4hUDdPH9HH4-ioP-NJsg'
}

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
