/* Just Enough: progressive enhancement only. All calculations and saving happen on the server. */
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var csrf = function () { var i = $('input[name="csrf_token"]'); return i ? i.value : ''; };
  var money = function (cur, v) { return v === null || v === undefined ? '–' : cur + Math.round(v).toLocaleString(); };
  var fmt = function (v, d) { return Number(v).toLocaleString(undefined, { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); };

  /* ---- navigation toggle ---- */
  $$('[data-nav-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var open = document.body.classList.toggle('nav-open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
  });

  /* ---- confirmation dialog for destructive actions ---- */
  var dialog = $('#confirm-dialog');
  var pending = null;
  function askConfirm(el, proceed) {
    if (!dialog || typeof dialog.showModal !== 'function') { if (window.confirm(el.getAttribute('data-confirm'))) proceed(); return; }
    $('#confirm-title').textContent = el.getAttribute('data-confirm-title') || 'Please confirm';
    $('#confirm-text').textContent = el.getAttribute('data-confirm');
    $('#confirm-ok').textContent = el.getAttribute('data-confirm-ok') || 'Confirm';
    pending = proceed;
    dialog.showModal();
  }
  if (dialog) {
    dialog.addEventListener('close', function () {
      if (dialog.returnValue === 'ok' && pending) pending();
      pending = null; dialog.returnValue = '';
    });
  }
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button[data-confirm]');
    if (btn && !btn.dataset.confirmed) {
      e.preventDefault();
      var form = btn.form;
      askConfirm(btn, function () {
        btn.dataset.confirmed = '1';
        if (form.requestSubmit) form.requestSubmit(btn); else btn.click();
      });
    }
  });
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.hasAttribute('data-confirm') && !form.dataset.confirmed) {
      e.preventDefault();
      askConfirm(form, function () { form.dataset.confirmed = '1'; form.submit(); });
    }
  });

  /* ---- print buttons ---- */
  $$('[data-print]').forEach(function (b) { b.addEventListener('click', function () { window.print(); }); });

  /* ---- client-side hints for forms (server still validates) ---- */
  $$('form[data-validate]').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      var bad = $$('input,select,textarea', form).filter(function (f) { return !f.checkValidity(); });
      if (bad.length) { e.preventDefault(); bad[0].focus(); bad[0].reportValidity(); }
    });
  });

  /* ---- shared preview call ---- */
  function preview(url, payload) {
    return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf() }, body: JSON.stringify(payload) })
      .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); });
  }
  function debounce(fn, ms) { var t; return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); }; }

  /* ---- charts ---- */
  function renderDishBars(el, dishes) {
    if (!el) return;
    var peak = Math.max.apply(null, dishes.map(function (d) { return d.recommended_kg; }).concat([0.001]));
    el.innerHTML = '';
    dishes.forEach(function (d) {
      var row = document.createElement('div'); row.className = 'bar-row';
      var label = document.createElement('span'); label.className = 'bar-label'; label.textContent = d.name;
      var track = document.createElement('div'); track.className = 'bar-track';
      var a = document.createElement('div'); a.className = 'bar-fill'; a.style.width = (d.recommended_kg / peak * 100).toFixed(1) + '%';
      var b = document.createElement('div'); b.className = 'bar-fill bar-fill-alt'; b.style.width = (d.expected_leftover_kg / peak * 100).toFixed(1) + '%';
      track.appendChild(a); track.appendChild(b);
      var val = document.createElement('span'); val.className = 'bar-value'; val.textContent = fmt(d.recommended_kg, 1) + ' / ' + fmt(d.expected_leftover_kg, 1);
      row.appendChild(label); row.appendChild(track); row.appendChild(val); el.appendChild(row);
    });
  }
  function renderCurve(el, curve) {
    if (!el) return;
    var W = 520, H = 220, P = 36;
    var maxY = Math.max.apply(null, curve.map(function (c) { return c.recommended_kg; })) * 1.05 || 1;
    var minX = curve[0].risk_pct, maxX = curve[curve.length - 1].risk_pct;
    var x = function (v) { return P + (v - minX) / ((maxX - minX) || 1) * (W - P * 2); };
    var y = function (v) { return H - P - v / maxY * (H - P * 2); };
    var pts = function (k) { return curve.map(function (c) { return x(c.risk_pct).toFixed(1) + ',' + y(c[k]).toFixed(1); }).join(' '); };
    var s = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="curve-svg" focusable="false">';
    s += '<line class="axis" x1="' + P + '" y1="' + (H - P) + '" x2="' + (W - P) + '" y2="' + (H - P) + '"/><line class="axis" x1="' + P + '" y1="' + P + '" x2="' + P + '" y2="' + (H - P) + '"/>';
    s += '<polyline class="line-main" fill="none" points="' + pts('recommended_kg') + '"/><polyline class="line-alt" fill="none" points="' + pts('expected_leftover_kg') + '"/>';
    curve.forEach(function (c) {
      s += '<circle class="pt' + (c.selected ? ' pt-sel' : '') + '" r="' + (c.selected ? 6 : 3.5) + '" cx="' + x(c.risk_pct).toFixed(1) + '" cy="' + y(c.recommended_kg).toFixed(1) + '"/>';
      s += '<circle class="pt-alt' + (c.selected ? ' pt-sel' : '') + '" r="' + (c.selected ? 6 : 3.5) + '" cx="' + x(c.risk_pct).toFixed(1) + '" cy="' + y(c.expected_leftover_kg).toFixed(1) + '"/>';
      s += '<text class="tick" x="' + x(c.risk_pct).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle">' + c.risk_pct + '%</text>';
    });
    s += '<text class="tick" x="6" y="' + (P + 4) + '">' + fmt(maxY, 0) + ' kg</text></svg>';
    el.innerHTML = s;
  }
  function showWarnings(el, list) {
    if (!el) return;
    el.innerHTML = '';
    list.forEach(function (w) { var d = document.createElement('div'); d.className = 'alert alert-warning'; d.textContent = w; el.appendChild(d); });
  }
  function initial() { var n = $('#initial-result'); return n ? JSON.parse(n.textContent) : null; }

  /* ---- planner page: live recalculation ---- */
  var planner = $('#planner-form');
  if (planner && $('[data-ed]')) {
    var cur = planner.getAttribute('data-currency') || '';
    var status = $('#live-status');
    var apply = function (res) {
      res.dishes.forEach(function (d) {
        var row = $('[data-ed="' + d.event_dish_id + '"]');
        if (!row) return;
        $('[data-out="rec_servings"]', row).textContent = d.recommended_servings;
        $('[data-out="rec_kg"]', row).textContent = fmt(d.recommended_kg, 2);
        $('[data-out="leftover_kg"]', row).textContent = fmt(d.expected_leftover_kg, 2);
        $('[data-out="cost"]', row).textContent = money(cur, d.food_cost);
        var ex = $('[data-explain="' + d.event_dish_id + '"]'); if (ex) ex.textContent = d.explanation;
      });
      var t = res.totals;
      $('[data-total="servings"]').textContent = fmt(t.recommended_servings);
      $('[data-total="kg"]').textContent = fmt(t.recommended_kg, 2);
      $('[data-total="leftover"]').textContent = fmt(t.expected_leftover_kg, 2);
      $('[data-total="cost"]').textContent = money(cur, t.food_cost);
      $('#out-attendance').textContent = fmt(res.attendance.estimated_attendance) + ' (~' + fmt(res.attendance.attendance_low) + '–' + fmt(res.attendance.attendance_high) + ')';
      $('#out-kg').textContent = fmt(t.recommended_kg, 1) + ' kg';
      $('#out-leftover').textContent = fmt(t.expected_leftover_kg, 1) + ' kg';
      $('#out-cost').textContent = t.food_cost === null ? 'No cost data' : money(cur, t.food_cost);
      $('#out-surplus-cost').textContent = t.surplus_cost === null ? 'No cost data' : money(cur, t.surplus_cost);
      renderDishBars($('#chart-dishes'), res.dishes);
      showWarnings($('#warnings'), res.warnings);
    };
    var run = debounce(function () {
      var payload = {};
      $$('[data-live]', planner).forEach(function (i) { payload[i.name] = i.value; });
      if (status) status.textContent = 'Recalculating…';
      preview(planner.getAttribute('data-preview-url'), payload).then(function (r) {
        $$('.live-error', planner).forEach(function (n) { n.remove(); });
        if (r.status === 200 && r.body.ok) { apply(r.body.result); if (status) status.textContent = 'Preview updated. Save to keep these values.'; }
        else if (status) { status.textContent = 'Some values are invalid: ' + Object.keys(r.body.errors || {}).map(function (k) { return r.body.errors[k]; }).join(' '); }
      }).catch(function () { if (status) status.textContent = 'Could not reach the server for a live preview. You can still save.'; });
    }, 250);
    planner.addEventListener('input', function (e) { if (e.target.hasAttribute('data-live')) run(); });
    var init = initial(); if (init) { renderDishBars($('#chart-dishes'), init.dishes); }
  }

  /* ---- risk explorer ---- */
  var panel = $('#risk-panel');
  if (panel) {
    var cur2 = panel.getAttribute('data-currency') || '';
    var slider = $('#risk-slider'), saved = parseFloat(panel.getAttribute('data-saved'));
    var init2 = initial(); var baseKg = init2 ? init2.totals.recommended_kg : null;
    var baseLeft = init2 ? init2.totals.expected_leftover_kg : null;
    if (init2) renderCurve($('#chart-curve'), init2.curve);
    var go = debounce(function () {
      var v = slider.value;
      $('#risk-label').textContent = v + '%'; $('#risk-apply-value').value = v;
      preview(panel.getAttribute('data-preview-url'), { shortage_risk_pct: v }).then(function (r) {
        if (!r.body.ok) return;
        var res = r.body.result, t = res.totals;
        $('#r-kg').textContent = fmt(t.recommended_kg, 1) + ' kg';
        $('#r-leftover').textContent = fmt(t.expected_leftover_kg, 1) + ' kg';
        $('#r-cost').textContent = t.food_cost === null ? 'No cost data' : money(cur2, t.food_cost);
        $('#r-surplus').textContent = t.surplus_cost === null ? 'No cost data' : money(cur2, t.surplus_cost);
        renderCurve($('#chart-curve'), res.curve);
        showWarnings($('#warnings'), res.warnings);
        $$('#curve-table tbody tr').forEach(function (tr) { tr.classList.toggle('is-selected', parseFloat(tr.getAttribute('data-risk')) === parseFloat(v)); });
        if (baseKg !== null) {
          var dk = t.recommended_kg - baseKg, dl = t.expected_leftover_kg - baseLeft;
          $('#r-delta').textContent = parseFloat(v) === saved ? 'This is the saved setting.' :
            'Compared with the saved ' + saved + '% setting: ' + (dk >= 0 ? '+' : '') + fmt(dk, 1) + ' kg of food and ' + (dl >= 0 ? '+' : '') + fmt(dl, 1) + ' kg of expected leftover. Not saved until you apply it.';
        }
      });
    }, 150);
    slider.addEventListener('input', go);
  }

  /* ---- donation form: holding-window guidance (display only; server re-checks) ---- */
  var prep = $('#prepared_at'), dead = $('#handoff_deadline'), note = $('#window-note');
  if (prep && dead && note) {
    var upd = function () {
      if (!prep.value || !dead.value) { note.hidden = true; return; }
      var h = (new Date(dead.value) - new Date(prep.value)) / 36e5;
      note.hidden = false; note.className = 'alert';
      if (h <= 0) { note.classList.add('alert-error'); note.textContent = 'The handoff deadline must be after the preparation time.'; }
      else if (h <= 2) { note.classList.add('alert-success'); note.textContent = 'Holding window ' + h.toFixed(1) + ' h. Short window; keep food hot or chilled. (General guidance only.)'; }
      else if (h <= 4) { note.classList.add('alert-warning'); note.textContent = 'Holding window ' + h.toFixed(1) + ' h. Over 2 hours: take extra care with temperature control. (General guidance only.)'; }
      else { note.classList.add('alert-error'); note.textContent = 'Holding window ' + h.toFixed(1) + ' h. Over 4 hours: many guidelines advise against donating perishable cooked food held this long. (General guidance only.)'; }
    };
    prep.addEventListener('input', upd); dead.addEventListener('input', upd); upd();
  }

  /* ---- success toast for flashes ---- */
  $$('.alert-success').forEach(function (a) { a.setAttribute('role', 'status'); });
})();
