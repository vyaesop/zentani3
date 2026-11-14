/* Zentanee storefront behaviour (vanilla, no jQuery).
   - mobile drawer open/close
   - search suggestion dismissal
   - quick-add toast lifecycle
   - copy-to-clipboard buttons
   - sticky mobile add-to-cart bar on product pages
   - GA4 ecommerce events (view_item, add_to_cart, begin_checkout, purchase) */
(function () {
  'use strict';

  function track(eventName, params) {
    if (typeof window.gtag !== 'function') return;
    try { window.gtag('event', eventName, params || {}); } catch (e) { /* analytics must never break the page */ }
  }

  function readJson(id) {
    var node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent || '{}'); } catch (e) { return null; }
  }

  /* ── Mobile drawer ─────────────────────────────────────────────── */
  var drawer = document.getElementById('mobile-menu');
  var toggles = document.querySelectorAll('.mobile-menu-toggle');

  function setDrawer(open) {
    if (!drawer) return;
    document.body.classList.toggle('mmenu-active', open);
    drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
    toggles.forEach(function (btn) { btn.setAttribute('aria-expanded', open ? 'true' : 'false'); });
    if (open) {
      var firstInput = drawer.querySelector('input, a, button');
      if (firstInput) firstInput.focus();
    }
  }

  toggles.forEach(function (btn) {
    btn.addEventListener('click', function () { setDrawer(!document.body.classList.contains('mmenu-active')); });
  });
  if (drawer) {
    drawer.querySelectorAll('.mobile-menu-overlay, .mobile-menu-close').forEach(function (el) {
      el.addEventListener('click', function () { setDrawer(false); });
    });
  }

  /* ── Search suggestions + drawer + lightbox escape handling ───── */
  document.addEventListener('click', function (e) {
    document.querySelectorAll('.zent-search-suggest').forEach(function (panel) {
      var wrap = panel.closest('.zent-search');
      if (wrap && !wrap.contains(e.target)) panel.innerHTML = '';
    });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') return;
    document.querySelectorAll('.zent-search-suggest').forEach(function (panel) { panel.innerHTML = ''; });
    if (document.body.classList.contains('mmenu-active')) setDrawer(false);
  });

  /* ── Quick-add toast ───────────────────────────────────────────── */
  document.body.addEventListener('htmx:afterSwap', function (e) {
    var toast = document.getElementById('zent-toast');
    if (toast && e.target === toast && toast.innerHTML.trim()) {
      clearTimeout(toast._hideTimer);
      toast.classList.add('is-visible');
      toast._hideTimer = setTimeout(function () {
        toast.classList.remove('is-visible');
        toast.innerHTML = '';
      }, 3500);
    }
  });

  /* ── Copy buttons (referral links) ─────────────────────────────── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-copy-target]');
    if (!btn) return;
    var input = document.getElementById(btn.getAttribute('data-copy-target'));
    if (!input) return;
    var original = btn.textContent;
    var done = function () {
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = original; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(input.value).then(done, function () {
        input.select(); document.execCommand('copy'); done();
      });
    } else {
      input.select(); document.execCommand('copy'); done();
    }
  });

  /* ── Sticky add-to-cart bar (mobile PDP) ───────────────────────── */
  var stickyBar = document.querySelector('[data-sticky-cta]');
  var mainButton = document.getElementById('add-to-cart-btn');
  var productForm = document.getElementById('product-add-to-cart-form');
  if (stickyBar && mainButton && productForm && 'IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var passed = !entry.isIntersecting && entry.boundingClientRect.top < 0;
        stickyBar.hidden = !passed;
        document.body.classList.toggle('has-sticky-cta', passed);
      });
    }, { threshold: 0 });
    observer.observe(mainButton);
    var submit = stickyBar.querySelector('[data-sticky-cta-submit]');
    if (submit) {
      submit.addEventListener('click', function () {
        if (productForm.requestSubmit) productForm.requestSubmit(); else productForm.submit();
        mainButton.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
  }

  /* ── Collection filters: open as a column on wide viewports ─────── */
  var wide = window.matchMedia('(min-width: 1024px)');
  function syncFilters() {
    document.querySelectorAll('details.zh-filters').forEach(function (d) { if (wide.matches) d.open = true; });
  }
  syncFilters();
  if (wide.addEventListener) wide.addEventListener('change', syncFilters);
  document.body.addEventListener('htmx:afterSettle', syncFilters);

  /* ── Install card (PWA) ────────────────────────────────────────── *
   * Shown only to engaged shoppers: after 2+ product views, or straight after
   * an order. Android/desktop Chrome get the native prompt behind "Install";
   * iPhone has no prompt API, so it gets the Share -> Add to Home Screen steps.
   * First "not now" hides it until their next visit (a new browser session);
   * every later "not now" hides it for 7 days. Never shown inside the installed app,
   * in in-app browsers (Telegram, Facebook, Instagram, TikTok can't install),
   * or on pages with their own bottom bar (product, cart, checkout). */
  (function installCard() {
    var card = document.getElementById('zh-install');
    if (!card) return;
    var KEY_VIEWS = 'zh-pdp-views';
    var KEY_DISMISSALS = 'zh-install-dismissals';   // how many times they said "not now"
    var KEY_SNOOZE = 'zh-install-snooze';           // when they last said it (ms)
    var KEY_SESSION = 'zh-install-hidden';          // sessionStorage: dismissed this visit
    var SNOOZE_MS = 7 * 24 * 60 * 60 * 1000;
    var route = document.body.getAttribute('data-zh-route') || '';
    var ua = navigator.userAgent || '';
    var deferred = null;

    // Web storage can throw (private mode, blocked storage); the card just
    // behaves as if nothing was stored.
    function store(key, value, area) {
      try {
        var s = window[area || 'localStorage'];
        if (value === undefined) return s.getItem(key);
        s.setItem(key, value);
      } catch (e) { /* ignore */ }
      return null;
    }
    function num(key) { return parseInt(store(key), 10) || 0; }

    var standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true;
    if (standalone) return;
    if (/FBAN|FBAV|Instagram|Telegram|TikTok|musical_ly|Line\//i.test(ua)) return;

    var isIos = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    var isPdp = !!document.getElementById('ga-view-item-data');
    var justOrdered = !!document.getElementById('ga-purchase-data');

    if (isPdp) store(KEY_VIEWS, String(num(KEY_VIEWS) + 1));

    function eligible() {
      if (store(KEY_SESSION, undefined, 'sessionStorage')) return false;
      if (num(KEY_DISMISSALS) >= 2 && Date.now() - num(KEY_SNOOZE) < SNOOZE_MS) return false;
      if (justOrdered) return true;
      if (isPdp || route === 'cart' || route === 'checkout') return false;
      return num(KEY_VIEWS) >= 2;
    }

    function show(mode) {
      if (!card.hidden || !eligible()) return;
      card.querySelectorAll('[data-install-mode]').forEach(function (el) {
        el.hidden = el.getAttribute('data-install-mode') !== mode;
      });
      card.hidden = false;
      track('pwa_install_card', { mode: mode });
    }

    function hide(snooze) {
      card.hidden = true;
      if (!snooze) return;
      store(KEY_SESSION, '1', 'sessionStorage');
      store(KEY_DISMISSALS, String(num(KEY_DISMISSALS) + 1));
      store(KEY_SNOOZE, String(Date.now()));
    }

    window.addEventListener('beforeinstallprompt', function (e) {
      e.preventDefault();
      deferred = e;
      show('prompt');
    });

    window.addEventListener('appinstalled', function () {
      hide(false);
      deferred = null;
      track('pwa_installed', {});
    });

    var accept = card.querySelector('[data-install-accept]');
    if (accept) {
      accept.addEventListener('click', function () {
        if (!deferred) { hide(true); return; }
        deferred.prompt();
        deferred.userChoice.then(function (choice) {
          track('pwa_install_choice', { outcome: choice && choice.outcome });
          hide(!choice || choice.outcome !== 'accepted');
        });
        deferred = null;
      });
    }

    var dismiss = card.querySelector('[data-install-dismiss]');
    if (dismiss) dismiss.addEventListener('click', function () { hide(true); });

    if (isIos) setTimeout(function () { show('ios'); }, 1500);
  })();

  /* ── GA4 ecommerce ─────────────────────────────────────────────── */
  var viewItem = readJson('ga-view-item-data');
  if (viewItem) track('view_item', { currency: 'ETB', value: viewItem.price || 0, items: [viewItem] });

  document.body.addEventListener('zent:add_to_cart', function (e) {
    if (e.detail) track('add_to_cart', e.detail);
  });

  var checkoutForm = document.getElementById('checkout-form');
  if (checkoutForm) {
    checkoutForm.addEventListener('submit', function () {
      var cart = readJson(checkoutForm.getAttribute('data-ga-checkout'));
      if (cart) track('begin_checkout', cart);
    });
  }

  var purchase = readJson('ga-purchase-data');
  if (purchase) track('purchase', purchase);
})();
