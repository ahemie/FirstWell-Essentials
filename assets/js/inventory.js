// FirstWell Essentials — Inventory Update (section 3).
// Staff scan a product barcode, then count stock / stock in / stock out.
// Talks to the existing Supabase inv_* functions with the staff member's own Supabase Auth login.
// The Flask dashboard login only protects this page; inv_* functions check inv_staff themselves.
(function () {
  'use strict';
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var esc = function (s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); };
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var KEY_TOKEN = 'fs-inv-token-v1', KEY_QUEUE = 'fs-inv-queue-v1';
  var REASONS_COUNT = ['Miscount', 'Damaged', 'Expired', 'Not recorded', 'Used / dispensed', 'Other'];
  var REASONS_OUT = ['Used / dispensed', 'Sold - Shopee MY', 'Sold - Shopee SG', 'Sold - TikTok', 'Sold - Clinic', 'Damaged', 'Expired', 'Sample', 'Other'];

  var cfg = null, tok = null, me = null;
  var products = [], byId = new Map(), byBarcode = new Map();
  var mode = 'count', blind = true, sel = null, pendingBarcode = null, pendingRelink = false, scanned = null;
  var queue = [];

  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16);
    });
  }
  function fmtDate(d) {
    if (!d) return 'No expiry';
    var p = String(d).split('-'); if (p.length !== 3) return d;
    return +p[2] + ' ' + MONTHS[+p[1] - 1] + ' ' + p[0];
  }
  function num(v) { return Number(v) || 0; }
  function fmtQty(v) { return String(Math.round(num(v) * 100) / 100); }
  var toastTimer;
  function toast(msg, bad) {
    var t = $('#toast'); t.textContent = msg; t.className = 'iv-toast' + (bad ? ' bad' : ''); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, bad ? 6000 : 3000);
  }

  // ---------- Supabase (login + RPC) ----------
  function setToken(j) {
    tok = { access: j.access_token, refresh: j.refresh_token, exp: Date.now() + (j.expires_in || 3600) * 1000 };
    try { localStorage.setItem(KEY_TOKEN, JSON.stringify(tok)); } catch (e) { /* private mode */ }
  }
  function clearToken() { tok = null; me = null; try { localStorage.removeItem(KEY_TOKEN); } catch (e) { } }
  async function authCall(grant, body) {
    var r = await fetch(cfg.url + '/auth/v1/token?grant_type=' + grant, {
      method: 'POST', headers: { apikey: cfg.key, 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(j.error_description || j.msg || 'Sign-in failed');
    setToken(j);
  }
  async function refreshToken() {
    if (!tok || !tok.refresh) throw new Error('Please sign in again.');
    try { await authCall('refresh_token', { refresh_token: tok.refresh }); }
    catch (e) { clearToken(); throw new Error('Your session ended. Please sign in again.'); }
  }
  async function rpc(name, args) {
    if (!tok) throw new Error('Please sign in again.');
    if (Date.now() > tok.exp - 60000) await refreshToken();
    function call() {
      return fetch(cfg.url + '/rest/v1/rpc/' + name, {
        method: 'POST',
        headers: { apikey: cfg.key, Authorization: 'Bearer ' + tok.access, 'Content-Type': 'application/json' },
        body: JSON.stringify(args || {})
      });
    }
    var r = await call();
    if (r.status === 401) { await refreshToken(); r = await call(); }
    var j = await r.json().catch(function () { return null; });
    if (!r.ok) throw new Error((j && (j.message || j.error_description)) || 'Request failed (' + r.status + ')');
    return j;
  }

  // ---------- products ----------
  async function loadProducts() {
    var list = await rpc('inv_products');
    products = list || [];
    byId = new Map(); byBarcode = new Map();
    products.forEach(function (p) {
      byId.set(p.id, p);
      (p.barcodes || []).forEach(function (b) { byBarcode.set(String(b).toLowerCase(), p); });
    });
    var linked = products.filter(function (p) { return (p.barcodes || []).length; }).length;
    $('#coverage').textContent = linked + ' of ' + products.length + ' products have a barcode linked. ' +
      (linked < products.length ? 'The first time you scan an unknown barcode, pick the product once and it is remembered.' : '');
  }
  function search(q) {
    q = q.trim().toLowerCase(); if (!q) return [];
    var words = q.split(/\s+/);
    return products.filter(function (p) {
      var hay = (p.name + ' ' + (p.code || '') + ' ' + (p.category || '') + ' ' + (p.barcodes || []).join(' ')).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    }).slice(0, 8);
  }
  function looksLikeBarcode(q) { return /^\d{6,}$/.test(q) || (/^[A-Za-z0-9\-_.]{8,}$/.test(q) && /\d/.test(q)); }

  function renderHits(list) {
    $('#hits').innerHTML = list.map(function (p) {
      return '<button type="button" class="iv-hit" role="option" data-id="' + esc(p.id) + '"><span>' + esc(p.name) +
        '<small>' + esc(p.category || '') + (p.code ? ' · ' + esc(p.code) : '') + ((p.barcodes || []).length ? ' · ▮ ' + esc(p.barcodes.join(', ')) : ' · no barcode yet') + '</small></span><span class="iv-muted">' +
        (blind && mode === 'count' ? '' : fmtQty(p.total) + ' ' + esc(p.unit || '')) + '</span></button>';
    }).join('');
  }
  function setBanner() {
    var b = $('#linkBanner');
    if (!pendingBarcode) { b.hidden = true; $('#scan').placeholder = 'Scan barcode or type product name, then Enter'; return; }
    b.hidden = false;
    b.innerHTML = '<span>' + (pendingRelink ? 'Fixing barcode ' : 'New barcode ') + '<b>' + esc(pendingBarcode) + '</b> — search for the ' + (pendingRelink ? 'correct ' : '') + 'product it belongs to and tap it.</span>' +
      '<button type="button" class="iv-btn" id="linkCancel">Cancel</button>';
    $('#linkCancel').onclick = function () { pendingBarcode = null; pendingRelink = false; setBanner(); $('#scan').focus(); };
    $('#scan').placeholder = 'Type the product name to link this barcode';
  }

  async function onScanEnter() {
    var input = $('#scan'), q = input.value.trim(); if (!q) return;
    var exact = byBarcode.get(q.toLowerCase());
    if (exact && !pendingBarcode) { input.value = ''; renderHits([]); return openProduct(exact, q); }
    var hits = search(q);
    if (pendingBarcode) { if (hits.length === 1) return chooseProduct(hits[0]); return; }
    if (!hits.length && looksLikeBarcode(q)) {
      pendingBarcode = q; input.value = ''; renderHits([]); setBanner(); return;
    }
    if (hits.length === 1) { input.value = ''; renderHits([]); return openProduct(hits[0], null); }
    if (!hits.length) toast('No product found for “' + q + '”', true);
  }
  async function chooseProduct(p) {
    var code = null;
    if (pendingBarcode) {
      code = pendingBarcode;
      try {
        var forced = pendingRelink;
        try { await rpc('inv_barcode_link', { p_barcode: pendingBarcode, p_product: p.id, p_force: forced }); }
        catch (e) {
          var m = /ALREADY_LINKED\|(.*)/.exec(e.message || '');
          if (!m) throw e;
          if (!confirm('This barcode is already linked to:\n' + m[1] + '\n\nMove it to ' + p.name + '?')) return toast('Barcode not changed.');
          await rpc('inv_barcode_link', { p_barcode: pendingBarcode, p_product: p.id, p_force: true }); forced = true;
        }
        if (forced) { await loadProducts(); p = byId.get(p.id) || p; }
        else { (p.barcodes = p.barcodes || []).push(pendingBarcode); byBarcode.set(pendingBarcode.toLowerCase(), p); }
        toast('Barcode linked to ' + p.name);
      } catch (e) { return toast(e.message, true); }
      pendingBarcode = null; pendingRelink = false; setBanner();
    }
    $('#scan').value = ''; renderHits([]); openProduct(p, code);
  }

  // ---------- product panel ----------
  function openProduct(p, code) {
    sel = p; scanned = code || null; renderPanel();
    var first = $('#panel input'); if (first) { first.focus(); }
    $('#panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function batchRow(exp, sys, isNew) {
    var left = isNew
      ? '<input type="date" class="iv-newexp" aria-label="Expiry date">'
      : '<span class="iv-exp">' + esc(fmtDate(exp)) + '</span>' + (blind ? '' : '<span class="iv-sys">System: ' + fmtQty(sys) + '</span>');
    return '<div class="iv-brow" data-exp="' + esc(exp || '') + '" data-sys="' + esc(sys) + '"' + (isNew ? ' data-new="1"' : '') + '>' +
      '<div>' + left + '</div><input type="number" class="iv-cnt" inputmode="decimal" min="0" step="any" placeholder="Count" aria-label="Counted quantity"></div>';
  }
  function panelHead(p) {
    return '<div class="iv-prod"><h2>' + esc(p.name) + '</h2><span class="iv-muted iv-small">' + esc(p.category || '') +
      (p.code ? ' · ' + esc(p.code) : '') + (p.unit ? ' · unit: ' + esc(p.unit) : '') +
      (p.last_counted ? ' · last counted ' + esc(fmtDate(p.last_counted)) : ' · never counted') + '</span>' +
      '<div class="iv-small iv-muted">Barcode: ' + ((p.barcodes || []).length ? '<b>' + esc(p.barcodes.join(', ')) + '</b>' : 'none linked yet') + '</div>' +
      (scanned ? '<div class="iv-small iv-muted">Scanned barcode <b>' + esc(scanned) + '</b> · <button type="button" class="iv-link" id="relink">Not this product? Fix it</button></div>' : '') + '</div>';
  }
  function reasonOptions(list) { return '<option value="">Choose reason…</option>' + list.map(function (r) { return '<option>' + esc(r) + '</option>'; }).join(''); }

  function renderPanel() {
    var box = $('#panel'), p = sel;
    if (mode === 'recent') { box.hidden = true; return; }
    if (!p) { box.hidden = true; box.innerHTML = ''; return; }
    box.hidden = false;
    var html = panelHead(p);
    var batches = p.batches || [];
    if (mode === 'count') {
      html += '<p class="iv-muted iv-small">Count what is physically on the shelf for each expiry date.' +
        (blind ? ' System quantity is hidden.' : '') + '</p>';
      html += batches.length ? batches.map(function (b) { return batchRow(b.expiry, b.qty, false); }).join('') : batchRow('', 0, true);
      html += '<div class="iv-actions">' +
        '<button type="button" class="iv-btn" id="addExp">+ Another expiry date</button>' +
        (blind ? '' : '<button type="button" class="iv-btn" id="same">Same as system</button>') +
        '<button type="button" class="iv-btn iv-primary" id="addToList">Add to count list</button>' +
        '<button type="button" class="iv-btn" id="closePanel">Cancel</button></div>';
    } else if (mode === 'in') {
      html += '<div class="iv-fields">' +
        '<label>Quantity received<input type="number" id="inQty" inputmode="decimal" min="0" step="any"></label>' +
        '<label>Expiry date<select id="inExpSel">' + batches.map(function (b) { return '<option value="' + esc(b.expiry || '') + '">' + esc(fmtDate(b.expiry)) + ' (have ' + fmtQty(b.qty) + ')</option>'; }).join('') +
        '<option value="__new">New expiry date…</option></select></label>' +
        '<label id="inNewWrap"' + (batches.length ? ' hidden' : '') + '>New expiry<input type="date" id="inExpNew"></label>' +
        '<label>Note (optional)<input type="text" id="inNote" maxlength="200"></label></div>' +
        '<div class="iv-actions"><button type="button" class="iv-btn iv-primary" id="doIn">Add stock</button><button type="button" class="iv-btn" id="closePanel">Cancel</button></div>';
    } else if (mode === 'out') {
      html += '<p class="iv-muted iv-small">Total in stock: <b>' + fmtQty(p.total) + '</b> ' + esc(p.unit || '') + '. Earliest expiry is used first unless you pick a batch.</p>' +
        '<div class="iv-fields">' +
        '<label>Quantity out<input type="number" id="outQty" inputmode="decimal" min="0" step="any"></label>' +
        '<label>Reason<select id="outReason">' + reasonOptions(REASONS_OUT) + '</select></label>' +
        '<label>Batch<select id="outBatch"><option value="">Earliest expiry first</option>' +
        batches.map(function (b) { return '<option value="' + esc(b.expiry || '') + '|1">' + esc(fmtDate(b.expiry)) + ' (have ' + fmtQty(b.qty) + ')</option>'; }).join('') + '</select></label>' +
        '<label>Note (optional)<input type="text" id="outNote" maxlength="200"></label></div>' +
        '<div class="iv-actions"><button type="button" class="iv-btn iv-primary" id="doOut">Remove stock</button><button type="button" class="iv-btn" id="closePanel">Cancel</button></div>';
    }
    box.innerHTML = html;
    bindPanel();
  }

  function bindPanel() {
    var box = $('#panel');
    var on = function (id, fn) { var el = $(id, box); if (el) el.onclick = fn; };
    on('#relink', function () {
      if (!scanned) return;
      pendingBarcode = scanned; pendingRelink = true; sel = null; renderPanel(); setBanner(); $('#scan').value = ''; $('#scan').focus();
    });
    on('#closePanel', function () { sel = null; renderPanel(); $('#scan').focus(); });
    on('#addExp', function () {
      var rows = $$('.iv-brow', box), last = rows[rows.length - 1];
      last.insertAdjacentHTML('afterend', batchRow('', 0, true));
      var d = $$('.iv-newexp', box).pop(); if (d) d.focus();
    });
    on('#same', function () { $$('.iv-brow', box).forEach(function (r) { if (!r.dataset.new) $('.iv-cnt', r).value = r.dataset.sys; }); });
    on('#addToList', addToQueue);
    on('#doIn', doStockIn);
    on('#doOut', doStockOut);
    var sel2 = $('#inExpSel', box);
    if (sel2) sel2.onchange = function () { $('#inNewWrap', box).hidden = sel2.value !== '__new'; };
    box.onkeydown = function (e) {
      if (e.key === 'Enter' && e.target.tagName === 'INPUT') {
        e.preventDefault();
        var btn = $('#addToList', box) || $('#doIn', box) || $('#doOut', box); if (btn) btn.click();
      }
    };
  }

  // ---------- count queue ----------
  function saveQueue() { try { localStorage.setItem(KEY_QUEUE, JSON.stringify(queue)); } catch (e) { } }
  function loadQueue() { try { queue = JSON.parse(localStorage.getItem(KEY_QUEUE) || '[]') || []; } catch (e) { queue = []; } }
  function batchQty(p, exp) { var b = (p.batches || []).filter(function (x) { return (x.expiry || '') === (exp || ''); })[0]; return b ? num(b.qty) : 0; }

  function addToQueue() {
    var p = sel, added = 0, bad = false;
    $$('.iv-brow', $('#panel')).forEach(function (r) {
      var raw = $('.iv-cnt', r).value.trim(); if (raw === '') return;
      var n = Number(raw); if (!isFinite(n) || n < 0) { bad = true; return; }
      var exp = r.dataset.new ? ($('.iv-newexp', r).value || '') : (r.dataset.exp || '');
      var key = p.id + '|' + exp;
      queue = queue.filter(function (q) { return q.key !== key; });
      queue.push({ key: key, cid: uuid(), pid: p.id, name: p.name, unit: p.unit || '', exp: exp, counted: n, sys: batchQty(p, exp), reason: '' });
      added++;
    });
    if (bad) return toast('Counts must be 0 or more.', true);
    if (!added) return toast('Type a count first.', true);
    saveQueue(); sel = null; renderPanel(); renderQueue(); $('#scan').focus();
    toast('Added ' + added + ' line' + (added > 1 ? 's' : '') + ' to the count list');
  }
  function renderQueue() {
    var box = $('#queueBox'); box.hidden = !queue.length || mode !== 'count';
    $('#qCount').textContent = queue.length;
    var need = queue.filter(function (q) { return q.counted !== q.sys && !q.reason; }).length;
    $('#qSubmit').disabled = !queue.length || need > 0;
    $('#qSubmit').textContent = need ? need + ' need a reason' : 'Save all counts';
    $('#qTable').className = 'iv-table iv-stack'; $('#qTable').innerHTML = '<thead><tr><th>Product</th><th>Expiry</th><th class="n">System</th><th class="n">Counted</th><th class="n">Diff</th><th>Reason</th><th></th></tr></thead><tbody>' +
      queue.map(function (q, i) {
        var d = q.counted - q.sys;
        var reason = d === 0 ? '<span class="iv-muted">Matches</span>' :
          '<select data-i="' + i + '" class="iv-qreason' + (q.reason ? '' : ' iv-need') + '" aria-label="Reason">' +
          reasonOptions(REASONS_COUNT).replace('<option>' + esc(q.reason) + '</option>', '<option selected>' + esc(q.reason) + '</option>') + '</select>';
        return '<tr><td class="iv-main">' + esc(q.name) + '</td><td data-l="Expiry">' + esc(fmtDate(q.exp)) + '</td><td class="n" data-l="System">' + fmtQty(q.sys) + '</td><td class="n" data-l="Counted">' + fmtQty(q.counted) +
          '</td><td class="n ' + (d < 0 ? 'iv-neg' : d > 0 ? 'iv-pos' : '') + '" data-l="Diff">' + (d > 0 ? '+' : '') + fmtQty(d) + '</td><td data-l="Reason">' + reason +
          '</td><td class="iv-del"><button type="button" class="iv-x" data-del="' + i + '" aria-label="Remove line">×</button></td></tr>';
      }).join('') + '</tbody>';
  }
  async function submitQueue() {
    var btn = $('#qSubmit'); btn.disabled = true;
    try {
      var items = queue.map(function (q) {
        return { client_id: q.cid, product_id: q.pid, expiry: q.exp || '', counted: q.counted, reason: q.reason || '' };
      });
      await rpc('inv_count_many', { p_items: items });
      var rows = queue.slice(); queue = []; saveQueue();
      showReport(rows);
      await loadProducts();
      renderQueue(); toast('Counts saved');
    } catch (e) { toast(e.message, true); renderQueue(); }
  }

  // ---------- variance report + Avixo key-in list ----------
  function showReport(rows) {
    var diffs = rows.filter(function (r) { return r.counted !== r.sys; }).sort(function (a, b) { return Math.abs(b.counted - b.sys) - Math.abs(a.counted - a.sys); });
    var box = $('#report'); box.hidden = false;
    var when = new Date().toLocaleString('en-MY');
    box.innerHTML = '<div class="iv-row"><h2>Count result — ' + rows.length + ' lines, ' + diffs.length + ' differ</h2><span class="iv-muted iv-small">' + esc(when) + '</span></div>' +
      (diffs.length ? '<p class="iv-muted iv-small">Key these adjustments into Avixo so it matches the shelf. Everything else already matches.</p>' +
        '<div class="iv-scroll"><table class="iv-table iv-stack"><thead><tr><th>Product</th><th>Expiry</th><th class="n">Avixo / system</th><th class="n">Physical</th><th class="n">Adjust by</th><th>Reason</th><th>Done</th></tr></thead><tbody>' +
        diffs.map(function (r) {
          var d = r.counted - r.sys;
          return '<tr><td class="iv-main">' + esc(r.name) + '</td><td data-l="Expiry">' + esc(fmtDate(r.exp)) + '</td><td class="n" data-l="Avixo / system">' + fmtQty(r.sys) + '</td><td class="n" data-l="Physical">' + fmtQty(r.counted) +
            '</td><td class="n ' + (d < 0 ? 'iv-neg' : 'iv-pos') + '" data-l="Adjust by">' + (d > 0 ? '+' : '') + fmtQty(d) + '</td><td data-l="Reason">' + esc(r.reason) + '</td><td data-l="Keyed into Avixo"><input type="checkbox" class="iv-tick" aria-label="Keyed into Avixo"></td></tr>';
        }).join('') + '</tbody></table></div>' +
        '<div class="iv-actions"><button type="button" class="iv-btn iv-primary" id="csv">Download CSV</button><button type="button" class="iv-btn" id="print">Print</button><button type="button" class="iv-btn" id="hideReport">Close</button></div>'
        : '<p>All counted lines match the system. 🎉</p><div class="iv-actions"><button type="button" class="iv-btn" id="hideReport">Close</button></div>');
    box._rows = diffs;
    var c = $('#csv', box); if (c) c.onclick = function () { downloadCsv(diffs); };
    var pr = $('#print', box); if (pr) pr.onclick = function () { window.print(); };
    $('#hideReport', box).onclick = function () { box.hidden = true; };
    box.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function csvCell(v) {
    if (typeof v === 'number') return String(v);
    v = String(v == null ? '' : v); if (/^[=+\-@\t\r]/.test(v)) v = "'" + v; // stop spreadsheet formula injection
    return '"' + v.replace(/"/g, '""') + '"';
  }
  function downloadCsv(rows) {
    var head = ['Product', 'Expiry', 'Avixo/system qty', 'Physical qty', 'Adjust by', 'Reason'];
    var lines = [head.map(csvCell).join(',')].concat(rows.map(function (r) {
      return [r.name, r.exp, r.sys, r.counted, r.counted - r.sys, r.reason].map(csvCell).join(',');
    }));
    var blob = new Blob(['﻿' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = 'avixo-adjustments-' + new Date().toISOString().slice(0, 10) + '.csv';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  // ---------- stock in / out ----------
  async function doStockIn() {
    var p = sel, qty = Number($('#inQty').value), s = $('#inExpSel').value;
    var exp = s === '__new' ? $('#inExpNew').value : s;
    if (!(qty > 0)) return toast('Enter the quantity received.', true);
    try {
      var r = await rpc('inv_stock_in', { p_product: p.id, p_qty: qty, p_expiry: exp || null, p_note: $('#inNote').value, p_client: uuid() });
      toast('Added ' + fmtQty(qty) + ' to ' + p.name + (r && r.new_qty != null ? ' (batch now ' + fmtQty(r.new_qty) + ')' : ''));
      await loadProducts(); sel = null; renderPanel(); $('#scan').focus();
    } catch (e) { toast(e.message, true); }
  }
  async function doStockOut() {
    var p = sel, qty = Number($('#outQty').value), reason = $('#outReason').value, b = $('#outBatch').value;
    if (!(qty > 0)) return toast('Enter the quantity to remove.', true);
    if (!reason) return toast('Choose a reason.', true);
    var pick = b !== '', exp = pick ? b.split('|')[0] : '';
    try {
      await rpc('inv_stock_out', { p_product: p.id, p_qty: qty, p_reason: reason, p_note: $('#outNote').value, p_client: uuid(), p_expiry: exp || null, p_pick: pick });
      toast('Removed ' + fmtQty(qty) + ' from ' + p.name);
      await loadProducts(); sel = null; renderPanel(); $('#scan').focus();
    } catch (e) { toast(e.message, true); }
  }

  // ---------- recent activity + undo ----------
  async function renderRecent() {
    var box = $('#recent'); box.hidden = mode !== 'recent'; if (mode !== 'recent') return;
    box.innerHTML = '<h2>Your recent updates</h2><p class="iv-muted">Loading…</p>';
    try {
      var h = await rpc('inv_history', { p_mine: true, p_limit: 40 });
      try { await loadProducts(); } catch (_) {}
      box.innerHTML = '<h2>Your recent updates</h2>' + (h.length ? '<div class="iv-scroll"><table class="iv-table iv-stack"><thead><tr><th>Product</th><th>When</th><th>Expiry</th><th class="n">Change</th><th class="n">Total stock</th><th>Reason</th><th></th></tr></thead><tbody>' +
        h.map(function (m) {
          var ch = num(m.change), pr = byId.get(m.product_id);
          return '<tr><td class="iv-main">' + esc(m.name) + ' <span class="iv-kind">' + esc(m.kind) + '</span></td><td data-l="When">' + esc(new Date(m.at).toLocaleString('en-MY')) + '</td><td data-l="Expiry">' + esc(fmtDate(m.expiry)) +
            '</td><td class="n ' + (ch < 0 ? 'iv-neg' : ch > 0 ? 'iv-pos' : '') + '" data-l="Change">' + (ch > 0 ? '+' : '') + fmtQty(ch) + '</td><td class="n" data-l="Total stock">' + (pr ? '<b>' + fmtQty(pr.total) + '</b> ' + esc(pr.unit || '') : '') + '</td><td data-l="Reason">' + esc(m.reason || '') +
            '</td><td>' + (m.undone ? '<span class="iv-muted">Undone</span>' : m.undoable ? '<button type="button" class="iv-btn" data-undo="' + esc(m.client_id) + '">Undo</button>' : '') + '</td></tr>';
        }).join('') + '</tbody></table></div>' : '<p class="iv-muted">Nothing yet.</p>');
    } catch (e) { box.innerHTML = '<h2>Your recent updates</h2><p class="iv-err">' + esc(e.message) + '</p>'; }
  }

  // ---------- barcode list ----------
  var bcFilter = 'missing', bcQuery = '';
  function renderBarcodes() {
    var box = $('#barcodes'); box.hidden = mode !== 'barcodes'; if (mode !== 'barcodes') return;
    var linked = products.filter(function (p) { return (p.barcodes || []).length; }).length;
    var words = bcQuery.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var list = products.filter(function (p) {
      var has = (p.barcodes || []).length > 0;
      if (bcFilter === 'missing' && has) return false;
      if (bcFilter === 'linked' && !has) return false;
      var hay = (p.name + ' ' + (p.code || '') + ' ' + (p.category || '') + ' ' + (p.barcodes || []).join(' ')).toLowerCase();
      return words.every(function (w) { return hay.indexOf(w) !== -1; });
    }).sort(function (a, b) { return String(a.name).localeCompare(String(b.name)); });
    var shown = list.slice(0, 200);
    function chip(k, label) { return '<button type="button" class="iv-btn' + (bcFilter === k ? ' iv-primary' : '') + '" data-bcf="' + k + '">' + label + '</button>'; }
    box.innerHTML = '<h2>Barcodes <span class="iv-pill">' + linked + ' of ' + products.length + ' linked</span></h2>' +
      '<p class="iv-muted iv-small">To link a product, go to Count stock, scan its barcode and pick the product once.</p>' +
      '<div class="iv-row" style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">' + chip('missing', 'Missing (' + (products.length - linked) + ')') + chip('linked', 'Linked (' + linked + ')') + chip('all', 'All') +
      '<input id="bcSearch" type="search" placeholder="Search product or barcode" value="' + esc(bcQuery) + '" style="flex:1;min-width:160px"></div>' +
      (shown.length ? '<div class="iv-scroll"><table class="iv-table iv-stack"><thead><tr><th>Product</th><th>Barcode</th><th></th></tr></thead><tbody>' +
        shown.map(function (p) {
          var bs = p.barcodes || [];
          return '<tr><td class="iv-main">' + esc(p.name) + '<br><span class="iv-muted iv-small">' + esc(p.category || '') + (p.code ? ' · ' + esc(p.code) : '') + '</span></td><td data-l="Barcode">' +
            (bs.length ? bs.map(function (b) { return '<span>' + esc(b) + ' <button type="button" class="iv-link" data-unlink="' + esc(b) + '" aria-label="Remove barcode ' + esc(b) + '">Remove</button></span>'; }).join('<br>') : '<span class="iv-muted">Not linked</span>') +
            '</td><td></td></tr>';
        }).join('') + '</tbody></table></div>' + (list.length > shown.length ? '<p class="iv-muted iv-small">Showing the first ' + shown.length + ' of ' + list.length + '. Use search to narrow.</p>' : '') : '<p class="iv-muted">Nothing here.</p>');
    var si = $('#bcSearch'); if (document.activeElement && document.activeElement.id === 'bcSearch') { si.focus(); }
  }

  // ---------- camera scan ----------
  // Chrome on Android has a built-in BarcodeDetector. iPhone Safari and PCs do not, so for those we load the
  // bundled ZXing library (assets/vendor, Apache-2.0) the first time the camera is opened.
  var camStream = null, camTimer = null, camBusy = false;
  function loadZxing() {
    return new Promise(function (resolve, reject) {
      if (window.ZXing) return resolve();
      var s = document.createElement('script'); s.src = '/assets/vendor/zxing-library.min.js';
      s.onload = resolve; s.onerror = function () { reject(new Error('could not load the scanner')); };
      document.head.appendChild(s);
    });
  }
  function onCameraCode(val) {
    if (!camBusy) return; closeCamera();
    $('#scan').value = val; renderHits(search(val)); onScanEnter();
  }
  // Returns a function(video) -> Promise<string|null> that looks for one barcode in the current video frame.
  async function makeDetector() {
    if ('BarcodeDetector' in window) {
      var det;
      try { det = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'qr_code'] }); } catch (e) { det = new window.BarcodeDetector(); }
      return async function (v) { var codes = await det.detect(v); return codes.length ? codes[0].rawValue : null; };
    }
    var reader = await zxingReader(), Z = window.ZXing, canvas = document.createElement('canvas');
    return async function (v) {
      if (!v.videoWidth) return null;
      canvas.width = v.videoWidth; canvas.height = v.videoHeight;
      canvas.getContext('2d').drawImage(v, 0, 0);
      return decodeCanvas(reader, Z, canvas);
    };
  }
  var zxCache = null;
  async function zxingReader() {
    if (zxCache) return zxCache;
    await loadZxing();
    var Z = window.ZXing, hints = new Map(), reader = new Z.MultiFormatReader();
    // Retail barcodes only. ITF / Code 39 / Code 128 readers often "find" random digits inside an EAN barcode.
    hints.set(Z.DecodeHintType.POSSIBLE_FORMATS, [Z.BarcodeFormat.EAN_13, Z.BarcodeFormat.EAN_8, Z.BarcodeFormat.UPC_A, Z.BarcodeFormat.UPC_E, Z.BarcodeFormat.QR_CODE]);
    hints.set(Z.DecodeHintType.TRY_HARDER, true);
    reader.setHints(hints);
    return (zxCache = reader);
  }
  function decodeCanvas(reader, Z, canvas) {
    try { return reader.decode(new Z.BinaryBitmap(new Z.HybridBinarizer(new Z.HTMLCanvasElementLuminanceSource(canvas)))).getText(); }
    catch (e) { return null; } // "not found" is normal
  }

  // ---------- take a photo, then read the barcode from the still picture ----------
  async function photoToBitmap(file) {
    if (window.createImageBitmap) { try { return await createImageBitmap(file); } catch (e) { /* fall through */ } }
    return new Promise(function (resolve, reject) {
      var img = new Image(), url = URL.createObjectURL(file);
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { reject(new Error('could not open that picture')); };
      img.src = url;
    });
  }
  async function readPhoto(file) {
    var bmp = await photoToBitmap(file), w = bmp.width, h = bmp.height;
    if ('BarcodeDetector' in window) {
      try {
        var det = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'qr_code'] });
        var codes = await det.detect(bmp); if (codes.length) return codes[0].rawValue;
      } catch (e) { /* use the library below */ }
    }
    var reader = await zxingReader(), Z = window.ZXing, canvas = document.createElement('canvas');
    // try a few sizes and the picture turned sideways: barcodes in big photos are small, and phones sometimes rotate the file
    for (var size of [1600, 1000, 2400]) {
      var k = Math.min(1, size / Math.max(w, h));
      for (var rot of [0, 90]) {
        var cw = Math.round(w * k), ch = Math.round(h * k), ctx;
        canvas.width = rot ? ch : cw; canvas.height = rot ? cw : ch; ctx = canvas.getContext('2d');
        ctx.save(); ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
        if (rot) { ctx.translate(canvas.width, 0); ctx.rotate(Math.PI / 2); }
        ctx.drawImage(bmp, 0, 0, cw, ch); ctx.restore();
        var val = decodeCanvas(reader, Z, canvas); if (val) return val;
      }
    }
    return null;
  }
  async function onPhoto(e) {
    var f = e.target.files && e.target.files[0]; e.target.value = ''; if (!f) return;
    toast('Reading the picture…');
    try {
      var val = await readPhoto(f);
      if (!val) return toast('No barcode found. Move closer, keep it flat and sharp, then retake.', true);
      $('#scan').value = val; renderHits(search(val)); onScanEnter();
    } catch (err) { toast('Could not read that picture: ' + err.message, true); }
  }
  async function openCamera() {
    if (camBusy) return; camBusy = true;
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) throw new Error('this browser cannot open the camera (the site must be opened with https)');
      var detect = await makeDetector();
      camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
      var v = $('#camVideo'); v.srcObject = camStream; await v.play(); $('#camBox').hidden = false;
      var working = false, last = null, streak = 0, need = ('BarcodeDetector' in window) ? 2 : 3;
      camTimer = setInterval(async function () {
        if (working) return; working = true;
        try {
          var val = await detect(v);
          // accept only when the SAME number is read several times in a row, so one blurry misread is ignored
          if (val && val === last) streak++; else { last = val; streak = val ? 1 : 0; }
          if (val && streak >= need) onCameraCode(val);
        } catch (e) { /* keep trying */ }
        working = false;
      }, 250);
    } catch (e) { closeCamera(); toast('Camera not available: ' + e.message, true); }
  }
  function closeCamera() {
    camBusy = false; clearInterval(camTimer); $('#camBox').hidden = true;
    if (camStream) camStream.getTracks().forEach(function (t) { t.stop(); }); camStream = null;
    var v = $('#camVideo'); if (v) v.srcObject = null;
  }

  // ---------- mode, wiring, startup ----------
  function setMode(m) {
    mode = m; sel = null; pendingBarcode = null; pendingRelink = false; setBanner();
    $$('.iv-tabs button').forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.mode === m)); });
    $('#scanBlock').hidden = m === 'recent' || m === 'barcodes'; $('#blindWrap').hidden = m !== 'count';
    $('#report').hidden = true; renderHits([]); renderPanel(); renderQueue(); renderRecent(); renderBarcodes();
    if (m !== 'recent' && m !== 'barcodes') $('#scan').focus();
  }
  function showLogin(msg) {
    $('#app').hidden = true; $('#login').hidden = false;
    var e = $('#loginErr'); e.hidden = !msg; e.textContent = msg || '';
  }
  async function startApp() {
    me = await rpc('inv_me');
    $('#login').hidden = true; $('#app').hidden = false;
    $('#who').textContent = (me.name || me.email) + (me.role === 'admin' ? ' (admin)' : '');
    await loadProducts(); loadQueue(); setMode('count');
  }
  function wire() {
    $$('.iv-tabs button').forEach(function (b) { b.onclick = function () { setMode(b.dataset.mode); }; });
    $('#scan').addEventListener('input', function () { renderHits(search(this.value)); });
    $('#scan').addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); onScanEnter(); } });
    $('#hits').addEventListener('click', function (e) {
      var b = e.target.closest('.iv-hit'); if (!b) return;
      chooseProduct(byId.get(b.dataset.id));
    });
    $('#blind').addEventListener('change', function () { blind = this.checked; renderPanel(); });
    $('#qTable').addEventListener('change', function (e) {
      if (e.target.classList.contains('iv-qreason')) { queue[+e.target.dataset.i].reason = e.target.value; saveQueue(); renderQueue(); }
    });
    $('#qTable').addEventListener('click', function (e) {
      var d = e.target.closest('[data-del]'); if (!d) return;
      queue.splice(+d.dataset.del, 1); saveQueue(); renderQueue();
    });
    $('#qClear').onclick = function () { if (queue.length && confirm('Clear the whole count list?')) { queue = []; saveQueue(); renderQueue(); } };
    $('#qSubmit').onclick = submitQueue;
    $('#recent').addEventListener('click', async function (e) {
      var u = e.target.closest('[data-undo]'); if (!u) return;
      u.disabled = true;
      try { await rpc('inv_undo', { p_client: u.dataset.undo }); toast('Undone'); await loadProducts(); renderRecent(); }
      catch (err) { toast(err.message, true); u.disabled = false; }
    });
    $('#barcodes').addEventListener('click', async function (e) {
      var f = e.target.closest('[data-bcf]'); if (f) { bcFilter = f.dataset.bcf; return renderBarcodes(); }
      var u = e.target.closest('[data-unlink]'); if (!u) return;
      var code = u.dataset.unlink, owner = byBarcode.get(code.toLowerCase());
      if (!confirm('Remove barcode ' + code + (owner ? ' from ' + owner.name : '') + '?')) return;
      try { await rpc('inv_barcode_unlink', { p_barcode: code }); toast('Barcode removed'); await loadProducts(); renderBarcodes(); }
      catch (err) { toast(err.message, true); }
    });
    $('#barcodes').addEventListener('input', function (e) {
      if (e.target.id !== 'bcSearch') return;
      bcQuery = e.target.value; var pos = e.target.selectionStart; renderBarcodes();
      var n = $('#bcSearch'); n.focus(); try { n.setSelectionRange(pos, pos); } catch (_) {}
    });
    $('#signout').onclick = function () { clearToken(); showLogin(''); };
    $('#loginForm').addEventListener('submit', async function (e) {
      e.preventDefault();
      try { await authCall('password', { email: $('#email').value.trim(), password: $('#password').value }); $('#password').value = ''; await startApp(); }
      catch (err) { showLogin(err.message); }
    });
    $('#cam').hidden = false; $('#cam').onclick = openCamera;
    $('#photo').onclick = function () { $('#photoIn').click(); };
    $('#photoIn').addEventListener('change', onPhoto);
    $('#camClose').onclick = closeCamera;
  }

  async function init() {
    wire();
    try {
      var r = await fetch('/api/inv/config', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('config');
      cfg = await r.json();
      var s = await fetch('/api/auth/session', { credentials: 'same-origin' }).then(function (x) { return x.ok ? x.json() : null; }).catch(function () { return null; });
      if (s && s.email) $('#email').value = s.email;
    } catch (e) { return showLogin('Inventory app is not configured on the server (SUPABASE_URL / SUPABASE_PUBLISHABLE_KEY).'); }
    try { tok = JSON.parse(localStorage.getItem(KEY_TOKEN) || 'null'); } catch (e) { tok = null; }
    if (!tok) return showLogin('');
    try { await startApp(); } catch (e) { showLogin(tok ? e.message : 'Please sign in.'); }
  }
  init();
})();
