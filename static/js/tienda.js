/* ===== Viati Café — JS de la tienda =====
   Reemplaza el comportamiento de HeroSlider.tsx, ProductosGrid.tsx,
   CatalogGrid.tsx, ProductCard.tsx, ProductDetail.tsx y ScrollReveal
   con once={false} (BannerOrigenes.tsx). Las animaciones de Framer Motion
   se reproducen con la Web Animations API. */
(function () {
  'use strict';

  var EASE = 'cubic-bezier(0.25, 0.46, 0.45, 0.94)';
  var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function animate(el, keyframes, options) {
    if (!el.animate || reduceMotion) return Promise.resolve();
    var anim = el.animate(keyframes, options);
    return anim.finished.catch(function () {});
  }

  function formatPrice(value) {
    return window.Viati && window.Viati.formatPrice
      ? window.Viati.formatPrice(value)
      : '$ ' + Math.round(Number(value) || 0).toLocaleString('es-CO');
  }

  function setClasses(el, on, activeClasses, inactiveClasses) {
    var add = on ? activeClasses : inactiveClasses;
    var remove = on ? inactiveClasses : activeClasses;
    remove.split(' ').forEach(function (c) { if (c) el.classList.remove(c); });
    add.split(' ').forEach(function (c) { if (c) el.classList.add(c); });
  }

  // ════════════════════════════════════════════════════════════════
  // Tarjeta de producto y detalle (tamaño, molienda, cantidad, carrito)
  // ════════════════════════════════════════════════════════════════
  var INACTIVE = 'bg-beige/30 text-verde-oscuro hover:bg-beige/60';
  var VARIANTS = {
    card: {
      size: 'bg-verde-oscuro text-crema',
      grind: 'bg-naranja-oscuro text-crema',
    },
    detail: {
      size: 'bg-verde-oscuro text-crema shadow-sm shadow-verde-oscuro/20',
      grind: 'bg-naranja-oscuro text-crema shadow-sm shadow-naranja-oscuro/20',
    },
  };

  // AnimatePresence mode="wait": sale un botón (0.2 s) y entra el otro (0.2 s).
  function swapButtons(from, to) {
    var frames = [
      { opacity: 1, transform: 'scale(1)' },
      { opacity: 0, transform: 'scale(0.95)' },
    ];
    return animate(from, frames, { duration: 200, easing: 'ease-out' }).then(function () {
      from.hidden = true;
      to.hidden = false;
      return animate(to, frames.slice().reverse(), { duration: 200, easing: 'ease-out' });
    });
  }

  function initProduct(root, kind) {
    var variant = VARIANTS[kind];
    var basePrice = Number(root.getAttribute('data-base-price')) || 0;
    var multi = root.getAttribute('data-multi') === '1';
    var sizeBtns = root.querySelectorAll('[data-size-btn]');
    var grindBtns = root.querySelectorAll('[data-grind-btn]');
    var priceEl = root.querySelector('[data-price-display]');
    var fromLabel = root.querySelector('[data-from-label]');
    var qtyEl = root.querySelector('[data-qty-value]');
    var addBtn = root.querySelector('[data-add-to-cart]');
    var addedBtn = root.querySelector('[data-added-btn]');

    var state = {
      size: sizeBtns.length ? sizeBtns[0].getAttribute('data-size') : '',
      price: sizeBtns.length ? Number(sizeBtns[0].getAttribute('data-price')) : basePrice,
      grind: grindBtns.length ? grindBtns[0].getAttribute('data-grind') : '',
      qty: 1,
      added: false,
    };

    function render() {
      sizeBtns.forEach(function (btn) {
        setClasses(btn, btn.getAttribute('data-size') === state.size, variant.size, INACTIVE);
      });
      grindBtns.forEach(function (btn) {
        setClasses(btn, btn.getAttribute('data-grind') === state.grind, variant.grind, INACTIVE);
      });
      var showFrom = multi && state.price === basePrice;
      if (priceEl) {
        priceEl.textContent = (kind === 'card' && showFrom ? 'Desde ' : '') + formatPrice(state.price);
      }
      if (fromLabel) fromLabel.hidden = !showFrom;
      if (qtyEl) qtyEl.textContent = String(state.qty);
      if (addBtn) {
        addBtn.setAttribute('data-size', state.size);
        addBtn.setAttribute('data-grind', state.grind);
        addBtn.setAttribute('data-qty', String(state.qty));
      }
    }

    sizeBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.size = btn.getAttribute('data-size');
        state.price = Number(btn.getAttribute('data-price')) || basePrice;
        render();
      });
    });
    grindBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        state.grind = btn.getAttribute('data-grind');
        render();
      });
    });

    var minus = root.querySelector('[data-qty-minus]');
    var plus = root.querySelector('[data-qty-plus]');
    if (minus) minus.addEventListener('click', function () { state.qty = Math.max(1, state.qty - 1); render(); });
    if (plus) plus.addEventListener('click', function () { state.qty += 1; render(); });

    if (addBtn && addedBtn) {
      addBtn.addEventListener('click', function () {
        if (state.added) return;
        state.added = true;

        if (window.ViatiCart && typeof window.ViatiCart.add === 'function') {
          Promise.resolve(
            window.ViatiCart.add({
              slug: addBtn.getAttribute('data-slug'),
              size: state.size,
              grind: state.grind,
              qty: state.qty,
              name: addBtn.getAttribute('data-name'),
            })
          ).catch(function (err) { console.error('[tienda] No se pudo agregar al carrito', err); });
        } else {
          console.error('[tienda] window.ViatiCart no está disponible');
        }

        // Feedback "Agregado" durante 2 s (igual que el original).
        var shown = swapButtons(addBtn, addedBtn);
        setTimeout(function () {
          shown.then(function () {
            return swapButtons(addedBtn, addBtn);
          }).then(function () { state.added = false; });
        }, 2000);
      });
    }

    render();
  }

  // ════════════════════════════════════════════════════════════════
  // Hero slider (HeroSlider.tsx): autoplay 8 s, flechas, puntos
  // ════════════════════════════════════════════════════════════════
  function initHeroSlider(section) {
    var slides;
    try { slides = JSON.parse(section.getAttribute('data-slides')); } catch (e) { return; }
    if (!slides || slides.length < 2) return;

    var slide = section.querySelector('[data-hero-slide]');
    var img = section.querySelector('[data-hero-img]');
    var dots = section.querySelectorAll('[data-hero-dot]');
    var current = 0;
    var shown = 0;
    var direction = 0;
    var busy = false;

    // Precarga para que la entrada no espere a la red.
    slides.slice(1).forEach(function (src) { var i = new Image(); i.src = src; });

    function renderDots() {
      dots.forEach(function (dot, i) {
        setClasses(dot, i === current, 'bg-naranja w-8', 'bg-blanco/50 hover:bg-blanco/80');
      });
    }

    function offset(d) { return d > 0 ? '100%' : '-100%'; }

    function run() {
      if (busy || shown === current) return;
      busy = true;
      var exitDir = direction;
      animate(
        slide,
        [
          { transform: 'translateX(0)', opacity: 1 },
          { transform: 'translateX(' + offset(-exitDir) + ')', opacity: 0 },
        ],
        { duration: 600, easing: EASE, fill: 'forwards' }
      ).then(function () {
        shown = current;
        img.src = slides[shown];
        img.removeAttribute('fetchpriority');
        return animate(
          slide,
          [
            { transform: 'translateX(' + offset(direction) + ')', opacity: 0 },
            { transform: 'translateX(0)', opacity: 1 },
          ],
          { duration: 600, easing: EASE, fill: 'forwards' }
        );
      }).then(function () {
        slide.getAnimations && slide.getAnimations().forEach(function (a) { a.cancel(); });
        busy = false;
        run();
      });
    }

    function setPage(index, dir) {
      current = index;
      direction = dir;
      renderDots();
      run();
    }

    function paginate(dir) {
      setPage((current + dir + slides.length) % slides.length, dir);
    }

    section.querySelector('[data-hero-prev]').addEventListener('click', function () { paginate(-1); });
    section.querySelector('[data-hero-next]').addEventListener('click', function () { paginate(1); });
    dots.forEach(function (dot, i) {
      dot.addEventListener('click', function () {
        if (i === current) return;
        setPage(i, i > current ? 1 : -1);
      });
    });

    setInterval(function () { paginate(1); }, 8000);
  }

  // ════════════════════════════════════════════════════════════════
  // Carrusel arrastrable de destacados (ProductosGrid.tsx)
  // ════════════════════════════════════════════════════════════════
  function initDragScroll(el) {
    var isMouseDown = false;
    var dragged = false;
    var startX = 0;
    var startScroll = 0;

    function begin(pageX) {
      dragged = false;
      startX = pageX - el.offsetLeft;
      startScroll = el.scrollLeft;
    }
    function move(pageX) {
      var walk = pageX - el.offsetLeft - startX;
      if (Math.abs(walk) > 5) {
        dragged = true;
        el.scrollLeft = startScroll - walk;
      }
    }

    el.addEventListener('mousedown', function (e) { isMouseDown = true; begin(e.pageX); });
    el.addEventListener('mousemove', function (e) { if (isMouseDown) move(e.pageX); });
    el.addEventListener('mouseup', function () { isMouseDown = false; });
    el.addEventListener('mouseleave', function () { isMouseDown = false; dragged = false; });
    el.addEventListener('touchstart', function (e) { begin(e.touches[0].pageX); }, { passive: true });
    el.addEventListener('touchmove', function (e) { move(e.touches[0].pageX); }, { passive: true });
    el.addEventListener('touchend', function () { setTimeout(function () { dragged = false; }, 0); });

    // Un arrastre no debe disparar el clic de la tarjeta/botón debajo.
    el.addEventListener('click', function (e) {
      if (dragged) {
        e.preventDefault();
        e.stopPropagation();
        dragged = false;
      }
    }, true);
  }

  function initSwipeHint(hint) {
    hint.querySelectorAll('[data-nudge]').forEach(function (arrow) {
      var x = arrow.getAttribute('data-nudge') + 'px';
      animate(
        arrow,
        [{ transform: 'translateX(0)' }, { transform: 'translateX(' + x + ')' }, { transform: 'translateX(0)' }],
        { duration: 1500, iterations: Infinity, easing: 'ease-in-out' }
      );
    });
    setTimeout(function () { hint.style.opacity = '0'; }, 4000);
  }

  // ════════════════════════════════════════════════════════════════
  // ScrollReveal con once={false}: se oculta al salir y reaparece al entrar
  // ════════════════════════════════════════════════════════════════
  function initRepeatReveal(els) {
    if (!els.length || !('IntersectionObserver' in window)) return;
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          entry.target.classList.toggle('is-visible', entry.isIntersecting);
        });
      },
      { rootMargin: '-80px' }
    );
    els.forEach(function (el) { observer.observe(el); });
  }

  // ════════════════════════════════════════════════════════════════
  // Catálogo (CatalogGrid.tsx): categorías + orden, con animación "layout"
  // ════════════════════════════════════════════════════════════════
  function initCatalog(root) {
    var grid = root.querySelector('[data-catalog-grid]');
    var empty = root.querySelector('[data-catalog-empty]');
    var countEl = root.querySelector('[data-catalog-count]');
    var select = root.querySelector('[data-sort-select]');
    var catBtns = root.querySelectorAll('[data-category-btn]');
    var items = Array.prototype.slice.call(root.querySelectorAll('[data-catalog-item]'));
    var collator = new Intl.Collator('es');
    var category = 'Todos';
    var sortBy = select ? select.value : 'default';

    var data = items.map(function (el) {
      return {
        el: el,
        category: el.getAttribute('data-category'),
        price: Number(el.getAttribute('data-price')) || 0,
        name: el.getAttribute('data-name') || '',
        featured: el.getAttribute('data-featured') === '1',
      };
    });

    function compute() {
      var result = data.filter(function (p) { return category === 'Todos' || p.category === category; });
      switch (sortBy) {
        case 'price-asc':
          result.sort(function (a, b) { return a.price - b.price; });
          break;
        case 'price-desc':
          result.sort(function (a, b) { return b.price - a.price; });
          break;
        case 'name-asc':
          result.sort(function (a, b) { return collator.compare(a.name, b.name); });
          break;
        default:
          result.sort(function (a, b) {
            if (a.featured && !b.featured) return -1;
            if (!a.featured && b.featured) return 1;
            return collator.compare(a.name, b.name);
          });
      }
      return result;
    }

    var MOUNT = [
      { opacity: 0, transform: 'scale(0.95)' },
      { opacity: 1, transform: 'scale(1)' },
    ];

    function apply(animated) {
      var before = new Map();
      if (animated) {
        data.forEach(function (p) {
          if (!p.el.hidden) before.set(p.el, p.el.getBoundingClientRect());
        });
      }

      var result = compute();
      var visible = new Set(result.map(function (p) { return p.el; }));
      data.forEach(function (p) { p.el.hidden = !visible.has(p.el); });
      result.forEach(function (p) { grid.appendChild(p.el); });

      grid.hidden = result.length === 0;
      if (empty) empty.hidden = result.length > 0;
      if (countEl) countEl.textContent = String(result.length);

      if (!animated) return;
      result.forEach(function (p) {
        var prev = before.get(p.el);
        if (!prev) {
          animate(p.el, MOUNT, { duration: 300, easing: EASE });
          return;
        }
        var next = p.el.getBoundingClientRect();
        var dx = prev.left - next.left;
        var dy = prev.top - next.top;
        if (dx || dy) {
          animate(
            p.el,
            [{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'translate(0,0)' }],
            { duration: 300, easing: EASE }
          );
        }
      });
    }

    catBtns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        category = btn.getAttribute('data-category');
        catBtns.forEach(function (b) {
          setClasses(
            b,
            b === btn,
            'bg-verde-oscuro text-crema shadow-sm shadow-verde-oscuro/20',
            INACTIVE
          );
        });
        apply(true);
      });
    });

    if (select) {
      select.addEventListener('change', function () {
        sortBy = select.value;
        apply(true);
      });
    }

    apply(false);
    // Animación de montaje inicial (initial → animate de cada motion.div).
    data.forEach(function (p) {
      if (!p.el.hidden) animate(p.el, MOUNT, { duration: 300, easing: EASE });
    });
  }

  // ════════════════════════════════════════════════════════════════
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-hero-slider]').forEach(initHeroSlider);
    document.querySelectorAll('[data-drag-scroll]').forEach(initDragScroll);
    document.querySelectorAll('[data-swipe-hint]').forEach(initSwipeHint);
    initRepeatReveal(document.querySelectorAll('[data-reveal-repeat]'));
    document.querySelectorAll('[data-catalog]').forEach(initCatalog);
    document.querySelectorAll('[data-product-card]').forEach(function (el) { initProduct(el, 'card'); });
    document.querySelectorAll('[data-product-detail]').forEach(function (el) { initProduct(el, 'detail'); });
  });
})();
