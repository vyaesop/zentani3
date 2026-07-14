"""Catalog cache versioning and key helpers.

Fragment and collection-metadata caches embed a site-wide "catalog version" in
their keys. Bumping the version on any Product/Category/Brand change makes all
stale entries unreachable at once — no per-key invalidation bookkeeping.
"""
import hashlib

from django.core.cache import cache

CATALOG_VERSION_KEY = "catalog_version"
MENU_CATEGORY_CACHE_KEY = "store_menu_categories"
MENU_BRAND_CACHE_KEY = "store_menu_brands"

COLLECTION_META_TTL = 60 * 10
HOME_TOP_SELLING_TTL = 60 * 10


def catalog_version():
    version = cache.get(CATALOG_VERSION_KEY)
    if version is None:
        version = 1
        cache.add(CATALOG_VERSION_KEY, version, None)
    return version


def bump_catalog_version():
    try:
        cache.incr(CATALOG_VERSION_KEY)
    except ValueError:
        cache.set(CATALOG_VERSION_KEY, 2, None)


def invalidate_menus():
    cache.delete_many([MENU_CATEGORY_CACHE_KEY, MENU_BRAND_CACHE_KEY])


def collection_meta_key(path, query_text):
    raw = f"{path}|{(query_text or '').strip().casefold()}"
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"collection-meta:{catalog_version()}:{digest}"
