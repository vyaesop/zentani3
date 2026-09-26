/* Zentanee motion: cloth on the loom.
   Lenis smooths wheel scrolling, GSAP + ScrollTrigger run the choreography,
   Vanta NET draws loose indigo threads behind the homepage hero on capable
   desktops. All of it is progressive: without this file, or under
   prefers-reduced-motion, every page is complete and static.
   - homepage hero: the band weaves in, the headline rises out of its line
     masks, the emphasised word's thread pulls taut, the three swatches are
     laid down like cut cloth and their price tags slide out from under them
   - scroll: every thin band weaves in as it arrives, its heading rises from
     under it; product modules, steps and collection rows arrive as lists
   - hero swatch photos lift off their woven under-strips while scrolling
   - inner pages: the page heading rises once on load
   The inline script in base.html adds html.zh-motion before first paint so
   the hero can start hidden; it removes the class if this file never runs. */
(function () {
  'use strict';

  var root = document.documentElement;
  var gsap = window.gsap;
  var ST = window.ScrollTrigger;
  var Split = window.SplitText;

  if (!gsap || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    root.classList.remove('zh-motion');
    return;
  }
  /* The head script only arms the entrances on a fast link; if it already
     gave up waiting for this file, the hero is showing and must stay put. */
  var introAllowed = root.classList.contains('zh-motion');
  window.__zhMotion = true;
  if (ST) gsap.registerPlugin(ST);
  if (Split) gsap.registerPlugin(Split);

  var EASE = 'expo.out'; /* the world ease, cubic-bezier(0.16, 1, 0.3, 1) */
  var WEAVE_FROM = 'inset(0% 100% 0% 0%)';
  var WEAVE_TO = 'inset(0% 0% 0% 0%)';

  function ready() { root.classList.add('zh-motion-ready'); }

  /* Fonts decide where lines break; wait for them, but never for long. */
  function fontsReady(maxMs) {
    return new Promise(function (resolve) {
      var done = false;
      var finish = function () { if (!done) { done = true; resolve(); } };
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(finish, finish);
      else finish();
      setTimeout(finish, maxMs);
    });
  }

  function splitLines(el) {
    if (!Split || !el) return null;
    return Split.create(el, { type: 'lines', mask: 'lines', linesClass: 'zh-sline', aria: 'auto' });
  }

  /* ── Lenis: smooth wheel scrolling, driven by the GSAP ticker ─────── */
  var lenis = null;
  if (window.Lenis) {
    lenis = new window.Lenis({
      lerp: 0.1,
      wheelMultiplier: 1,
      autoRaf: false,
      prevent: function (node) {
        return !!(node && node.closest && node.closest('.zh-drawer, .zent-search-suggest, .zh-pdp__lightbox, [data-lenis-prevent]'));
      }
    });
    gsap.ticker.add(function (time) { lenis.raf(time * 1000); });
    gsap.ticker.lagSmoothing(0);
    if (ST) lenis.on('scroll', ST.update);
    window.zentLenis = lenis;

    /* The drawer and the product lightbox lock the body; hold Lenis with them. */
    var body = document.body;
    var syncLock = function () {
      var locked = body.classList.contains('mmenu-active') || body.style.overflow === 'hidden';
      if (locked) lenis.stop(); else lenis.start();
    };
    new MutationObserver(syncLock).observe(body, { attributes: true, attributeFilter: ['class', 'style'] });
  }

  /* ── Homepage hero: the one authored entrance ─────────────────────── */
  function heroIntro() {
    var hero = document.querySelector('.zh-hero');
    if (!hero) return null;

    var tile = hero.querySelector('.zh-band--weave .zh-band__tile');
    var h1 = hero.querySelector('h1');
    var swatches = gsap.utils.toArray(hero.querySelectorAll('.zh-swatch'));
    var labels = gsap.utils.toArray(hero.querySelectorAll('.zh-swatch__label'));
    var extras = gsap.utils.toArray(hero.querySelectorAll('.zh-swatches__caption, .zh-swatches--empty'));
    var bodyBits = gsap.utils.toArray(hero.querySelectorAll('.zh-truth, .zh-actions > *, .zh-ruler > li'));
    var split = splitLines(h1);
    var tilts = [-5, 4, -3];

    var tl = gsap.timeline({
      defaults: { ease: EASE },
      onComplete: function () {
        if (split) split.revert();
        gsap.set(swatches, { clearProps: 'transform,opacity,visibility' });
        gsap.set(labels.concat(bodyBits, extras), { clearProps: 'all' });
        if (tile) gsap.set(tile, { clearProps: 'clipPath' });
      }
    });

    if (tile) tl.fromTo(tile, { clipPath: WEAVE_FROM }, { clipPath: WEAVE_TO, duration: 1.2 }, 0);

    if (split && split.lines.length) {
      tl.fromTo(split.lines, { yPercent: 125 }, { yPercent: 0, duration: 0.95, stagger: 0.09 }, 0.2);
    } else if (h1) {
      tl.fromTo(h1, { autoAlpha: 0, y: 18 }, { autoAlpha: 1, y: 0, duration: 0.8 }, 0.2);
    }

    /* The indigo thread under the emphasised word pulls taut after the line lands. */
    var ems = h1 ? h1.querySelectorAll('em') : [];
    if (ems.length) {
      tl.fromTo(ems,
        { textDecorationColor: 'rgba(31, 58, 147, 0)', textUnderlineOffset: '0.42em' },
        { textDecorationColor: 'rgba(31, 58, 147, 1)', textUnderlineOffset: '0.14em', duration: 0.9, ease: 'power3.out',
          clearProps: 'textDecorationColor,textUnderlineOffset' },
        0.85);
    }

    /* Cut cloth laid down: each swatch drops, straightens and settles. */
    if (swatches.length) {
      tl.fromTo(swatches,
        { autoAlpha: 0, yPercent: -14, scale: 1.04, rotation: function (i) { return tilts[i % tilts.length]; } },
        { autoAlpha: 1, yPercent: 0, scale: 1, rotation: 0, duration: 1.05, stagger: 0.12 },
        0.4);
      tl.fromTo(labels, { clipPath: 'inset(0% 0% 0% 100%)' }, { clipPath: 'inset(0% 0% 0% 0%)', duration: 0.6, stagger: 0.12 }, 1.1);
    }
    if (extras.length) tl.fromTo(extras, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.6 }, 1.2);

    if (bodyBits.length) {
      tl.fromTo(bodyBits, { autoAlpha: 0, y: 16 }, { autoAlpha: 1, y: 0, duration: 0.8, stagger: 0.05 }, 0.6);
    }
    return tl;
  }

  /* ── Inner pages: the page heading rises once ─────────────────────── */
  function pageHeadIntro() {
    var h1 = document.querySelector('.zh-page__head h1');
    if (!h1 || document.querySelector('.zh-hero')) return;
    var split = splitLines(h1);
    if (split && split.lines.length) {
      gsap.fromTo(split.lines, { yPercent: 125 }, {
        yPercent: 0, duration: 0.85, ease: EASE, stagger: 0.08, delay: 0.1,
        onComplete: function () { split.revert(); }
      });
    }
  }

  /* ── Scroll: bands weave, headings rise, lists arrive ─────────────── */
  function belowFold(el) { return el.getBoundingClientRect().top > window.innerHeight * 0.96; }

  function scrollWeaves() {
    if (!ST) return;

    /* Every band but the hero's weaves in left to right. Those already on
       screen (the header band) weave on load. */
    gsap.utils.toArray('.zh-band:not(.zh-band--weave) > .zh-band__tile').forEach(function (tile) {
      gsap.fromTo(tile, { clipPath: WEAVE_FROM }, {
        clipPath: WEAVE_TO, duration: 1.1, ease: EASE, clearProps: 'clipPath',
        scrollTrigger: { trigger: tile, start: 'top 94%', once: true }
      });
    });

    /* A section's heading rises out from under its band. */
    gsap.utils.toArray('.zh-section__head').forEach(function (head) {
      if (!belowFold(head)) return;
      var h2 = head.querySelector('h2');
      var rest = Array.prototype.filter.call(head.children, function (c) { return c !== h2; });
      var split = splitLines(h2);
      var tl = gsap.timeline({
        defaults: { ease: EASE },
        scrollTrigger: { trigger: head, start: 'top 90%', once: true },
        onComplete: function () { if (split) split.revert(); }
      });
      if (split && split.lines.length) tl.fromTo(split.lines, { yPercent: 125 }, { yPercent: 0, duration: 0.9, stagger: 0.08 }, 0.15);
      if (rest.length) tl.fromTo(rest, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.6, clearProps: 'all' }, 0.45);
    });

    /* Lists arrive as lists, only the ones not yet seen. */
    var items = gsap.utils.toArray('.zh-rail > .zh-module, .zh-grid > .zh-module, .zh-steps > .zh-step, .zh-collections > li').filter(belowFold);
    if (items.length) {
      gsap.set(items, { autoAlpha: 0, y: 36 });
      ST.batch(items, {
        start: 'top 92%',
        once: true,
        onEnter: function (batch) {
          gsap.to(batch, {
            autoAlpha: 1, y: 0, duration: 0.95, ease: EASE, overwrite: true,
            stagger: { each: 0.07 }, clearProps: 'transform,opacity,visibility'
          });
        }
      });
      /* Photos settle inside their frames as the module arrives. */
      items.forEach(function (item) {
        var img = item.querySelector('.zh-module__media img');
        if (!img) return;
        gsap.fromTo(img, { scale: 1.12 }, {
          scale: 1, duration: 1.4, ease: EASE, clearProps: 'transform',
          scrollTrigger: { trigger: item, start: 'top 92%', once: true }
        });
      });
    }
  }

  /* ── Hero depth: swatch photos lift off their under-strips ────────── */
  function heroDepth() {
    if (!ST) return;
    var hero = document.querySelector('.zh-hero');
    if (!hero) return;
    var mm = gsap.matchMedia();
    mm.add('(min-width: 768px) and (hover: hover)', function () {
      var lifts = [-26, -40, -16];
      hero.querySelectorAll('.zh-swatch img').forEach(function (img, i) {
        gsap.to(img, {
          y: lifts[i % lifts.length], ease: 'none',
          scrollTrigger: { trigger: hero, start: 'top top', end: 'bottom top', scrub: 0.6 }
        });
      });
      var loom = hero.querySelector('.zh-hero__loom');
      if (loom) {
        gsap.to(loom, { yPercent: 12, ease: 'none', scrollTrigger: { trigger: hero, start: 'top top', end: 'bottom top', scrub: true } });
      }
    });
  }

  /* ── Vanta NET: loose indigo threads behind the hero ──────────────
     Desktop with a fine pointer only, never on Save-Data or slow links,
     loaded after the page has settled so it never competes with photos. */
  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  function hasWebGL() {
    try {
      var c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (c.getContext('webgl') || c.getContext('experimental-webgl')));
    } catch (e) { return false; }
  }

  function loom() {
    var el = document.querySelector('[data-loom]');
    if (!el) return;
    var mq = window.matchMedia('(min-width: 992px) and (hover: hover) and (pointer: fine)');
    var conn = navigator.connection || {};
    if (conn.saveData || /(^|-)(2g|3g)$/.test(conn.effectiveType || '')) return;

    var effect = null;
    var loading = false;

    function start() {
      if (effect || loading || !mq.matches || !hasWebGL()) return;
      loading = true;
      var three = window.THREE ? Promise.resolve() : loadScript(el.getAttribute('data-three-src'));
      three.then(function () {
        return window.VANTA && window.VANTA.NET ? null : loadScript(el.getAttribute('data-vanta-src'));
      }).then(function () {
        loading = false;
        if (!mq.matches || !window.VANTA || !window.VANTA.NET) return;
        effect = window.VANTA.NET({
          el: el,
          THREE: window.THREE,
          mouseControls: true,
          touchControls: false,
          gyroControls: false,
          minHeight: 200,
          minWidth: 200,
          scale: 1,
          scaleMobile: 1,
          color: 0x1f3a93,
          backgroundColor: 0xfbfbf8,
          points: 12,
          maxDistance: 21,
          spacing: 17,
          showDots: false
        });
        requestAnimationFrame(function () { el.classList.add('is-live'); });
      }).catch(function () { loading = false; /* the hero is complete without it */ });
    }

    function stop() {
      if (!effect) return;
      el.classList.remove('is-live');
      effect.destroy();
      effect = null;
    }

    var kick = function () {
      if ('requestIdleCallback' in window) window.requestIdleCallback(start, { timeout: 2500 });
      else setTimeout(start, 1200);
    };
    if (document.readyState === 'complete') kick();
    else window.addEventListener('load', kick, { once: true });

    var onChange = function () { if (mq.matches) start(); else stop(); };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
  }

  /* ── Boot ─────────────────────────────────────────────────────────── */
  fontsReady(400).then(function () {
    if (introAllowed) {
      heroIntro();
      pageHeadIntro();
    }
    ready();
    scrollWeaves();
    heroDepth();
    loom();
    if (ST) ST.refresh();
  });

  /* htmx swaps change page height: re-measure triggers and Lenis limits. */
  document.body.addEventListener('htmx:afterSettle', function () {
    if (ST) ST.refresh();
    if (lenis) lenis.resize();
  });
})();
