// Weekly sales tab of the Upload Data page. Element ids are prefixed 'w-' so they never clash with the monthly form.
(() => {
const el = id => document.getElementById('w-' + id);
const escapeHtml = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = v => Number(v || 0).toLocaleString('en-MY', {maximumFractionDigits: 2});
const money = (v, cur) => v == null ? 'Units only' : (cur === 'SGD' ? 'S$ ' : 'RM ') + Number(v).toLocaleString('en-MY', {minimumFractionDigits: 2, maximumFractionDigits: 2});
let csrf = '', previewSha = null, previewOk = false;

function message(text, type = '') { el('message').innerHTML = text ? `<div class="message ${type}">${escapeHtml(text)}</div>` : ''; }
async function api(url, options = {}) {
  const r = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options});
  if (r.status === 401) { location.href = '/login'; throw Error('Please sign in again.'); }
  let data; try { data = await r.json(); } catch { throw Error('Unexpected server response'); }
  if (!r.ok) throw Error(data.error || `Server error ${r.status}`);
  return data;
}
function table(headers, rows, numeric = []) {
  return `<table><thead><tr>${headers.map((h, i) => `<th${numeric.includes(i) ? ' class="num"' : ''}>${escapeHtml(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map((c, i) => `<td${numeric.includes(i) ? ' class="num"' : ''}>${escapeHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function clearPreview() { previewSha = null; previewOk = false; el('previewArea').classList.add('hidden'); el('confirm').checked = false; el('acceptBtn').disabled = true; }
function formData(extra = {}) {
  const f = new FormData();
  f.append('file', el('file').files[0]);
  for (const id of ['kind', 'period_start', 'period_end']) f.append(id, el(id).value);
  for (const [k, v] of Object.entries(extra)) f.append(k, v);
  return f;
}

// Fill the dates from a file name such as parentskudetail.20261019_20261025.xlsx
el('file').addEventListener('change', () => {
  clearPreview(); message('');
  const name = el('file').files[0]?.name || '';
  const m = name.match(/(20\d{2})(\d{2})(\d{2})[_-](20\d{2})(\d{2})(\d{2})/);
  if (m) {
    el('period_start').value = `${m[1]}-${m[2]}-${m[3]}`;
    el('period_end').value = `${m[4]}-${m[5]}-${m[6]}`;
    el('nameHint').textContent = 'Dates were read from the file name. Check them.';
  } else {
    el('nameHint').textContent = 'This file name has no dates. Enter the dates you exported.';
  }
});
for (const id of ['kind', 'period_start', 'period_end']) el(id).addEventListener('change', () => { clearPreview(); message(''); });
el('confirm').addEventListener('change', () => { el('acceptBtn').disabled = !(el('confirm').checked && previewOk); });

el('uploadForm').addEventListener('submit', async ev => {
  ev.preventDefault(); clearPreview(); message('Checking the Excel file…');
  const btn = el('previewBtn'); btn.disabled = true;
  try {
    const res = await api('/api/weekly-sales/preview', {method: 'POST', headers: {'X-CSRF-Token': csrf}, body: formData()});
    previewSha = res.sha256; previewOk = res.can_accept;
    const m = res.metrics;
    el('previewMeta').textContent = `${m.channel_label} · ${res.period_start} to ${res.period_end} · ${el('file').files[0].name}`;
    el('metrics').innerHTML = [
      ['Rows', fmt(m.rows)], ['Units', fmt(m.units)],
      ['Revenue', m.revenue == null ? 'Units only' : money(m.revenue, m.currency)],
      ['Rows not linked to an Avixo product', fmt(m.unmapped_rows)]
    ].map(([k, v]) => `<div class="metric"><small>${escapeHtml(k)}</small><strong>${escapeHtml(v)}</strong></div>`).join('');
    const notes = [...(res.warnings || []).map(t => ['warn', t]), ...(res.conflicts || []).map(t => ['error', t])];
    if (res.already_imported) notes.push(['error', 'This exact file was already imported. Nothing to add.']);
    el('warnings').innerHTML = notes.map(([k, t]) => `<div class="message ${k}">${escapeHtml(t)}</div>`).join('');
    el('previewArea').classList.remove('hidden');
    message(res.can_accept ? 'Preview ready. Check the totals before saving.' : 'This file cannot be saved. See the notes below.', res.can_accept ? '' : 'error');
  } catch (err) { message(err.message, 'error'); } finally { btn.disabled = false; }
});
el('acceptBtn').addEventListener('click', async () => {
  if (!previewSha || !previewOk || !el('confirm').checked) return;
  el('acceptBtn').disabled = true;
  try {
    const res = await api('/api/weekly-sales/accept', {method: 'POST', headers: {'X-CSRF-Token': csrf}, body: formData({expected_sha256: previewSha})});
    message(res.message || 'Saved.'); clearPreview(); el('file').value = ''; el('nameHint').textContent = '';
    await loadSummary();
  } catch (err) { message(err.message, 'error'); el('acceptBtn').disabled = false; }
});
el('cancelBtn').addEventListener('click', () => { clearPreview(); message('Cancelled. Nothing was saved.'); });

async function loadSummary(useDates = false) {
  const q = new URLSearchParams();
  if (useDates && el('from').value) q.set('from', el('from').value);
  if (useDates && el('to').value) q.set('to', el('to').value);
  const s = await api('/api/weekly-sales/summary' + (q.toString() ? '?' + q : ''));
  if (!s.range) {
    el('totals').innerHTML = ''; el('notes').innerHTML = ''; el('gaps').innerHTML = '';
    el('weeks').innerHTML = '<div class="empty">No weekly sales uploaded yet.</div>'; el('top').innerHTML = '';
    return;
  }
  if (!useDates) { el('from').value = s.range.start; el('to').value = s.range.end; }
  el('notes').innerHTML = (s.notes || []).map(t => `<div class="message">${escapeHtml(t)}</div>`).join('');
  el('totals').innerHTML = s.totals.length ? s.totals.map(t => `<div class="metric"><small>${escapeHtml(t.channel_label)} · ${t.periods} upload(s), ${t.days} days</small><strong>${escapeHtml(fmt(t.units))} units</strong><small>${escapeHtml(money(t.revenue, t.currency))}</small></div>`).join('') : '<div class="empty">No whole upload falls inside these dates.</div>';
  el('gaps').innerHTML = Object.entries(s.gaps || {}).filter(([, g]) => g.length).map(([ch, g]) => `<div class="message warn ws-gap">${escapeHtml(({shopee_my: 'Shopee MY', shopee_sg: 'Shopee SG', clinic: 'Clinic'})[ch])} has no data for: ${escapeHtml(g.map(([a, b]) => a === b ? a : `${a} to ${b}`).join(', '))}</div>`).join('');
  el('weeks').innerHTML = s.weeks.length ? table(['Period', 'Channel', 'Units', 'Revenue', 'Rows', 'Not linked', 'File'], s.weeks.map(w => [`${w.period_start} to ${w.period_end}`, w.channel_label, fmt(w.units), money(w.revenue, w.currency), w.rows, w.unmapped_rows, w.file]), [2, 3, 4, 5]) : '<div class="empty">Nothing in these dates.</div>';
  el('top').innerHTML = Object.entries(s.top_products || {}).filter(([, list]) => list.length).map(([ch, list]) => `<div class="tablewrap"><h3>${escapeHtml(({shopee_my: 'Shopee MY', shopee_sg: 'Shopee SG', clinic: 'Clinic'})[ch])}</h3>${table(['Product', 'Units', 'Revenue'], list.map(p => [p.name, fmt(p.units), money(p.revenue, ch === 'shopee_sg' ? 'SGD' : 'MYR')]), [1, 2])}</div>`).join('') || '<div class="empty">No products yet.</div>';
}
el('applyBtn').addEventListener('click', () => loadSummary(true).catch(e => message(e.message, 'error')));
el('allBtn').addEventListener('click', () => loadSummary(false).catch(e => message(e.message, 'error')));
(async () => { try { csrf = (await api('/api/auth/session')).csrf_token; await loadSummary(false); } catch (e) { message(e.message, 'error'); } })();

// Tabs on the Upload Data page: Monthly reports | Weekly sales (#weekly opens the weekly tab).
const tabs = {monthly: [document.getElementById('tabBtnMonthly'), document.getElementById('tab-monthly')],
              weekly: [document.getElementById('tabBtnWeekly'), document.getElementById('tab-weekly')]};
function showTab(name) {
  for (const [key, [btn, panel]] of Object.entries(tabs)) {
    btn.setAttribute('aria-selected', String(key === name));
    panel.hidden = key !== name;
  }
  try { history.replaceState(null, '', name === 'weekly' ? '#weekly' : location.pathname); } catch (e) { /* ignore */ }
}
tabs.monthly[0].addEventListener('click', () => showTab('monthly'));
tabs.weekly[0].addEventListener('click', () => showTab('weekly'));
showTab(location.hash === '#weekly' ? 'weekly' : 'monthly');

})();
