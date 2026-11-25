// Stock After Sales: inventory snapshot minus weekly sales uploads (read-only).
(() => {
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = v => Number(v || 0).toLocaleString('en-MY', {maximumFractionDigits: 2});
let data = null, filter = '', onlyNeg = false;

async function api(url) {
  const r = await fetch(url, {credentials: 'same-origin', cache: 'no-store'});
  if (r.status === 401) { location.href = '/login'; throw Error('Please sign in again.'); }
  let j; try { j = await r.json(); } catch { throw Error('Unexpected server response'); }
  if (!r.ok) throw Error(j.error || 'Server error ' + r.status);
  return j;
}
function msg(t) { $('msg').hidden = !t; $('msg').textContent = t || ''; }

async function load(first) {
  msg(''); $('go').disabled = true;
  try {
    const q = new URLSearchParams();
    if (!first) { if ($('snap').value) q.set('snapshot', $('snap').value); if ($('from').value) q.set('from', $('from').value); if ($('to').value) q.set('to', $('to').value); }
    data = await api('/api/stock-after-sales?' + q);
    $('snap').innerHTML = data.snapshots.map(d => `<option${d === data.snapshot ? ' selected' : ''}>${esc(d)}</option>`).join('');
    $('from').value = data.range.start; $('to').value = data.range.end;
    $('csv').disabled = false; render();
  } catch (e) { msg(e.message); $('csv').disabled = true; }
  $('go').disabled = false;
}

function visible() {
  const w = filter.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return data.rows.filter(r => (!onlyNeg || r.after < 0) && w.every(x => (r.name + ' ' + r.category).toLowerCase().includes(x)));
}
function render() {
  const ch = data.channels, rows = data.rows;
  const totOpen = rows.reduce((a, r) => a + r.opening, 0), totSold = rows.reduce((a, r) => a + r.sold_total, 0);
  const neg = rows.filter(r => r.after < 0).length;
  let h = '<div class="sa-cards">' +
    `<div class="sa-card"><b>${fmt(totOpen)}</b><span>Opening units (${esc(data.snapshot)})</span></div>` +
    `<div class="sa-card"><b>${fmt(totSold)}</b><span>Sold on platforms</span></div>` +
    `<div class="sa-card"><b>${fmt(totOpen - totSold)}</b><span>Stock after sales</span></div>` +
    `<div class="sa-card"><b>${neg}</b><span>Products below zero</span></div></div>`;
  if (!data.counted.length) h += '<div class="sa-note">No weekly sales are uploaded for this period yet, so nothing is subtracted. Add them on the Upload Data page (Weekly sales tab).</div>';
  else h += `<div class="sa-note">Counted ${data.counted.length} upload(s): ` + data.counted.map(c => `${esc(c.channel_label)} ${esc(c.period_start)} to ${esc(c.period_end)}`).join('; ') + '.</div>';
  if (data.skipped.length) h += '<div class="sa-note">Not counted because they only partly fit the dates: ' + data.skipped.map(c => `${esc(c.channel_label)} ${esc(c.period_start)} to ${esc(c.period_end)}`).join('; ') + '.</div>';
  h += '<div class="sa-note">TikTok is not included yet. Only Shopee MY, Shopee SG and Clinic can be uploaded as weekly sales so far.</div>';
  h += `<input id="q" class="sa-search" type="search" placeholder="Search product" value="${esc(filter)}"> <label><input type="checkbox" id="neg"${onlyNeg ? ' checked' : ''}> Only below zero</label>`;
  const v = visible();
  h += '<div class="sa-wrap"><table><thead><tr><th>Product</th><th class="num">Opening</th>' + ch.map(c => `<th class="num">${esc(c.label)}</th>`).join('') + '<th class="num">Total sold</th><th class="num">Stock after</th></tr></thead><tbody>' +
    v.map(r => `<tr class="${r.after < 0 ? 'neg' : ''}"><td>${esc(r.name)}${r.unit ? ' <span class="sa-muted">(' + esc(r.unit) + ')</span>' : ''}${r.in_snapshot ? '' : ' <span class="sa-muted">not in inventory file</span>'}</td><td class="num">${fmt(r.opening)}</td>` +
      ch.map(c => `<td class="num">${fmt(r.sold[c.id])}</td>`).join('') + `<td class="num">${fmt(r.sold_total)}</td><td class="num ${r.after < 0 ? 'neg-n' : ''}">${fmt(r.after)}</td></tr>`).join('') + '</tbody></table></div>';
  if (data.unmatched.length) {
    h += '<h2>Sold but not matched to a product</h2><p class="sa-muted">These sales could not be linked to a product, so they are not subtracted above. Link them in Price Watch / product links, then recalculate.</p><div class="sa-wrap"><table><thead><tr><th>Platform</th><th>Item</th><th class="num">Units</th></tr></thead><tbody>' +
      data.unmatched.map(u => `<tr><td>${esc(u.channel_label)}</td><td>${esc(u.name)}</td><td class="num">${fmt(u.units)}</td></tr>`).join('') + '</tbody></table></div>';
  }
  $('out').innerHTML = h;
  $('q').oninput = e => { filter = e.target.value; const p = e.target.selectionStart; render(); const n = $('q'); n.focus(); n.setSelectionRange(p, p); };
  $('neg').onchange = e => { onlyNeg = e.target.checked; render(); };
}
function csvCell(v) { v = String(v ?? ''); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
function download() {
  if (!data) return;
  const head = ['Product', 'Unit', 'Opening (' + data.snapshot + ')'].concat(data.channels.map(c => c.label), ['Total sold', 'Stock after']);
  const lines = [head].concat(visible().map(r => [r.name, r.unit, r.opening].concat(data.channels.map(c => r.sold[c.id]), [r.sold_total, r.after])));
  const blob = new Blob(['﻿' + lines.map(l => l.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'stock-after-sales_' + data.range.start + '_to_' + data.range.end + '.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
$('go').onclick = () => load(false);
$('snap').onchange = () => { $('from').value = $('snap').value; };
$('csv').onclick = download;
let dbLoaded = false, histLoaded = false;
document.querySelectorAll('.sa-tabs button').forEach(b => b.onclick = () => {
  document.querySelectorAll('.sa-tabs button').forEach(x => x.classList.toggle('sel', x === b));
  $('tab-up').hidden = b.dataset.tab !== 'up'; $('tab-hist').hidden = b.dataset.tab !== 'hist'; $('tab-db').hidden = b.dataset.tab !== 'db';
  if (b.dataset.tab === 'db' && !dbLoaded) { dbLoaded = true; load(true); }
  if (b.dataset.tab === 'hist' && !histLoaded) loadHistory();
});

// ---------- Upload files tab ----------
const SLOTS = [['inventory', 'Inventory (FirstWell Avixo report)'], ['inventory_fs', "FirstStep's Avixo report (optional)"], ['shopee_my', 'Shopee MY'], ['shopee_sg', 'Shopee SG'], ['tiktok', 'TikTok']];
$('slots').innerHTML = SLOTS.map(([k, l]) => `<label class="sa-slot">${l}<input type="file" id="slot-${k}" accept=".xlsx,.xls"></label>`).join('');
const slotInput = k => $('slot-' + k);
function guessSlot(n) {
  n = n.toLowerCase();
  if (/inventory[_ -]?report/.test(n)) return 'inventory';
  if (/(^|[^a-z])sg[ _-]?\d?([^a-z]|$)/.test(n)) return 'shopee_sg';
  if (/(^|[^a-z])my([^a-z]|$)/.test(n)) return 'shopee_my';
  if (/tiktok|tik[ _-]?tok|(^|[^a-z])tt([^a-z]|$)|product[_ -]?list/.test(n)) return 'tiktok';
  return null;
}
$('multi').onchange = e => {
  const left = [], reports = [...e.target.files].filter(f => guessSlot(f.name) === 'inventory').length;
  for (const f of e.target.files) {
    const k = guessSlot(f.name);
    if (k === 'inventory' && reports > 1) { left.push(f.name + ' (two Avixo reports: choose which is FirstWell and which is FirstStep)'); continue; }
    if (k) { const dt = new DataTransfer(); dt.items.add(f); slotInput(k).files = dt.files; } else left.push(f.name);
  }
  upmsg(left.length ? 'Could not tell where these go: ' + left.join(', ') + '. Choose them in the right box.' : ''); e.target.value = '';
};
function slotForm() {
  const f = new FormData(); let n = 0;
  for (const [k] of SLOTS) { const x = slotInput(k).files[0]; if (x) { f.append(k, x); n++; } }
  return [f, n];
}
$('clearAll').onclick = () => { for (const [k] of SLOTS) slotInput(k).value = ''; up = null; $('upout').innerHTML = ''; upmsg(''); };
let csrf = '', up = null;
const fmtq = v => v ? fmt(v) : '';
function upmsg(t) { $('upmsg').hidden = !t; $('upmsg').textContent = t || ''; }
async function calc() {
  if (!slotInput('inventory').files.length) return upmsg('Choose the Avixo Inventory Report in the Inventory box first.');
  upmsg(''); $('calc').disabled = true; $('calc').textContent = 'Reading files…';
  try {
    if (!csrf) csrf = (await api('/api/auth/session')).csrf_token;
    const [f] = slotForm();
    const r = await fetch('/api/stock-after-sales/from-files', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRF-Token': csrf}, body: f});
    if (r.status === 401) { location.href = '/login'; return; }
    let j; try { j = await r.json(); } catch { throw Error('Unexpected server response'); }
    if (!r.ok) throw Error(j.error || 'Server error ' + r.status);
    // Products with 0 in Avixo before are not shown (nothing to deduct from). They are listed in a note under the summary.
    const zero = r => !(r.before > 0);
    j.hidden = j.rows.filter(zero).concat(j.ref && j.ref.rows ? j.ref.rows.filter(zero) : []);
    j.rows = j.rows.filter(r => !zero(r)); if (j.ref && j.ref.rows) j.ref.rows = j.ref.rows.filter(r => !zero(r));
    up = j; renderUp();
  } catch (e) { upmsg(e.message); up = null; $('upout').innerHTML = ''; }
  $('calc').disabled = false; $('calc').textContent = 'Preview →';
}
async function postJson(url, body) {
  if (!csrf) csrf = (await api('/api/auth/session')).csrf_token;
  const r = await fetch(url, {method: 'POST', credentials: 'same-origin', headers: {'X-CSRF-Token': csrf, 'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  let j = {}; try { j = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw Error(j.error || 'Server error ' + r.status);
}
// Save one pairing, then read the same files again so the table includes these sales.
// source: 'firstwell' = the uploaded Avixo report, 'firststep' = FirstStep's Avixo (read from FirstStep's Supabase).
async function pairListing(i, avixoId, source) {
  source = source === 'firststep' ? 'firststep' : 'firstwell';
  const list = source === 'firststep' ? ((up.ref || {}).products || []) : up.products;
  const u = up.unmatched[i], p = list.find(x => String(x.id) === String(avixoId));
  if (!u || !p) return;
  try {
    await postJson('/api/stock-after-sales/alias', {market: u.market, item: u.item, variation: u.var_key, avixo_id: String(p.id), avixo_name: p.name, platform_name: u.name, avixo_source: source});
    await calc();
    upmsg('Paired "' + u.name + '" with ' + (source === 'firststep' ? "FirstStep's Avixo " : '') + p.id + ' · ' + p.name + '. It will be matched automatically next time.');
  } catch (e) { upmsg(e.message); }
}
async function unpair(i) {
  const u = up.paired[i];
  try { await postJson('/api/stock-after-sales/alias/remove', {market: u.market, item: u.item, variation: u.variation}); await calc(); upmsg('Pairing removed.'); }
  catch (e) { upmsg(e.message); }
}
const RNAME = {shopee_my: 'MY', shopee_sg: 'SG', tiktok: 'TT'};
const ddmmyyyy = iso => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || ''); return m ? m[3] + m[2] + m[1] : ''; };
// Each platform keeps the date of its own sales file, unless staff changed the sales date (then one date is used for all).
function remarkFor(r, iso) {
  const own = iso === up.sales_date ? (up.slot_dates || {}) : {}, groups = new Map();
  up.channels.filter(c => (r.sold[c.id] || 0) > 0).forEach(c => {
    const d = ddmmyyyy(own[c.id] || iso);
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d).push((RNAME[c.id] || c.label) + ' x' + r.sold[c.id]);
  });
  const text = [...groups].map(([d, parts]) => (d ? [d] : []).concat(parts).join(' ')).join('; ');
  return r.remark_suffix ? text + ' ' + r.remark_suffix : text;   // sales deducted from FirstStep's Avixo end with "Firstwell"
}
async function copyText(text, btn, done) {
  try { await navigator.clipboard.writeText(text); } catch {
    const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select();
    try { document.execCommand('copy'); } catch { upmsg('Could not copy. Select the text and copy it by hand.'); } t.remove();
  }
  if (btn) { const old = btn.textContent; btn.textContent = done || 'Copied'; setTimeout(() => { btn.textContent = old; }, 1200); }
}
// On the first draw of the table the date box does not exist yet, so fall back to the sales date found in the files.
const salesDate = () => ($('salesDate') && $('salesDate').value) || (up && up.sales_date) || '';
function upTable(rows) {
  const ch = up.channels, iso = salesDate();
  return '<div class="sa-wrap"><table><thead><tr><th>ID</th><th>Product</th><th class="num">Stock before</th>' + ch.map(c => `<th class="num">${esc(c.label)}</th>`).join('') +
    '<th class="num">Total sold</th><th class="num">Stock after</th><th>Remark for Avixo</th><th></th><th>Take from expiry</th><th>Check</th></tr></thead><tbody>' +
    rows.map(r => `<tr class="${r.after < 0 ? 'neg' : ''}"><td>${r.id}</td><td>${esc(r.name)}${r.unit ? ' <span class="sa-muted">(' + esc(r.unit) + ')</span>' : ''}</td><td class="num">${fmt(r.before)}</td>` +
      ch.map(c => `<td class="num">${fmtq(r.sold[c.id])}</td>`).join('') + `<td class="num">${fmt(r.total)}</td><td class="num ${r.after < 0 ? 'neg-n' : ''}"><b>${fmt(r.after)}</b></td><td><b>${esc(remarkFor(r, iso))}</b></td><td><button type="button" class="sa-copy" data-remark="${esc(remarkFor(r, iso))}" title="Copy this remark">Copy</button></td><td>${esc(r.expiry)}</td><td class="${r.check ? 'chk' : ''}">${esc(r.check)}</td></tr>`).join('') +
    '</tbody></table></div>';
}
const refRows = () => ((up && up.ref) || {}).rows || [];
function renderUp() {
  const j = up, tot = j.rows.reduce((a, r) => a + r.total, 0), un = j.unmatched.reduce((a, r) => a + r.units, 0);
  const rtot = refRows().reduce((a, r) => a + r.total, 0);
  let h = '<ul class="sa-files">' + j.files.map(f => `<li>${esc(f.kind)}: ${esc(f.file)} <span class="sa-muted">(${esc(f.detail)})</span></li>`).join('') + '</ul>';
  h += '<div class="sa-cards">' + `<div class="sa-card"><b>${j.rows.length}</b><span>Products sold (this Avixo)</span></div><div class="sa-card"><b>${fmt(tot)}</b><span>Units sold (this Avixo)</span></div>` +
    (j.ref ? `<div class="sa-card"><b>${fmt(rtot)}</b><span>Units from FirstStep's Avixo</span></div>` : '') + `<div class="sa-card"><b>${fmt(un)}</b><span>Units not matched</span></div></div>`;
  j.notes.forEach(n => h += `<div class="sa-note">${esc(n)}</div>`);
  if (j.hidden.length) h += `<div class="sa-note">Not shown: ${j.hidden.length} sold product${j.hidden.length > 1 ? 's' : ''} with 0 in Avixo before (${j.hidden.map(r => esc(r.id + ' ' + r.name)).join(', ')}).</div>`;
  if (j.already_saved.length) h += '<div class="sa-msg">Already saved in the history before: ' + j.already_saved.map(a => esc(a.file)).join(', ') + '.</div>';
  h += '<div class="sa-actions"><label class="sa-muted">Sales date <input type="date" id="salesDate" value="' + esc(j.sales_date || '') + '"></label>' +
    '<button type="button" id="copyRem" class="alt">Copy all remarks</button><button type="button" id="copyTsv" class="alt">Copy table (paste into Excel / Avixo)</button><button type="button" id="dlCsv" class="alt">Download CSV</button></div>';
  h += '<h2>Deduct from the uploaded Avixo (' + esc(j.inventory.file) + ')</h2>';
  h += '<div id="uptable">' + (j.rows.length ? upTable(j.rows) : '<p class="sa-muted">No sold products were found in this Avixo report.</p>') + '</div>';
  if (j.ref && refRows().length) {
    h += `<h2>Deduct from ${esc(j.ref.label)}</h2><p class="sa-muted">Sold on FirstWell but not in the uploaded Avixo report, found in FirstStep's Avixo instead. Update these in <b>FirstStep's Avixo</b>, not FirstWell's. Stock before = ${j.ref.source === 'upload' ? `the FirstStep Avixo report you uploaded (${esc(j.ref.when)})` : `FirstStep's last Avixo report in its dashboard (${esc(j.ref.when)}), so it may be a few weeks old. Upload FirstStep's latest Avixo report to use fresh stock`}.</p>` +
      '<div class="sa-actions"><button type="button" id="copyRemRef" class="alt">Copy these remarks</button><button type="button" id="copyTsvRef" class="alt">Copy this table</button><button type="button" id="dlCsvRef" class="alt">Download CSV</button></div>' +
      '<div id="reftable">' + upTable(refRows()) + '</div>';
  }
  if (j.unmatched.length) {
    h += '<h2>Sold but not matched to an Avixo product</h2><p class="sa-muted">Pick the Avixo product for each listing' + (j.ref ? " — from the uploaded Avixo, or from <b>FirstStep's Avixo</b> (FS)" : '') + '. The pairing is saved, so this listing is matched automatically from now on, and the tables above update.</p>' +
      '<datalist id="avixoList">' + j.products.map(p => `<option value="${esc(p.id + ' · ' + p.name)}"></option>`).join('') +
        (j.ref ? j.ref.products.map(p => `<option value="${esc('FS-' + p.id + ' · ' + p.name + " (FirstStep's Avixo)")}"></option>`).join('') : '') + '</datalist>' +
      '<div class="sa-wrap"><table><thead><tr><th>Platform</th><th>Listing</th><th class="num">Units</th><th>Pair with Avixo product</th></tr></thead><tbody>' +
      j.unmatched.map((u, i) => `<tr><td>${esc(u.channel)}</td><td>${esc(u.name)}${u.variation ? ' <span class="sa-muted">/ ' + esc(u.variation) + '</span>' : ''}<br><span class="sa-muted">ID ${esc(u.item)}</span></td><td class="num">${fmt(u.units)}</td>` +
        `<td class="sa-pair">${(u.candidates || []).slice(0, 3).map(c => `<button type="button" class="alt sa-pairpick" data-u="${i}" data-id="${esc(c.id)}" data-src="firstwell" title="Pair with ${esc(c.name)}">${esc(c.id + ' · ' + c.name)}</button>`).join('')}` +
        `${(u.ref_candidates || []).slice(0, 3).map(c => `<button type="button" class="alt sa-pairpick sa-fs" data-u="${i}" data-id="${esc(c.id)}" data-src="firststep" title="Pair with FirstStep's Avixo: ${esc(c.name)}">FS ${esc(c.id + ' · ' + c.name)}</button>`).join('')}` +
        `<span class="sa-other"><input type="text" list="avixoList" placeholder="Search other Avixo name or ID…" data-search="${i}"><button type="button" class="sa-pairbtn" data-u="${i}">Pair</button></span></td></tr>`).join('') + '</tbody></table></div>';
  }
  if ((j.paired || []).length) {
    h += `<details class="sa-paired"><summary>Matched by a saved pairing (${j.paired.length})</summary><div class="sa-wrap"><table><thead><tr><th>Platform</th><th>Listing</th><th>Avixo product</th><th class="num">Units</th><th></th></tr></thead><tbody>` +
      j.paired.map((u, i) => `<tr><td>${esc(u.channel)}</td><td>${esc(u.name)}${u.var_name ? ' <span class="sa-muted">/ ' + esc(u.var_name) + '</span>' : ''}<br><span class="sa-muted">ID ${esc(u.item)}</span></td><td>${u.source === 'firststep' ? "<b>FirstStep's Avixo</b> " : ''}${esc(u.avixo_id + ' · ' + u.avixo_name)}</td><td class="num">${fmt(u.units)}</td><td><button type="button" class="alt sa-unpair" data-p="${i}">Remove pairing</button></td></tr>`).join('') + '</tbody></table></details>';
  }
  if (j.can_save) h += '<div class="sa-confirm"><div class="sa-muted">Saving only keeps a record in the History tab. It does not change any stock, here or in Avixo.</div>' +
    '<div class="sa-actions"><button type="button" id="saveBtn">Save to history</button></div></div>';
  $('upout').innerHTML = h;
  const bindCopy = () => document.querySelectorAll('#uptable .sa-copy, #reftable .sa-copy').forEach(b => b.onclick = () => copyText(b.dataset.remark, b));
  $('salesDate').onchange = () => { $('uptable').innerHTML = up.rows.length ? upTable(up.rows) : ''; if ($('reftable')) $('reftable').innerHTML = upTable(refRows()); bindCopy(); };
  bindCopy();
  $('copyRem').onclick = () => copyText(up.rows.map(r => remarkFor(r, salesDate())).join('\n'), $('copyRem'), 'Copied ' + up.rows.length);
  if (j.can_save) $('saveBtn').onclick = saveNow;
  document.querySelectorAll('.sa-pairpick').forEach(b => b.onclick = () => pairListing(+b.dataset.u, b.dataset.id, b.dataset.src));
  document.querySelectorAll('.sa-pairbtn').forEach(b => b.onclick = () => {
    const raw = (document.querySelector(`[data-search="${b.dataset.u}"]`).value || '').trim(), id = raw.split(' · ')[0].trim();
    if (/^FS-/i.test(id) && up.ref) {
      const hit = up.ref.products.find(p => String(p.id) === id.slice(3));
      if (!hit) return upmsg("Choose a FirstStep product from the list.");
      return pairListing(+b.dataset.u, hit.id, 'firststep');
    }
    const hit = up.products.find(p => String(p.id) === id) || up.products.find(p => p.name.toLowerCase() === raw.toLowerCase());
    if (!hit) return upmsg('Choose a product from the list (type part of the name or the ID).');
    pairListing(+b.dataset.u, hit.id, 'firstwell');
  });
  if ($('copyRemRef')) {
    $('copyRemRef').onclick = () => copyText(refRows().map(r => remarkFor(r, salesDate())).join('\n'), $('copyRemRef'), 'Copied ' + refRows().length);
    $('copyTsvRef').onclick = () => copyText(upLines(refRows()).map(l => l.join('\t')).join('\n'), $('copyTsvRef'));
    $('dlCsvRef').onclick = () => downloadCsv(upLines(refRows()), 'stock-after-sales-firststep-avixo.csv');
  }
  document.querySelectorAll('.sa-unpair').forEach(b => b.onclick = () => unpair(+b.dataset.p));
  $('copyTsv').onclick = () => copyText(upLines().map(l => l.join('\t')).join('\n'), $('copyTsv'));
  $('dlCsv').onclick = () => downloadCsv(upLines(), 'stock-after-sales.csv');
}
function downloadCsv(lines, fname) {
  const blob = new Blob(['\ufeff' + lines.map(l => l.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = fname; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
async function saveNow() {
  if (!salesDate()) return upmsg('Choose the sales date first.');
  $('saveBtn').disabled = true; $('saveBtn').textContent = 'Saving…'; upmsg('');
  try {
    const [f] = slotForm(); f.append('expected_sha256', up.sha256); f.append('sales_date', salesDate());
    const r = await fetch('/api/stock-after-sales/save', {method: 'POST', credentials: 'same-origin', headers: {'X-CSRF-Token': csrf}, body: f});
    let j; try { j = await r.json(); } catch { throw Error('Unexpected server response'); }
    if (!r.ok) throw Error(j.error || 'Server error ' + r.status);
    $('saveBtn').closest('.sa-confirm').outerHTML = '<div class="sa-done"><b>Saved to history.</b> No stock was changed. You can find it in the History tab.</div>';
    histLoaded = false;
  } catch (e) { upmsg(e.message); $('saveBtn').disabled = false; $('saveBtn').textContent = 'Save to history'; }
}
function upLines(rows) {
  const ch = up.channels, iso = salesDate();
  return [['ID', 'Product', 'Unit', 'Stock before'].concat(ch.map(c => c.label), ['Total sold', 'Stock after', 'Remark for Avixo', 'Take from expiry', 'Check'])]
    .concat((rows || up.rows).map(r => [r.id, r.name, r.unit, r.before].concat(ch.map(c => r.sold[c.id] || ''), [r.total, r.after, remarkFor(r, iso), r.expiry, r.check])));
}
$('calc').onclick = calc;

// ---------- History tab ----------
const SLOT_LABEL = Object.fromEntries(SLOTS);
const when = s => new Date(s).toLocaleString('en-MY', {timeZone: 'Asia/Kuala_Lumpur', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit'});
async function loadHistory() {
  $('histmsg').hidden = true; $('histout').innerHTML = '<p class="sa-muted">Loading…</p>';
  try {
    const j = await api('/api/stock-after-sales/history'); histLoaded = true;
    if (!j.items.length) { $('histout').innerHTML = '<p class="sa-muted">Nothing saved yet.</p>'; return; }
    const ddmmyyyy = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') ? d.slice(8) + d.slice(5, 7) + d.slice(0, 4) : '';
    $('histout').innerHTML = '<div class="sa-wrap"><table><thead><tr><th>Saved</th><th>By</th><th>Sales date</th><th>Files</th><th class="num">Products</th><th>Type</th><th></th></tr></thead><tbody>' +
      j.items.map(i => `<tr><td>${esc(when(i.applied_at))}</td><td>${esc(i.applied_by)}</td><td>${esc(ddmmyyyy(i.sales_date))}</td><td>${i.files.map(f => esc((SLOT_LABEL[f.slot] || f.slot) + ': ' + f.name)).join('<br>')}${i.inventory_file ? '<br><span class="sa-muted">Inventory: ' + esc(i.inventory_file) + (i.inventory_date ? ' (' + esc(i.inventory_date) + ')' : '') + '</span>' : ''}</td>` +
        `<td class="num">${i.products}</td><td>${i.mode === 'record' ? 'Record only' : 'Stock updated (' + fmt(i.units_applied) + ' units)'}</td><td><button type="button" class="sa-link" data-hid="${esc(i.id)}" data-mode="${esc(i.mode)}">View</button></td></tr><tr hidden id="hd-${esc(i.id)}"><td colspan="7"></td></tr>`).join('') + '</tbody></table></div>';
    $('histout').querySelectorAll('[data-hid]').forEach(b => b.onclick = () => openHist(b.dataset.hid, b));
  } catch (e) { $('histmsg').hidden = false; $('histmsg').textContent = e.message; $('histout').innerHTML = ''; }
}
// Sales deducted from FirstStep's Avixo end with "_ Firstwell". Entries saved before that rule get it added when shown.
const REF_SUFFIX = '_ Firstwell';
const histRemark = l => {
  const r = String(l.remark || '');
  return r && /^FS-/i.test(String(l.avixo_id || '')) && !r.endsWith(REF_SUFFIX) ? r + ' ' + REF_SUFFIX : r;
};
async function openHist(id, btn) {
  const row = $('hd-' + id), cell = row.firstElementChild, legacy = btn.dataset.mode !== 'record';
  if (!row.hidden) { row.hidden = true; btn.textContent = 'View'; return; }
  btn.textContent = 'Hide'; row.hidden = false; cell.innerHTML = 'Loading…';
  try {
    const j = await api('/api/stock-after-sales/history/' + encodeURIComponent(id));
    const status = l => l.undone ? 'Undone' : l.short > 0 ? 'Short' : 'Deducted';
    cell.innerHTML = '<div class="sa-actions"><button type="button" class="alt" data-csv="' + esc(id) + '">Download CSV</button></div><div class="sa-wrap"><table><thead><tr><th>Product</th><th>Platform</th><th class="num">Sold</th><th class="num">Avixo before → after</th><th>Remark for Avixo</th>' + (legacy ? '<th class="num">Deducted</th><th class="num">App before → after</th><th>Status</th>' : '') + '</tr></thead><tbody>' +
      j.lines.map(l => `<tr><td>${esc(l.product)}</td><td>${esc(l.channel)}</td><td class="num">${fmt(l.sold)}</td><td class="num">${l.avixo_before == null ? '' : fmt(l.avixo_before) + ' → ' + fmt(l.avixo_after)}</td><td>${esc(histRemark(l) || '')}${histRemark(l) ? ' <button type="button" class="sa-copy" data-remark="' + esc(histRemark(l)) + '">Copy</button>' : ''}</td>` +
        (legacy ? `<td class="num">${fmt(l.applied)}</td><td class="num">${l.app_before == null ? '' : fmt(l.app_before) + ' → ' + fmt(l.app_after)}</td><td>${esc(status(l))}</td>` : '') + '</tr>').join('') + '</tbody></table></div>';
    cell.querySelectorAll('.sa-copy').forEach(b => b.onclick = () => copyText(b.dataset.remark, b));
    cell.querySelector('[data-csv]').onclick = () => {
      const lines = [['Product', 'Avixo ID', 'Platform', 'Sold', 'Avixo before', 'Avixo after', 'Remark for Avixo']].concat(j.lines.map(l => [l.product, l.avixo_id, l.channel, l.sold, l.avixo_before ?? '', l.avixo_after ?? '', histRemark(l) || '']));
      const blob = new Blob(['\ufeff' + lines.map(l => l.map(csvCell).join(',')).join('\r\n')], {type: 'text/csv;charset=utf-8'});
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'stock-after-sales-history.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
  } catch (e) { cell.textContent = e.message; }
}
})();
