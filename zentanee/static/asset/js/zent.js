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
