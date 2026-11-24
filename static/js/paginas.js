/* ===== Viati Café — JS de las páginas institucionales =====
   Reemplaza OrigenDetail.tsx (tabs), GalleryWithLightbox.tsx, Carrusel.tsx,
   FAQAccordion.tsx, ContactForm.tsx e InstitucionalForm.tsx.
   Depende de window.Viati (static/js/main.js). */
(function () {
  'use strict';

  var Viati = (window.Viati = window.Viati || {});
  var EASE = 'cubic-bezier(0.25, 0.46, 0.45, 0.94)';

  function classes(str) { return (str || '').split(/\s+/).filter(Boolean); }
  function swap(el, remove, add) {
    el.classList.remove.apply(el.classList, classes(remove));
    el.classList.add.apply(el.classList, classes(add));
  }
  function nextFrame(fn) {
    requestAnimationFrame(function () { requestAnimationFrame(fn); });
  }
  function lock() { if (Viati.lockScroll) Viati.lockScroll(); else document.body.style.overflow = 'hidden'; }
  function unlock() { if (Viati.unlockScroll) Viati.unlockScroll(); else document.body.style.overflow = ''; }

  // ── Tabs Clima / Atractivos / El Caficultor (OrigenDetail.tsx) ──
  function initTabs(root) {
    var nav = root.querySelector('[role="tablist"]');
    if (!nav) return;
    var tabs = Array.prototype.slice.call(nav.querySelectorAll('[role="tab"]'));
    var activeCls = nav.dataset.activeClass;
    var inactiveCls = nav.dataset.inactiveClass;

    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute('aria-selected', String(on));
        t.tabIndex = on ? 0 : -1;
        if (on) swap(t, inactiveCls, activeCls); else swap(t, activeCls, inactiveCls);
        var panel = document.getElementById(t.getAttribute('aria-controls'));
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }

    tabs.forEach(function (tab, i) {
      tab.addEventListener('click', function () { select(tab); });
      tab.addEventListener('keydown', function (e) {
        var j = null;
        if (e.key === 'ArrowRight') j = (i + 1) % tabs.length;
        else if (e.key === 'ArrowLeft') j = (i - 1 + tabs.length) % tabs.length;
        else if (e.key === 'Home') j = 0;
        else if (e.key === 'End') j = tabs.length - 1;
        if (j !== null) { e.preventDefault(); select(tabs[j], true); }
      });
    });
  }

  // ── Galería con lightbox (GalleryWithLightbox.tsx) ──
  function initGallery(root) {
    var buttons = Array.prototype.slice.call(root.querySelectorAll('[data-gallery-index]'));
    var tpl = root.querySelector('[data-lightbox-template]');
    if (!buttons.length || !tpl) return;
    var images = buttons
      .sort(function (a, b) { return a.dataset.galleryIndex - b.dataset.galleryIndex; })
      .map(function (b) { return { src: b.dataset.src, alt: b.dataset.alt }; });

    var box = null, img, figure, counter, current = 0, trigger = null, swapTimer = null;

    function render(index, animate) {
      current = index;
      counter.textContent = (current + 1) + ' / ' + images.length;
      clearTimeout(swapTimer);
      if (!animate) {
        img.src = images[current].src;
        img.alt = images[current].alt;
        nextFrame(function () { swap(figure, 'opacity-0 scale-95', 'opacity-100 scale-100'); });
        return;
      }
      // AnimatePresence mode="wait": sale la imagen actual y luego entra la nueva.
      swap(figure, 'opacity-100 scale-100', 'opacity-0 scale-95');
      swapTimer = setTimeout(function () {
        img.src = images[current].src;
        img.alt = images[current].alt;
        nextFrame(function () { swap(figure, 'opacity-0 scale-95', 'opacity-100 scale-100'); });
      }, 200);
    }

    function prev() { render((current - 1 + images.length) % images.length, true); }
    function next() { render((current + 1) % images.length, true); }

    function onKey(e) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowLeft') prev();
      else if (e.key === 'ArrowRight') next();
      else if (e.key === 'Tab') {
        // Mantiene el foco dentro del lightbox
        var focusables = box.querySelectorAll('button');
        var first = focusables[0], last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }

    function open(index, btn) {
      if (box) return;
      trigger = btn;
      box = tpl.content.firstElementChild.cloneNode(true);
      img = box.querySelector('[data-lightbox-img]');
      figure = box.querySelector('[data-lightbox-figure]');
      counter = box.querySelector('[data-lightbox-counter]');

      box.addEventListener('click', close);
      figure.addEventListener('click', function (e) { e.stopPropagation(); });
      box.querySelector('[data-lightbox-close]').addEventListener('click', function (e) { e.stopPropagation(); close(); });
      box.querySelector('[data-lightbox-prev]').addEventListener('click', function (e) { e.stopPropagation(); prev(); });
      box.querySelector('[data-lightbox-next]').addEventListener('click', function (e) { e.stopPropagation(); next(); });

      document.body.appendChild(box);
      document.addEventListener('keydown', onKey);
      lock();
      render(index, false);
      nextFrame(function () { swap(box, 'opacity-0', 'opacity-100'); });
      box.querySelector('[data-lightbox-close]').focus();
    }

    function close() {
      if (!box) return;
      var el = box;
      box = null;
      clearTimeout(swapTimer);
      document.removeEventListener('keydown', onKey);
      unlock();
      swap(el, 'opacity-100', 'opacity-0');
      setTimeout(function () { el.remove(); }, 250);
      if (trigger) trigger.focus();
    }

    buttons.forEach(function (btn) {
      btn.addEventListener('click', function () { open(Number(btn.dataset.galleryIndex), btn); });
    });
  }

  // ── Carrusel (Carrusel.tsx): deslizamiento 0.5 s, avance automático cada 5 s ──
  function initCarrusel(root) {
    var slides = Array.prototype.slice.call(root.querySelectorAll('[data-slide]'));
    var dots = Array.prototype.slice.call(root.querySelectorAll('[data-dot]'));
    if (slides.length < 2) return;
    var dotsBox = dots[0].parentElement;
    var activeCls = dotsBox.dataset.activeClass;
    var inactiveCls = dotsBox.dataset.inactiveClass;
    var current = 0, token = 0;
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var DUR = reduce ? 0 : 500;

    function set(el, x, opacity, animate) {
      el.style.transition = animate && DUR ? 'transform .5s ' + EASE + ', opacity .5s ' + EASE : 'none';
      el.style.transform = 'translateX(' + x + ')';
      el.style.opacity = String(opacity);
    }

    function updateDots(index) {
      dots.forEach(function (d, i) {
        if (i === index) swap(d, inactiveCls, activeCls); else swap(d, activeCls, inactiveCls);
      });
    }

    function go(index, direction) {
      if (index === current) return;
      var my = ++token;
      var out = slides[current];
      var inc = slides[index];
      current = index;
      updateDots(index);

      // Salida (AnimatePresence mode="wait")
      set(out, direction > 0 ? '-100%' : '100%', 0, true);
      setTimeout(function () {
        if (my !== token) return;
        slides.forEach(function (s) {
          if (s !== inc) { s.style.visibility = 'hidden'; s.setAttribute('aria-hidden', 'true'); }
        });
        // Entrada desde el lado opuesto
        set(inc, direction > 0 ? '100%' : '-100%', 0, false);
        inc.style.visibility = 'visible';
        inc.removeAttribute('aria-hidden');
        void inc.offsetWidth;
        set(inc, '0', 1, true);
      }, DUR);
    }

    function paginate(dir) { go((current + dir + slides.length) % slides.length, dir); }

    root.querySelector('[data-prev]').addEventListener('click', function () { paginate(-1); });
    root.querySelector('[data-next]').addEventListener('click', function () { paginate(1); });
    dots.forEach(function (d, i) {
      d.addEventListener('click', function () { go(i, i > current ? 1 : -1); });
    });
    setInterval(function () { paginate(1); }, 5000);
  }

  // ── Acordeón de preguntas frecuentes (FAQAccordion.tsx) ──
  function initAccordion(root) {
    var items = Array.prototype.slice.call(root.querySelectorAll('[aria-controls]')).map(function (btn) {
      return { btn: btn, panel: btn.parentElement.querySelector('[data-accordion-panel]'), icon: btn.querySelector('svg') };
    });
    var T = 'height .3s ' + EASE + ', opacity .3s ' + EASE;

    function setOpen(item, open) {
      var panel = item.panel;
      item.btn.setAttribute('aria-expanded', String(open));
      item.icon.classList.toggle('rotate-45', open);
      clearTimeout(panel._timer);
      if (open) {
        panel.hidden = false;
        panel.style.transition = 'none';
        panel.style.height = '0px';
        panel.style.opacity = '0';
        void panel.offsetHeight;
        panel.style.transition = T;
        panel.style.height = panel.scrollHeight + 'px';
        panel.style.opacity = '1';
        panel._timer = setTimeout(function () { panel.style.height = 'auto'; }, 300);
      } else {
        panel.style.transition = 'none';
        panel.style.height = panel.scrollHeight + 'px';
        void panel.offsetHeight;
        panel.style.transition = T;
        panel.style.height = '0px';
        panel.style.opacity = '0';
        panel._timer = setTimeout(function () { panel.hidden = true; }, 300);
      }
    }

    items.forEach(function (item) {
      item.btn.addEventListener('click', function () {
        var willOpen = item.btn.getAttribute('aria-expanded') !== 'true';
        items.forEach(function (other) {
          if (other !== item && other.btn.getAttribute('aria-expanded') === 'true') setOpen(other, false);
        });
        setOpen(item, willOpen);
      });
    });
  }

  // ── Formularios de contacto e institucional ──
  var EMAIL_RE = /^\S+@\S+\.\S+$/i;

  // Mismas reglas y mensajes que react-hook-form (ContactForm.tsx) y validate() (InstitucionalForm.tsx)
  var FORM_RULES = {
    contacto: {
      revalidate: true, // react-hook-form: tras el primer envío revalida al escribir
      focusError: true,
      fields: {
        nombre: function (v) { return !v ? 'El nombre es obligatorio' : v.length < 2 ? 'Mínimo 2 caracteres' : ''; },
        apellido: function (v) { return !v ? 'El apellido es obligatorio' : v.length < 2 ? 'Mínimo 2 caracteres' : ''; },
        email: function (v) { return !v ? 'El email es obligatorio' : !EMAIL_RE.test(v) ? 'Email inválido' : ''; },
        celular: function (v) { return !v ? 'El celular es obligatorio' : v.length < 7 ? 'Mínimo 7 dígitos' : ''; },
        mensaje: function (v) { return !v ? 'El mensaje es obligatorio' : v.length < 10 ? 'Mínimo 10 caracteres' : ''; }
      }
    },
    institucional: {
      revalidate: false, // al escribir solo se borra el error del campo
      focusError: false,
      fields: {
        name: function (v) { return !v || v.length < 2 ? 'El nombre debe tener al menos 2 caracteres' : ''; },
        company: function (v) { return !v || v.length < 2 ? 'La empresa debe tener al menos 2 caracteres' : ''; },
        email: function (v) { return !v || !EMAIL_RE.test(v) ? 'Correo electrónico inválido' : ''; }
      }
    }
  };

  function initForm(form) {
    var config = FORM_RULES[form.dataset.viatiForm];
    if (!config) return;
    var card = form.parentElement;
    var submit = form.querySelector('[data-submit]');
    var ds = form.dataset;
    var submitted = false, busy = false, status = null, statusTimer = null;

    function fieldEl(name) { return form.elements[name]; }

    function setError(name, message) {
      var input = fieldEl(name);
      var box = input.parentElement;
      var p = box.querySelector('[data-error]');
      if (message) {
        swap(input, ds.inputOk, ds.inputError);
        if (!p) {
          p = document.createElement('p');
          p.setAttribute('data-error', '');
          p.className = ds.errorClass;
          p.id = input.id + '-error';
          box.appendChild(p);
        }
        p.textContent = message;
        input.setAttribute('aria-invalid', 'true');
        input.setAttribute('aria-describedby', p.id);
      } else {
        swap(input, ds.inputError, ds.inputOk);
        if (p) p.remove();
        input.removeAttribute('aria-invalid');
        input.removeAttribute('aria-describedby');
      }
    }

    function validate() {
      var firstInvalid = null;
      Object.keys(config.fields).forEach(function (name) {
        var msg = config.fields[name](fieldEl(name).value);
        setError(name, msg);
        if (msg && !firstInvalid) firstInvalid = fieldEl(name);
      });
      if (firstInvalid && config.focusError) firstInvalid.focus();
      return !firstInvalid;
    }

    Object.keys(config.fields).forEach(function (name) {
      fieldEl(name).addEventListener('input', function () {
        if (config.revalidate) {
          if (submitted) setError(name, config.fields[name](fieldEl(name).value));
        } else if (fieldEl(name).hasAttribute('aria-invalid')) {
          setError(name, '');
        }
      });
    });

    function hideStatus() {
      clearTimeout(statusTimer);
      if (!status) return;
      var el = status;
      status = null;
      el.style.opacity = '0';
      el.style.transform = 'translateY(10px)';
      setTimeout(function () { el.remove(); }, 300);
    }

    function showStatus(kind) {
      hideStatus();
      var tpl = card.querySelector('template[data-status="' + kind + '"]');
      if (!tpl) return;
      var el = tpl.content.firstElementChild.cloneNode(true);
      el.style.opacity = '0';
      el.style.transform = 'translateY(10px)';
      el.style.transition = 'opacity .3s ease-out, transform .3s ease-out';
      form.appendChild(el);
      status = el;
      nextFrame(function () { el.style.opacity = '1'; el.style.transform = 'none'; });
      statusTimer = setTimeout(hideStatus, 5000);
    }

    function setBusy(state) {
      busy = state;
      submit.disabled = state;
      submit.textContent = state ? 'Enviando...' : submit.dataset.label;
      if (state) swap(submit, ds.idleClass, ds.busyClass); else swap(submit, ds.busyClass, ds.idleClass);
    }

    function payload() {
      var data = {};
      Array.prototype.forEach.call(form.elements, function (el) {
        if (!el.name) return;
        data[el.name] = el.type === 'checkbox' ? el.checked : el.value;
      });
      return data;
    }

    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (busy) return;
      submitted = true;
      if (!validate()) return;

      setBusy(true);
      hideStatus();

      fetch(ds.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': Viati.csrf ? Viati.csrf() : '' },
        body: JSON.stringify(payload())
      })
        .then(function (res) {
          return res.json().then(function (json) {
            if (!res.ok) throw new Error(json.error || 'Error al enviar');
            return json;
          });
        })
        .then(function () {
          showStatus('success');
          form.reset();
          submitted = false;
          Object.keys(config.fields).forEach(function (name) { setError(name, ''); });
        })
        .catch(function () { showStatus('error'); })
        .then(function () { setBusy(false); });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-tabs]').forEach(initTabs);
    document.querySelectorAll('[data-gallery]').forEach(initGallery);
    document.querySelectorAll('[data-carrusel]').forEach(initCarrusel);
    document.querySelectorAll('[data-accordion]').forEach(initAccordion);
    document.querySelectorAll('[data-viati-form]').forEach(initForm);
  });
})();
