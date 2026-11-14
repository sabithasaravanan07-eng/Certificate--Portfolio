// Sabitha's Certificate Portfolio: small, dependency-free behaviour.
(function () {
  'use strict';

  // Mobile menu
  var nav = document.querySelector('[data-nav]');
  var toggle = document.querySelector('[data-nav-toggle]');
  if (nav && toggle) {
    toggle.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  }

  // Filters apply as soon as a dropdown changes
  document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
    el.addEventListener('change', function () { el.form.submit(); });
  });

  // Confirm before destructive admin actions
  document.querySelectorAll('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!window.confirm(f.getAttribute('data-confirm'))) e.preventDefault();
    });
  });

  // Copy the site link
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var t = document.createElement('textarea');
    t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); } finally { document.body.removeChild(t); }
    return Promise.resolve();
  }
  document.querySelectorAll('[data-copy-link]').forEach(function (b) {
    b.addEventListener('click', function () {
      var label = b.textContent;
      copyText(b.getAttribute('data-copy-link')).then(function () {
        b.textContent = 'Link copied';
        setTimeout(function () { b.textContent = label; }, 2000);
      });
    });
  });

  // Certificate preview dialog
  var dataEl = document.getElementById('cert-data');
  var dlg = document.getElementById('preview');
  if (!dataEl || !dlg || typeof dlg.showModal !== 'function') return;

  var certs = {};
  JSON.parse(dataEl.textContent).forEach(function (c) { certs[c.id] = c; });
  var $ = function (id) { return document.getElementById(id); };
  var current = null, lastFocus = null;

  function show(el, on) { el.hidden = !on; }

  function openCert(id, opener) {
    var c = certs[id];
    if (!c) return;
    current = c; lastFocus = opener || null;
    $('pv-cat').textContent = c.category;
    $('pv-title').textContent = c.title;
    $('pv-issuer').textContent = c.issuer;
    $('pv-date').textContent = c.date_display;
    $('pv-duration').textContent = c.duration;
    show($('pv-duration-row'), !!c.duration);

    var skills = $('pv-skills'); skills.textContent = '';
    c.skills.forEach(function (s) { var li = document.createElement('li'); li.textContent = s; skills.appendChild(li); });
    show($('pv-skills-wrap'), c.skills.length > 0);
    $('pv-desc').textContent = c.description; show($('pv-desc'), !!c.description);

    var media = $('pv-media'); media.textContent = '';
    if (c.is_pdf) {
      var f = document.createElement('iframe');
      f.src = c.file_url; f.title = 'Preview of ' + c.title; media.appendChild(f);
    } else {
      var img = document.createElement('img');
      img.src = c.file_url; img.alt = 'Certificate: ' + c.title; media.appendChild(img);
    }
    $('pv-download').href = c.download_url;
    $('pv-open').href = c.file_url;
    var v = $('pv-verify'); v.href = c.verification_url || '#'; show(v, !!c.verification_url);
    $('pv-status').textContent = '';
    if (!dlg.open) dlg.showModal();
    history.replaceState(null, '', '#cert-' + id);
  }

  function closeCert() {
    if (dlg.open) dlg.close();
  }
  dlg.addEventListener('close', function () {
    $('pv-media').textContent = '';
    history.replaceState(null, '', location.pathname + location.search);
    if (lastFocus) lastFocus.focus();
  });
  dlg.addEventListener('click', function (e) { if (e.target === dlg) closeCert(); });
  dlg.querySelector('[data-close]').addEventListener('click', closeCert);

  document.querySelectorAll('[data-cert]').forEach(function (card) {
    card.addEventListener('click', function () { openCert(card.getAttribute('data-cert'), card); });
  });

  $('pv-share').addEventListener('click', function () {
    if (!current) return;
    var url = location.origin + '/certificates#cert-' + current.id;
    var status = $('pv-status');
    if (navigator.share) {
      navigator.share({ title: current.title, url: url }).catch(function () {});
    } else {
      copyText(url).then(function () { status.textContent = 'Link to this certificate copied.'; });
    }
  });

  // Open a certificate straight from a shared link such as /certificates#cert-7
  var m = location.hash.match(/^#cert-(\d+)$/);
  if (m) openCert(m[1]);
  window.addEventListener('hashchange', function () {
    var h = location.hash.match(/^#cert-(\d+)$/);
    if (h) openCert(h[1]);
  });
})();
