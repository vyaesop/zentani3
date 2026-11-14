{% load static %}/* Zentanee service worker.
   - Static assets: cache-first. URLs carry ?v=<content hash>, so when a file
     changes the old copy for that path is dropped as the new one is stored.
   - Pages: network-first. Only public shopping pages are kept for offline use
     (never cart, checkout, orders, accounts or the dashboard), capped in size.
   - Offline: pages never visited fall back to a precached offline page.
   Bump CACHE_VERSION only to force-drop every cache (e.g. a caching bug). */
const CACHE_VERSION = "zentanee-v3";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const PAGE_CACHE = `${CACHE_VERSION}-pages`;
const OFFLINE_URL = "{% url 'store:offline' %}";
const PRECACHE = [OFFLINE_URL, "{% static 'asset/images/logo-mark-80.png' %}"];
const MAX_PAGES = 40;
const MAX_STATIC = 120;

// First path segments that are personal, transactional or internal. Pages
// under these are never stored, even though they are GET navigations.
const PRIVATE_ROOTS = new Set([
  "cart", "checkout", "orders", "accounts", "dashboard", "payments", "review",
  "ref", "admin", "internal", "telegram", "i18n", "wishlist", "add-coupon",
  "add-to-cart", "search", "offline",
]);

function isCacheablePage(url) {
  if (url.origin !== self.location.origin) return false;
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts.length === 0) return true; // home
  if (PRIVATE_ROOTS.has(parts[0])) return false;
  if (parts.length === 1) return true; // listings, collections, info pages
  // Product and brand pages, but not their sub-actions (review, restock).
  return parts.length === 2 && (parts[0] === "product" || parts[0] === "brand");
}

function isStorable(response) {
  if (!response || !response.ok || response.redirected || response.type !== "basic") return false;
  const cc = response.headers.get("Cache-Control") || "";
  return !/no-store|private/i.test(cc);
}

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - max; i++) await cache.delete(keys[i]);
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(PAGE_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .catch(() => { /* offline page is a nicety; never block the update */ })
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

async function staticFirst(request, url) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    // Drop older ?v= versions of the same file so the cache doesn't grow
    // with every deploy.
    const keys = await cache.keys();
    await Promise.all(
      keys
        .filter((key) => {
          const k = new URL(key.url);
          return k.pathname === url.pathname && k.search !== url.search;
        })
        .map((key) => cache.delete(key))
    );
    await cache.put(request, response.clone());
    trim(STATIC_CACHE, MAX_STATIC);
  }
  return response;
}

async function pageNetworkFirst(request, url) {
  try {
    const response = await fetch(request);
    if (isCacheablePage(url) && isStorable(response)) {
      const cache = await caches.open(PAGE_CACHE);
      const copy = response.clone();
      // Delete first so a refreshed page moves to the newest end for trimming.
      await cache.delete(request);
      await cache.put(request, copy);
      trim(PAGE_CACHE, MAX_PAGES + PRECACHE.length);
    }
    return response;
  } catch (err) {
    const cache = await caches.open(PAGE_CACHE);
    if (isCacheablePage(url)) {
      const cached = await cache.match(request);
      if (cached) return cached;
    }
    const offline = await cache.match(OFFLINE_URL);
    return offline || Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // Logging out: forget stored pages so they can't show the old account.
  // (Django 3.2 logs out on a GET link; a POST form would land here too.)
  if (url.origin === self.location.origin && url.pathname.startsWith("/accounts/logout")) {
    event.waitUntil(
      caches.delete(PAGE_CACHE)
        .then(() => caches.open(PAGE_CACHE))
        .then((cache) => cache.addAll(PRECACHE))
        .catch(() => {})
    );
    return;
  }

  if (request.method !== "GET") return;

  if (url.origin === self.location.origin && url.pathname.startsWith("/static/")) {
    event.respondWith(staticFirst(request, url));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(pageNetworkFirst(request, url));
  }
});
