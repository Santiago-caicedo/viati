/* ===== Viati Café — Checkout =====
   - Recalcula el envío al cambiar el departamento (GET /checkout/envio).
   - Bloquea el botón al enviar (evita pedidos duplicados por doble clic).
   - Si el carrito cambia desde el panel lateral, recarga la página
     conservando lo que el cliente ya escribió (sessionStorage). */
(function () {
  'use strict';

  var STORAGE_KEY = 'viati_checkout_form';
  var form = document.querySelector('[data-checkout-form]');
  if (!form) return;

  var Viati = window.Viati || {};
  var price = function (n) {
    return Viati.formatPrice ? Viati.formatPrice(n) : '$ ' + Math.round(n).toLocaleString('es-CO');
  };
  var $ = function (sel) { return document.querySelector(sel); };
  var department = form.querySelector('[name="department"]');
  var submit = form.querySelector('[data-checkout-submit]');
  var initialCart = form.getAttribute('data-cart-signature') || '';
  var cartChanged = false;

  function storage(fn) {
    try { return fn(window.sessionStorage); } catch (e) { return null; }
  }

  // ── Restaurar datos tras una recarga por cambios en el carrito ──
  var saved = storage(function (s) { return s.getItem(STORAGE_KEY); });
  if (saved) {
    storage(function (s) { s.removeItem(STORAGE_KEY); });
    try {
      var values = JSON.parse(saved);
      Object.keys(values).forEach(function (name) {
        var field = form.elements[name];
        if (field && !field.value) field.value = values[name];
      });
    } catch (e) { /* ignorar */ }
  }

  function saveForm() {
    var values = {};
    Array.prototype.forEach.call(form.elements, function (el) {
      if (el.name && el.name !== 'csrfmiddlewaretoken' && el.value) values[el.name] = el.value;
    });
    storage(function (s) { s.setItem(STORAGE_KEY, JSON.stringify(values)); });
  }

  // ── Cotización de envío ──
  function updateShipping() {
    var dep = department ? department.value : '';
    fetch('/checkout/envio?departamento=' + encodeURIComponent(dep), {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (res) { return res.ok ? res.json() : Promise.reject(); })
      .then(function (data) {
        var shipping = $('[data-summary-shipping]');
        if (!data.shipping_known) {
          shipping.innerHTML = '<span class="font-cuerpo font-normal text-texto-claro">Elige el departamento</span>';
        } else {
          shipping.textContent = data.shipping_free || !data.shipping ? 'Gratis' : price(data.shipping);
        }
        $('[data-summary-subtotal]').textContent = price(data.subtotal);
        $('[data-summary-total]').textContent = price(data.total);
      })
      .catch(function () { /* el servidor recalcula igual al enviar */ });
  }
  if (department) department.addEventListener('change', updateShipping);
  if (department && department.value) updateShipping();

  // ── Envío del formulario ──
  form.addEventListener('submit', function (e) {
    if (submit.disabled) { e.preventDefault(); return; }
    submit.disabled = true;
    var label = submit.querySelector('[data-checkout-submit-label]');
    if (label) label.textContent = 'Conectando con Mercado Pago…';
  });

  // Al volver con "atrás" desde Mercado Pago (bfcache) se recarga: el carrito
  // ya se convirtió en pedido y el servidor redirige al pedido pendiente.
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) window.location.reload();
  });

  // ── Cambios del carrito desde el panel lateral ──
  document.addEventListener('viati:cart', function (e) {
    var state = e.detail || {};
    var signature = (state.items || []).map(function (i) { return i.key + ':' + i.qty; }).join('|');
    if (signature !== initialCart) cartChanged = true;
  });
  document.addEventListener('viati:cart-closed', function (e) {
    if (!cartChanged) return;
    var state = e.detail || {};
    if (!state.count) { window.location.href = '/tienda'; return; }
    saveForm();
    window.location.reload();
  });
})();
