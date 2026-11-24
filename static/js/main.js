/* ===== Viati Café — JS global =====
   Reemplaza el comportamiento de Header.tsx, MobileMenu.tsx, ScrollReveal.tsx
   y Toast.tsx. Expone window.Viati con utilidades compartidas. */
(function () {
  'use strict';

  var Viati = (window.Viati = window.Viati || {});

  // ── Utilidades ──
  Viati.csrf = function () {
    var input = document.querySelector('input[name="csrfmiddlewaretoken"]');
    return input ? input.value : '';
  };

  Viati.formatPrice = function (value) {
    return '$ ' + Math.round(Number(value) || 0).toLocaleString('es-CO');
  };

  Viati.track = function (eventName, params) {
    if (typeof window.gtag === 'function') window.gtag('event', eventName, params);
  };

  // ── Toast "Agregado al carrito" (máx. 3 visibles, 3.5 s) ──
  Viati.toast = function (name, label) {
    var container = document.getElementById('viati-toasts');
    if (!container) return;
    while (container.children.length >= 3) container.removeChild(container.firstChild);

    var el = document.createElement('div');
    el.className =
      'viati-toast pointer-events-auto flex items-center gap-3 bg-crema border border-beige/40 text-verde-oscuro px-4 py-3 rounded-2xl shadow-md shadow-verde-oscuro/10 backdrop-blur-sm max-w-xs';
    el.innerHTML =
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="w-5 h-5 text-naranja shrink-0" aria-hidden="true"><polyline points="20 6 9 17 4 12" /></svg>' +
      '<div class="flex flex-col min-w-0">' +
      '<span class="font-nav text-xs font-bold uppercase tracking-wider text-verde-oscuro/70 leading-tight"></span>' +
      '<span class="font-cuerpo text-sm text-verde-header truncate leading-tight"></span>' +
      '</div>';
    el.querySelectorAll('span')[0].textContent = label || 'Agregado al carrito';
    el.querySelectorAll('span')[1].textContent = name;
    container.appendChild(el);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { el.classList.add('is-visible'); });
    });
    setTimeout(function () {
      el.classList.remove('is-visible');
      setTimeout(function () { el.remove(); }, 400);
    }, 3500);
  };

  // ── Bloqueo de scroll compartido (menú móvil, carrito, lightbox) ──
  var locks = 0;
  Viati.lockScroll = function () { locks++; document.body.style.overflow = 'hidden'; };
  Viati.unlockScroll = function () {
    locks = Math.max(0, locks - 1);
    if (!locks) document.body.style.overflow = '';
  };

  // ── Header: sombra al hacer scroll ──
  function initHeader() {
    var header = document.getElementById('site-header');
    if (!header) return;
    var onScroll = function () {
      var scrolled = window.scrollY > 10;
      header.classList.toggle('shadow-md', scrolled);
      header.classList.toggle('shadow-verde-oscuro/20', scrolled);
      header.classList.toggle('shadow-sm', !scrolled);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  // ── Menú móvil ──
  function initMobileMenu() {
    var toggle = document.getElementById('menu-toggle');
    var menu = document.getElementById('mobile-menu');
    var backdrop = document.getElementById('mobile-menu-backdrop');
    if (!toggle || !menu || !backdrop) return;
    var bars = toggle.querySelectorAll('[data-bar]');
    var open = false;

    function set(state) {
      if (state === open) return;
      open = state;
      menu.classList.toggle('translate-x-full', !open);
      menu.classList.toggle('translate-x-0', open);
      backdrop.classList.toggle('opacity-0', !open);
      backdrop.classList.toggle('pointer-events-none', !open);
      backdrop.classList.toggle('opacity-100', open);
      if (open) menu.removeAttribute('inert'); else menu.setAttribute('inert', '');
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Cerrar menú' : 'Abrir menú');
      bars[0].classList.toggle('rotate-45', open);
      bars[0].classList.toggle('translate-y-[7.5px]', open);
      bars[1].classList.toggle('opacity-0', open);
      bars[2].classList.toggle('-rotate-45', open);
      bars[2].classList.toggle('-translate-y-[7.5px]', open);
      if (open) Viati.lockScroll(); else Viati.unlockScroll();
    }

    Viati.closeMenu = function () { set(false); };
    toggle.addEventListener('click', function () { set(!open); });
    backdrop.addEventListener('click', function () { set(false); });
    menu.querySelectorAll('[data-menu-close], nav a, a[href="/"]').forEach(function (el) {
      el.addEventListener('click', function () { set(false); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') set(false);
    });
  }

  // ── Scroll reveal ──
  // Uso: data-reveal="up|down|left|right|fade" + style="--reveal-delay:.2s".
  Viati.observeReveal = function (root) {
    var els = (root || document).querySelectorAll('[data-reveal]:not(.is-visible)');
    if (!('IntersectionObserver' in window)) {
      els.forEach(function (el) { el.classList.add('is-visible'); });
      return;
    }
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: '0px 0px -80px 0px' }
    );
    els.forEach(function (el) { observer.observe(el); });
  };

  document.addEventListener('DOMContentLoaded', function () {
    initHeader();
    initMobileMenu();
    Viati.observeReveal();
  });
})();
