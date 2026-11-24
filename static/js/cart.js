/* ===== Viati Café — Carrito (reemplaza Snipcart) =====

   API pública (contrato con la app tienda):
     window.ViatiCart.add({slug, size, grind, qty, name}) -> Promise<carrito JSON>
         Agrega al carrito (POST /carrito/agregar). Al terminar actualiza todos los
         [data-cart-count], muestra el toast "Agregado al carrito" y envía el evento
         GA4 add_to_cart. NO abre el panel (igual que Snipcart con
         data-config-add-product-behavior="none"). Si falla, rechaza la promesa
         (error.message en español) después de mostrar un toast de error.
     window.ViatiCart.open()     Abre el panel lateral.
     window.ViatiCart.close()    Lo cierra.
     window.ViatiCart.refresh()  -> Promise<carrito JSON> (GET /carrito/estado).
     window.ViatiCart.state      Último JSON recibido (o null).

   JSON del carrito: {count, subtotal, total_weight, free_shipping_from,
   checkout_url, items: [{key, slug, name, image, url, size, grind, options,
   qty, unit_price, total}], added?: {...línea, qty_added}}.

   Atajos declarativos:
     - Cualquier [data-cart-open] abre el panel (y cierra el menú móvil).
     - Botones con data-add-to-cart="auto" se manejan aquí leyendo
       data-slug / data-size / data-grind / data-qty / data-name.
       OJO: SOLO el valor "auto". La tienda llama ViatiCart.add() desde sus
       propios handlers en botones [data-add-to-cart] (sin "auto"); si aquí se
       atendieran todos, el producto se agregaría dos veces.

   Además se emite el evento `viati:cart` en document (detail = carrito JSON)
   cada vez que cambia el carrito (lo usa checkout.js). */
(function () {
  'use strict';

  var Viati = (window.Viati = window.Viati || {});
  var root, panel, veil, list, tpl;
  var isOpen = false;
  var lastFocus = null;
  var pending = 0;

  // ── Utilidades ──
  function csrf() {
    if (typeof Viati.csrf === 'function' && Viati.csrf()) return Viati.csrf();
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function price(n) {
    return typeof Viati.formatPrice === 'function'
      ? Viati.formatPrice(n)
      : '$ ' + Math.round(Number(n) || 0).toLocaleString('es-CO');
  }

  function api(url, body) {
    var opts = {
      method: body ? 'POST' : 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    };
    if (body) {
      opts.headers['Content-Type'] = 'application/json';
      opts.headers['X-CSRFToken'] = csrf();
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (res) {
      return res
        .json()
        .catch(function () { return {}; })
        .then(function (data) {
          if (!res.ok) {
            if (data && Array.isArray(data.items)) render(data);
            var err = new Error(
              (data && data.error) ||
                (res.status === 403 ? 'Tu sesión expiró. Recarga la página e intenta de nuevo.' : 'No pudimos actualizar el carrito.')
            );
            err.data = data;
            err.status = res.status;
            throw err;
          }
          render(data);
          return data;
        });
    });
  }

  function setBusy(on) {
    pending = Math.max(0, pending + (on ? 1 : -1));
    if (list) list.classList.toggle('opacity-60', pending > 0);
  }

  // ── Render ──
  function updateCounts(count) {
    document.querySelectorAll('[data-cart-count]').forEach(function (el) {
      el.textContent = String(count);
    });
  }

  function render(state) {
    ViatiCart.state = state;
    updateCounts(state.count || 0);
    document.dispatchEvent(new CustomEvent('viati:cart', { detail: state }));
    if (!root) return;

    var items = state.items || [];
    var empty = items.length === 0;
    q('[data-cart-loading]').hidden = true;
    q('[data-cart-empty]').hidden = !empty;
    q('[data-cart-footer]').hidden = empty;
    q('[data-cart-heading-count]').textContent = empty
      ? ''
      : state.count + (state.count === 1 ? ' artículo' : ' artículos');
    q('[data-cart-subtotal]').textContent = price(state.subtotal);

    var hint = q('[data-cart-free-hint]');
    var threshold = Number(state.free_shipping_from) || 0;
    if (threshold > 0 && !empty) {
      var missing = threshold - state.subtotal;
      hint.textContent = missing > 0
        ? 'Te faltan ' + price(missing) + ' para el envío gratis.'
        : '¡Tu pedido tiene envío gratis!';
      hint.hidden = false;
    } else {
      hint.hidden = true;
    }

    list.textContent = '';
    items.forEach(function (item) {
      var node = tpl.content.firstElementChild.cloneNode(true);
      node.dataset.key = item.key;
      node.querySelectorAll('[data-item-link]').forEach(function (a) { a.href = item.url; });
      var img = node.querySelector('[data-item-image]');
      img.src = item.image;
      img.alt = item.name;
      node.querySelector('[data-item-name]').textContent = item.name;
      var opts = node.querySelector('[data-item-options]');
      opts.textContent = item.options || '';
      opts.hidden = !item.options;
      node.querySelector('[data-item-qty]').textContent = item.qty;
      node.querySelector('[data-item-total]').textContent = price(item.total);
      node.querySelector('[data-item-unit]').textContent = item.qty > 1 ? price(item.unit_price) + ' c/u' : '';
      node.querySelector('[data-item-inc]').disabled = item.qty >= 99;
      node.querySelector('[data-item-remove]').setAttribute('aria-label', 'Eliminar ' + item.name);
      list.appendChild(node);
    });
  }

  function q(sel) { return root.querySelector(sel); }

  function showError(message) {
    if (!root) return;
    var box = q('[data-cart-error]');
    box.textContent = message;
    box.hidden = false;
    clearTimeout(showError.t);
    showError.t = setTimeout(function () { box.hidden = true; }, 5000);
  }

  // ── Abrir / cerrar ──
  function open() {
    if (!root || isOpen) return;
    isOpen = true;
    lastFocus = document.activeElement;
    root.classList.remove('pointer-events-none');
    veil.classList.replace('opacity-0', 'opacity-100');
    panel.classList.replace('translate-x-full', 'translate-x-0');
    panel.removeAttribute('inert');
    if (Viati.lockScroll) Viati.lockScroll();
    if (!ViatiCart.state) {
      q('[data-cart-loading]').hidden = false;
      q('[data-cart-empty]').hidden = true;
    }
    refresh().catch(function (err) { showError(err.message); q('[data-cart-loading]').hidden = true; });
    setTimeout(function () {
      var first = q('[data-cart-close]');
      (first || panel).focus();
    }, 50);
  }

  function close() {
    if (!root || !isOpen) return;
    isOpen = false;
    root.classList.add('pointer-events-none');
    veil.classList.replace('opacity-100', 'opacity-0');
    panel.classList.replace('translate-x-0', 'translate-x-full');
    panel.setAttribute('inert', '');
    if (Viati.unlockScroll) Viati.unlockScroll();
    if (lastFocus && typeof lastFocus.focus === 'function' && document.contains(lastFocus)) lastFocus.focus();
    document.dispatchEvent(new CustomEvent('viati:cart-closed', { detail: ViatiCart.state }));
  }

  function trapFocus(e) {
    if (!isOpen || e.key !== 'Tab') return;
    var focusables = Array.prototype.filter.call(
      panel.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
      function (el) { return el.offsetParent !== null; }
    );
    if (!focusables.length) return;
    var first = focusables[0];
    var last = focusables[focusables.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  // ── Acciones ──
  function refresh() {
    return api('/carrito/estado');
  }

  function add(opts) {
    opts = opts || {};
    var qty = parseInt(opts.qty, 10) || 1;
    return api('/carrito/agregar', {
      slug: opts.slug,
      size: opts.size || '',
      grind: opts.grind || '',
      qty: qty,
    }).then(
      function (data) {
        var line = data.added || {};
        var name = opts.name || line.name || '';
        if (Viati.toast) Viati.toast(name);
        if (Viati.track) {
          var unit = Number(line.unit_price) || 0;
          Viati.track('add_to_cart', {
            currency: 'COP',
            value: unit * qty,
            items: [
              {
                item_id: line.slug || opts.slug || '',
                item_name: line.name || name,
                item_variant: line.options || undefined,
                price: unit,
                quantity: qty,
              },
            ],
          });
        }
        return data;
      },
      function (err) {
        if (Viati.toast) Viati.toast(err.message, 'No se pudo agregar');
        throw err;
      }
    );
  }

  function changeLine(key, qty) {
    setBusy(true);
    var req = qty > 0
      ? api('/carrito/actualizar', { key: key, qty: qty })
      : api('/carrito/eliminar', { key: key });
    return req
      .catch(function (err) { showError(err.message); })
      .then(function () { setBusy(false); });
  }

  var ViatiCart = (window.ViatiCart = {
    add: add,
    open: open,
    close: close,
    refresh: refresh,
    state: null,
  });

  // ── Eventos ──
  function onDocumentClick(e) {
    var opener = e.target.closest('[data-cart-open]');
    if (opener) {
      e.preventDefault();
      if (typeof Viati.closeMenu === 'function') Viati.closeMenu();
      open();
      return;
    }

    var auto = e.target.closest('[data-add-to-cart="auto"]');
    if (auto) {
      e.preventDefault();
      if (auto.disabled || auto.getAttribute('aria-busy') === 'true') return;
      auto.setAttribute('aria-busy', 'true');
      auto.disabled = true;
      add({
        slug: auto.dataset.slug,
        size: auto.dataset.size,
        grind: auto.dataset.grind,
        qty: auto.dataset.qty,
        name: auto.dataset.name,
      })
        .catch(function () {})
        .then(function () {
          auto.disabled = false;
          auto.removeAttribute('aria-busy');
        });
    }
  }

  function onPanelClick(e) {
    if (e.target.closest('[data-cart-close]')) { close(); return; }
    var row = e.target.closest('li[data-key]');
    if (!row || pending) return;
    var key = row.dataset.key;
    var item = (ViatiCart.state && ViatiCart.state.items || []).filter(function (i) { return i.key === key; })[0];
    if (!item) return;
    if (e.target.closest('[data-item-remove]')) {
      row.classList.add('opacity-40');
      changeLine(key, 0);
    } else if (e.target.closest('[data-item-inc]')) {
      changeLine(key, Math.min(99, item.qty + 1));
    } else if (e.target.closest('[data-item-dec]')) {
      changeLine(key, item.qty - 1); // 0 → elimina
    }
  }

  function init() {
    root = document.querySelector('[data-cart-root]');
    if (root) {
      panel = root.querySelector('[data-cart-panel]');
      veil = root.querySelector('[data-cart-veil]');
      list = root.querySelector('[data-cart-items]');
      tpl = document.getElementById('viati-cart-item');
      veil.addEventListener('click', close);
      panel.addEventListener('click', onPanelClick);
      panel.addEventListener('keydown', trapFocus);
    }
    document.addEventListener('click', onDocumentClick);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen) close();
    });
    // Al volver con el botón "atrás" (bfcache, ej. desde Mercado Pago) el
    // contador puede estar desactualizado.
    window.addEventListener('pageshow', function (e) {
      if (e.persisted) refresh().catch(function () {});
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
