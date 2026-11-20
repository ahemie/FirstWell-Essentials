/* Action Centre — loads one reporting month and turns it into ranked actions. */
(function () {
  'use strict';
  const A = window.FSAnalysis;
  const $ = id => document.getElementById(id);
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const rm = n => 'RM ' + Math.round(n || 0).toLocaleString('en-MY');
  const rm2 = n => 'RM ' + (n || 0).toLocaleString('en-MY', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const int = n => Math.round(n || 0).toLocaleString('en-MY');
  const pct = (n, d = 0) => n == null ? '—' : n.toFixed(d) + '%';
  const date = s => { if (!s) return '—'; const p = s.split('-'); return `${+p[2]} ${MON[+p[1] - 1]} ${p[0]}`; };
  const short = (s, n = 46) => s.length > n ? s.slice(0, n - 1) + '…' : s;

  let state = { months: [], data: null, summary: null, tab: 'reorder', showAll: false, sort: null, fees: { my: 0, sg: 0 } };
  const FEE_KEY = 'fw_shopee_fee_assumption';
  function loadFees() { try { const f = JSON.parse(localStorage.getItem(FEE_KEY) || '{}'); state.fees = { my: clampPct(f.my), sg: clampPct(f.sg) }; } catch (e) { /* storage unavailable: keep defaults */ } }
  function saveFees() { try { localStorage.setItem(FEE_KEY, JSON.stringify(state.fees)); } catch (e) { /* ignore */ } }
  function clampPct(v) { v = Number(v); return isFinite(v) ? Math.min(Math.max(v, 0), 100) : 0; }

  async function getJson(url) {
    const r = await fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' } });
    if (!r.ok) throw new Error(url + ' → ' + r.status);
    return r.json();
  }
  async function loadMonths() {
    try { const l = await getJson('/api/dashboard/months'); if (Array.isArray(l) && l.length) return { list: l, source: 'api' }; } catch (e) { /* fall through to files */ }
    return { list: await getJson('/data/months.json'), source: 'files' };
  }
  async function loadMonth(key) {
    return state.source === 'api' ? getJson('/api/dashboard/' + encodeURIComponent(key)) : getJson('/data/' + encodeURIComponent(key) + '.json');
  }

  /* ---------- analyst narrative ---------- */
  function narrative(s, meta) {
    const topCat = s.categories[0];
    const idleShare = s.stockValue > 0 ? s.idleStock / s.stockValue * 100 : 0;
    const parts = [
      `${esc(meta.label)}: ${rm(s.revenue)} sales at an estimated ${pct(s.gm, 1)} gross margin (${rm(s.grossProfit)} gross profit, before Shopee fees and expenses).`,
      `Stock on hand is ${rm(s.stockValue)}, about ${s.coverMonths == null ? '—' : s.coverMonths.toFixed(1)} months of sales, yet <strong>${int(s.lists.reorder.length)} products are running short</strong> while <strong>${rm(s.idleStock)} (${idleShare.toFixed(0)}%)</strong> sits in slow, non-moving or excess stock.`,
      `That is a stock-mix problem more than a stock-size problem: move cash from idle items into the fast sellers.`
    ];
    if (topCat) parts.push(`${esc(topCat.name)} drives ${pct(topCat.revenue / s.revenue * 100)} of revenue.`);
    return parts.join(' ');
  }

  /* ---------- KPI cards ---------- */
  function feeFoot(s) {
    const f = A.applyFees(s.channels, state.fees);
    return f.totalFees > 0 ? `${pct(s.gm, 1)} before fees · ${rm(f.gpAfterFees)} after assumed fees` : `${pct(s.gm, 1)} margin before Shopee fees`;
  }
  function kpis(s) {
    const cards = [
      ['Sales (all channels)', rm(s.revenue), `${int(s.units)} units · clinic estimated`, ''],
      ['Gross profit', rm(s.grossProfit), feeFoot(s), 'good'],
      ['Stock at cost', rm(s.stockValue), `${s.coverMonths == null ? '—' : s.coverMonths.toFixed(1)} months of sales`, ''],
      ['Idle stock cash', rm(s.idleStock), `${pct(s.stockValue ? s.idleStock / s.stockValue * 100 : 0)} of stock · slow / non-moving / excess`, 'warn'],
      ['Profit at risk', rm(s.profitAtRisk), `${int(s.lists.reorder.length)} products below 3 weeks of cover`, 'bad']
    ];
    $('kpis').innerHTML = cards.map(c => `<article class="ov-kpi ${c[3]}"><span>${esc(c[0])}</span><strong class="num">${esc(c[1])}</strong><small>${esc(c[2])}</small></article>`).join('');
  }

  /* ---------- action lists ---------- */
  function badge(text, kind) { return `<span class="ov-badge ${kind}">${esc(text)}</span>`; }

  const TABS = {
    reorder: {
      label: 'Reorder now', total: s => rm(s.profitAtRisk) + ' profit at risk', count: s => s.lists.reorder.length,
      blurb: s => `Below 3 weeks of cover. Buying up to ${A.RULES.TARGET_COVER_MONTHS} months of sales would need about <strong>${rm(s.reorderCash)}</strong> in total — fund it from the idle-stock list.`,
      head: ['Product', 'Stock', 'Sold / mo', 'Cover', 'Suggested order', 'Order cost', 'Profit at risk'],
      row: i => [short(i.product.n), int(i.product.q), int(i.units), i.cover.toFixed(2) + ' mo', int(i.alerts.lowstock.orderUnits) + ' ' + esc(i.product.u || 'units'), rm(i.alerts.lowstock.orderCost), rm(i.alerts.lowstock.rm)],
      right: [1, 2, 3, 4, 5, 6], list: s => s.lists.reorder, money: 6, moneyLabel: 'Profit at risk',
      sort: { 0: i => i.product.n, 1: i => i.product.q, 2: i => i.units, 3: i => i.cover, 4: i => i.alerts.lowstock.orderUnits, 5: i => i.alerts.lowstock.orderCost, 6: i => i.alerts.lowstock.rm },
      csv: i => [i.product.id, i.product.n, i.product.c, i.product.q, i.units, i.cover.toFixed(2), i.alerts.lowstock.orderUnits, i.alerts.lowstock.orderCost.toFixed(2)],
      csvHead: ['id', 'product', 'category', 'stock', 'sold_per_month', 'cover_months', 'suggested_order_units', 'order_cost_rm']
    },
    expiry: {
      label: 'Clear before expiry', total: s => rm(s.expiryRm) + ' at risk', count: s => s.lists.expiry.length,
      blurb: s => `Batches expired or due within ${A.RULES.EXPIRY_DAYS} days that this month's sales rate will not clear. Expired stock should be removed from sale and returned or written off.`,
      head: ['Product', 'First batch', 'Status', 'Units at risk', 'Cost at risk', 'Suggested action'],
      row: i => {
        const e = i.alerts.expiry, d = e.daysToFirst;
        const status = e.expired ? badge('Expired', 'bad') : d <= 30 ? badge(d + ' days', 'bad') : badge(d + ' days', 'warn');
        const units = e.expiredUnits + e.atRiskUnits;
        const action = e.expired ? 'Remove from shelf; return or write off' : d <= 30 ? 'Discount or bundle now' : 'Promote on Shopee / move to front';
        return [short(i.product.n), date(e.first && e.first[0]), status, int(units), rm(e.rm), action];
      },
      right: [3, 4], list: s => s.lists.expiry, money: 4, moneyLabel: 'Cost at risk',
      sort: { 0: i => i.product.n, 1: i => i.alerts.expiry.first && i.alerts.expiry.first[0], 2: i => i.alerts.expiry.expired ? -1e9 : i.alerts.expiry.daysToFirst, 3: i => i.alerts.expiry.expiredUnits + i.alerts.expiry.atRiskUnits, 4: i => i.alerts.expiry.rm },
      csv: i => [i.product.id, i.product.n, i.alerts.expiry.first && i.alerts.expiry.first[0], i.alerts.expiry.expiredUnits, i.alerts.expiry.atRiskUnits, i.alerts.expiry.rm.toFixed(2)],
      csvHead: ['id', 'product', 'first_batch_expiry', 'expired_units', 'at_risk_units', 'cost_at_risk_rm']
    },
    idle: {
      label: 'Free up cash', total: s => rm(s.idleStock) + ' tied up', count: s => s.lists.idle.length,
      blurb: s => `Stock with no sales, slow sales (under ${A.RULES.SLOW_UNITS} units a month) or more than ${A.RULES.HIGH_MONTHS} months of cover. Pause reordering, then bundle, discount or return the largest items first.`,
      head: ['Product', 'Why', 'Stock', 'Sold / mo', 'Cash tied up', 'Suggested action'],
      row: i => {
        const a = i.alerts, kind = a.nonmoving ? 'Non-moving' : a.slow ? 'Slow' : 'Excess';
        const action = a.nonmoving ? 'Stop buying; clear or return' : a.slow ? 'Stop buying; bundle with a fast seller' : 'Skip next order; stock covers ' + i.cover.toFixed(1) + ' mo';
        return [short(i.product.n), badge(kind, a.nonmoving ? 'bad' : a.slow ? 'warn' : 'info'), int(i.product.q), int(i.units), rm(A.idleRm(i)), action];
      },
      right: [2, 3, 4], list: s => s.lists.idle, money: 4, moneyLabel: 'Cash tied up',
      sort: { 0: i => i.product.n, 1: i => i.alerts.nonmoving ? 0 : i.alerts.slow ? 1 : 2, 2: i => i.product.q, 3: i => i.units, 4: i => A.idleRm(i) },
      csv: i => [i.product.id, i.product.n, i.product.c, i.product.q, i.units, A.idleRm(i).toFixed(2)],
      csvHead: ['id', 'product', 'category', 'stock', 'sold_per_month', 'cash_tied_up_rm']
    },
    margin: {
      label: 'Fix pricing', total: s => int(s.lists.margin.length) + ' products', count: s => s.lists.margin.length,
      blurb: s => `Clinic margin below ${A.RULES.GM_CLINIC}% (vaccines ${A.RULES.GM_CLINIC_VACCINE}%), Shopee margin below ${A.RULES.GM_ECOM}%, or clinic price below cost. The “price for target” column is the lowest price that reaches the clinic target.`,
      head: ['Product', 'Cost', 'Clinic price', 'Clinic GM', 'Price for target', 'Shopee MY GM', 'Stock value'],
      row: i => {
        const target = i.cost ? i.cost / (1 - i.clinicMin / 100) : null;
        const gm = i.clinicMargin;
        return [short(i.product.n), i.cost ? rm2(i.cost) : '—', i.price ? rm2(i.price) : '—',
          gm == null ? '—' : badge(gm.toFixed(0) + '%', gm < 0 ? 'bad' : 'warn'),
          target && i.clinicMargin !== null && i.clinicMargin < i.clinicMin ? rm2(target) : '—',
          i.myMargin == null ? '—' : badge(i.myMargin.toFixed(0) + '%', i.myMargin < A.RULES.GM_ECOM ? 'bad' : 'ok'), rm(i.stockValue)];
      },
      right: [1, 2, 3, 4, 5, 6], list: s => s.lists.margin, money: 6, moneyLabel: 'Stock value',
      sort: { 0: i => i.product.n, 1: i => i.cost, 2: i => i.price, 3: i => i.clinicMargin, 4: i => i.cost && i.clinicMargin !== null && i.clinicMargin < i.clinicMin ? i.cost / (1 - i.clinicMin / 100) : null, 5: i => i.myMargin, 6: i => i.stockValue },
      csv: i => [i.product.id, i.product.n, i.cost, i.price, i.clinicMargin == null ? '' : i.clinicMargin.toFixed(1), i.myMargin == null ? '' : i.myMargin.toFixed(1)],
      csvHead: ['id', 'product', 'cost', 'clinic_price', 'clinic_gm_pct', 'shopee_my_gm_pct']
    },
    data: {
      label: 'Data fixes', total: s => int(s.lists.data.length) + ' products', count: s => s.lists.data.length,
      blurb: s => 'Wrong or missing source data distorts every number above. Fix these in Avixo or the Shopee mapping, then re-upload.',
      head: ['Product', 'Category', 'Issue(s)'],
      row: i => [short(i.product.n, 60), esc(i.product.c || '—'), i.warnings.map(w => badge(w, 'warn')).join(' ')],
      right: [], list: s => s.lists.data, money: null, moneyLabel: '',
      sort: { 0: i => i.product.n, 1: i => i.product.c || '' },
      csv: i => [i.product.id, i.product.n, i.warnings.join('; ')], csvHead: ['id', 'product', 'issues']
    }
  };

  function renderTabs() {
    const s = state.summary;
    $('tabs').innerHTML = Object.entries(TABS).map(([k, t]) =>
      `<button role="tab" type="button" class="ov-tab" data-tab="${k}" aria-selected="${k === state.tab}"><span>${t.label}</span><b>${int(t.count(s))}</b></button>`).join('');
    $('tabs').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { state.tab = b.dataset.tab; state.showAll = false; state.sort = null; renderTabs(); renderPanel(); }));
  }

  function renderPanel() {
    const s = state.summary, t = TABS[state.tab], list = A.sortRows(t.list(s), t.sort, state.sort);
    const rows = state.showAll ? list : list.slice(0, 12);
    // The engine's own order is "biggest money first", so the money column shows the active arrow until the user picks another.
    const active = state.sort ? state.sort.col : t.money, dir = state.sort ? state.sort.dir : 'desc';
    const head = t.head.map((h, k) => {
      const cls = t.right.includes(k) ? 'r' : '';
      if (!t.sort[k]) return `<th class="${cls}">${h}</th>`;
      const on = active === k;
      return `<th class="${cls}" aria-sort="${on ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}"><button type="button" class="ov-sort${on ? ' on' : ''}" data-col="${k}">${h}<span class="ov-sort-arrow">${on ? (dir === 'asc' ? ' ▲' : ' ▼') : ' ↕'}</span></button></th>`;
    }).join('');
    const body = rows.map(i => '<tr>' + t.row(i).map((c, k) => `<td class="${t.right.includes(k) ? 'r num' : ''}">${k === 0 ? esc(c) : c}</td>`).join('') + '</tr>').join('');
    $('actionPanel').innerHTML = `
      <div class="ov-panel-top"><p>${t.blurb(s)}</p><div class="ov-panel-tools"><span class="ov-total">${esc(t.total(s))}</span>${state.sort && t.money != null ? `<button type="button" class="ov-btn" id="sortReset">Biggest money first</button>` : ''}<button type="button" class="ov-btn" id="csvBtn">↓ Download CSV</button></div></div>
      ${list.length ? `<div class="ov-tablewrap"><table class="ov-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
      ${list.length > 12 ? `<button type="button" class="ov-btn ov-more" id="moreBtn">${state.showAll ? 'Show top 12 only' : 'Show all ' + int(list.length)}</button>` : ''}` : '<p class="ov-empty">Nothing to action here this month.</p>'}`;
    const more = $('moreBtn'); if (more) more.addEventListener('click', () => { state.showAll = !state.showAll; renderPanel(); });
    $('csvBtn').addEventListener('click', () => downloadCsv(t, list));
    const reset = $('sortReset'); if (reset) reset.addEventListener('click', () => { state.sort = null; renderPanel(); });
    $('actionPanel').querySelectorAll('.ov-sort').forEach(b => b.addEventListener('click', () => {
      const col = Number(b.dataset.col), cur = state.sort ? state.sort : (t.money != null ? { col: t.money, dir: 'desc' } : null);
      // Same column: flip. New column: text starts A-Z, numbers start highest first.
      const sample = list.length ? t.sort[col](list[0]) : 0;
      state.sort = cur && cur.col === col ? { col, dir: cur.dir === 'desc' ? 'asc' : 'desc' } : { col, dir: typeof sample === 'string' ? 'asc' : 'desc' };
      if (state.sort.col === t.money && state.sort.dir === 'desc') state.sort = null;   // back to the default order
      renderPanel();
    }));
  }

  function downloadCsv(t, list) {
    const cell = v => { v = v == null ? '' : String(v); if (/^[=+\-@\t\r]/.test(v)) v = "'" + v; return '"' + v.replace(/"/g, '""') + '"'; };  // neutralise spreadsheet formulas
    const csv = [t.csvHead].concat(list.map(t.csv)).map(r => r.map(cell).join(',')).join('\r\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `firstwell-essentials-${state.tab}-${state.data.meta.month}.csv`;
    document.body.append(a); a.click(); a.remove();
  }

  /* ---------- concentration, channels, categories ---------- */
  function renderAbc(s) {
    const a = s.abc, tot = s.items.length;
    const row = (k, label, d, color) => `<div class="ov-abc-row"><div class="ov-abc-name"><b style="background:${color}">${k}</b><span>${label}<small>${int(d.count)} products · ${pct(d.count / tot * 100)} of range</small></span></div>
      <div class="ov-abc-bars"><div><i style="width:${(d.revShare * 100).toFixed(1)}%;background:${color}"></i></div><span>${pct(d.revShare * 100)} of revenue</span><div><i style="width:${(d.stockShare * 100).toFixed(1)}%;background:${color};opacity:.45"></i></div><span>${pct(d.stockShare * 100)} of stock value</span></div></div>`;
    $('abcCard').innerHTML = `<div class="ov-sec-head"><div><p class="ov-eyebrow">CONCENTRATION</p><h2>Few products carry the business</h2></div></div>
      ${row('A', 'Top sellers (first 80% of revenue)', a.A, '#178f7c')}${row('B', 'Middle (next 15%)', a.B, '#2a5da8')}${row('C', 'Tail (last 5% and zero sales)', a.C, '#b06a0a')}
      <p class="ov-note">${pct(a.C.stockShare * 100)} of your stock value is in class C products that earn ${pct(a.C.revShare * 100)} of revenue. Keep class A in stock first; review class C ranges before reordering.</p>`;
  }

  function renderChannels(s) {
    const f = A.applyFees(s.channels, state.fees), max = Math.max(...s.channels.map(c => c.revenue), 1);
    const hasFees = f.totalFees > 0;
    const input = (k, label) => `<label class="ov-fee"><span>${label}</span><input type="number" min="0" max="100" step="0.1" inputmode="decimal" data-fee="${k}" value="${state.fees[k] || ''}" placeholder="0"><b>%</b></label>`;
    $('channelCard').innerHTML = `<div class="ov-sec-head"><div><p class="ov-eyebrow">CHANNELS</p><h2>Where the profit comes from</h2></div></div>
      <div class="ov-fees"><div><strong>Shopee fee assumption</strong><small>Commission + service + payment fees as % of sales. Your own figure; saved in this browser only.</small></div><div class="ov-fee-inputs">${input('my', 'Shopee MY')}${input('sg', 'Shopee SG')}</div></div>
      <table class="ov-table ov-compact"><thead><tr><th>Channel</th><th class="r">Revenue</th><th class="r">Units</th><th class="r">Avg price</th><th class="r">GM before fees</th>${hasFees ? '<th class="r">Fees</th><th class="r">GM after fees</th>' : ''}</tr></thead><tbody>
      ${f.channels.map(c => `<tr><td>${esc(c.name)}<div class="ov-minibar"><i style="width:${(c.revenue / max * 100).toFixed(0)}%"></i></div></td><td class="r num">${rm(c.revenue)}</td><td class="r num">${int(c.units)}</td><td class="r num">${c.asp == null ? '—' : rm2(c.asp)}</td><td class="r num">${pct(c.gm, 1)}</td>${hasFees ? `<td class="r num">${c.fee > 0 ? rm(c.fee) + ' <small>(' + c.feePct + '%)</small>' : '—'}</td><td class="r num">${pct(c.gmAfterFees, 1)}</td>` : ''}</tr>`).join('')}</tbody></table>
      <p class="ov-note">${hasFees ? `With your assumed fees, total gross profit is ${rm(f.gpAfterFees)} (${rm(f.totalFees)} lower). ` : 'Enter your Shopee fee percentages above to see margins after fees. Until then margins exclude fees, so Shopee looks better than it is. '}Shipping subsidies and ads are not included. Clinic revenue is units × list price, not receipts. Singapore sales are shown in RM.</p>`;
    $('channelCard').querySelectorAll('input[data-fee]').forEach(inp => inp.addEventListener('change', () => {
      state.fees[inp.dataset.fee] = clampPct(inp.value); saveFees(); kpis(state.summary); renderChannels(state.summary);
      const again = $('channelCard').querySelector(`input[data-fee="${inp.dataset.fee}"]`); if (again) again.focus();
    }));
  }

  function renderCategories(s) {
    $('catCard').innerHTML = `<div class="ov-sec-head"><div><p class="ov-eyebrow">CATEGORY SCORECARD</p><h2>Profit, stock and idle cash by category</h2></div></div>
      <div class="ov-tablewrap"><table class="ov-table"><thead><tr><th>Category</th><th class="r">Products</th><th class="r">Revenue</th><th class="r">Gross profit</th><th class="r">GM</th><th class="r">Stock at cost</th><th class="r">Cover</th><th class="r">Idle share of stock</th></tr></thead><tbody>
      ${s.categories.map(c => `<tr><td>${esc(c.name)}</td><td class="r num">${int(c.products)}</td><td class="r num">${rm(c.revenue)}</td><td class="r num">${rm(c.grossProfit)}</td><td class="r num">${pct(c.gm)}</td><td class="r num">${rm(c.stockValue)}</td><td class="r num">${c.coverMonths == null ? '—' : c.coverMonths.toFixed(1) + ' mo'}</td><td class="r num">${c.stockValue > 0 ? badge(pct(c.idleShare * 100), c.idleShare > .5 ? 'bad' : c.idleShare > .25 ? 'warn' : 'ok') : '—'}</td></tr>`).join('')}</tbody></table></div>`;
  }

  function renderRules() {
    const R = A.RULES;
    $('rulesCard').innerHTML = `<details><summary>How these numbers are worked out</summary><ul class="ov-rules">
      <li><b>Revenue</b> = clinic units × clinic price (estimate) + Shopee MY confirmed order value + Shopee SG paid order value in RM.</li>
      <li><b>Gross profit</b> = revenue − units sold × latest cost. Excludes Shopee fees, staff, rent and discounts.</li>
      <li><b>Cover</b> = stock ÷ units sold this month (all channels). Low is under ${R.LOW_MONTHS} month; excess is over ${R.HIGH_MONTHS} months.</li>
      <li><b>Suggested order</b> = enough to reach ${R.TARGET_COVER_MONTHS} months of this month's sales. Adjust for supplier minimums, seasonality and lead time.</li>
      <li><b>Expiry at risk</b> = batch units this month's sales rate will not clear before the batch date, plus units already expired.</li>
      <li><b>Idle stock</b> = non-moving, slow (under ${R.SLOW_UNITS} units) and excess (above ${R.HIGH_MONTHS} months) stock at cost.</li>
      <li>Only one reporting month is loaded at a time. Trends over time are on the Live Sales page.</li></ul></details>`;
  }


  /* ---------- weekly sales trend (from the Weekly Sales uploads) ---------- */
  const CH_COLOR = { clinic: '#b06a0a', shopee_my: '#2a5da8', shopee_sg: '#178f7c' };
  const cur = (v, c) => v == null ? 'Units only' : (c === 'SGD' ? 'S$ ' : 'RM ') + Math.round(v).toLocaleString('en-MY');
  const chg = v => v == null ? '<span class="ov-muted">—</span>' : `<span class="ov-delta ${v >= 5 ? 'up' : v <= -5 ? 'down' : ''}">${v > 0 ? '▲' : v < 0 ? '▼' : '■'} ${Math.abs(v).toFixed(0)}%</span>`;

  function trendChart(trend) {
    const starts = [...new Set(trend.flatMap(c => c.series.map(x => x.start)))].sort();
    if (starts.length < 2) return '';
    const W = 720, H = 220, L = 44, R = 12, T = 12, B = 30;
    const max = Math.max(...trend.flatMap(c => c.series.map(x => x.perDay)), 1);
    const nice = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / nice * 2) / 2 * nice || 1;
    const X = i => L + (W - L - R) * (starts.length === 1 ? .5 : i / (starts.length - 1));
    const Y = v => T + (H - T - B) * (1 - v / top);
    const grid = [0, .5, 1].map(f => `<g><line x1="${L}" x2="${W - R}" y1="${Y(top * f)}" y2="${Y(top * f)}" stroke="#e6e0d3"/><text x="${L - 8}" y="${Y(top * f) + 4}" text-anchor="end" font-size="11" fill="#5d6965">${(top * f).toFixed(top < 10 ? 1 : 0)}</text></g>`).join('');
    const labels = starts.map((d, i) => (starts.length <= 8 || i % Math.ceil(starts.length / 8) === 0) ? `<text x="${X(i)}" y="${H - 8}" text-anchor="middle" font-size="11" fill="#5d6965">${esc(date(d).replace(/ 20\d\d$/, ''))}</text>` : '').join('');
    const lines = trend.map(c => {
      const pts = c.series.map(x => [X(starts.indexOf(x.start)), Y(x.perDay)]);
      return `<polyline fill="none" stroke="${CH_COLOR[c.channel] || '#555'}" stroke-width="2.5" stroke-linejoin="round" points="${pts.map(q => q.join(',')).join(' ')}"/>` +
        pts.map(q => `<circle cx="${q[0]}" cy="${q[1]}" r="3.5" fill="${CH_COLOR[c.channel] || '#555'}"/>`).join('');
    }).join('');
    const sr = trend.map(c => `${c.label}: ` + c.series.map(x => `${x.start} ${x.perDay.toFixed(1)}/day`).join(', ')).join('. ');
    return `<div class="ov-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Units sold per day by channel, by upload period. ${esc(sr)}">${grid}${labels}${lines}</svg>
      <div class="ov-legend">${trend.map(c => `<span><i style="background:${CH_COLOR[c.channel] || '#555'}"></i>${esc(c.label)}</span>`).join('')}<small>Units per day, so periods of different length compare fairly</small></div></div>`;
  }

  function renderWeekly(summary) {
    const card = $('weeklyCard');
    const weeks = summary && summary.weeks || [];
    const head = '<div class="ov-sec-head"><div><p class="ov-eyebrow">WEEKLY TREND</p><h2>Is demand speeding up or slowing down?</h2></div><a class="ov-btn" href="/upload.html#weekly">Upload weekly sales →</a></div>';
    if (!weeks.length) {
      card.innerHTML = head + '<p class="ov-empty">No weekly sales uploaded yet. After your first weekend upload on the Upload Data page (Weekly sales tab), this shows units per day for Clinic, Shopee MY and Shopee SG. Trends become useful from the second upload.</p>';
      return;
    }
    const trend = A.weeklyTrend(weeks);
    const rows = trend.map(c => `<tr><td>${esc(c.label)}<div class="ov-sub">${c.periods} upload${c.periods > 1 ? 's' : ''}</div></td>
      <td class="r num">${esc(date(c.last.start))} – ${esc(date(c.last.end))}</td><td class="r num">${c.last.perDay.toFixed(1)}</td>
      <td class="r">${chg(c.changePct)}</td><td class="r">${chg(c.vsAvgPct)}</td><td class="r num">${esc(cur(c.last.revenue, c.currency))}</td></tr>`).join('');
    const movers = trend.filter(c => c.changePct != null && Math.abs(c.changePct) >= 15);
    const note = movers.length
      ? movers.map(c => `${esc(c.label)} is ${c.changePct > 0 ? 'up' : 'down'} ${Math.abs(c.changePct).toFixed(0)}% per day on the previous upload${c.changePct > 0 ? ': check fast sellers before they run short.' : ': hold reorders for slowing lines until it settles.'}`).join(' ')
      : 'No channel moved more than 15% per day versus its previous upload.';
    card.innerHTML = head + `<p class="ov-trend-note">${note}</p>${trendChart(trend)}
      <div class="ov-tablewrap"><table class="ov-table"><thead><tr><th>Channel</th><th class="r">Latest period</th><th class="r">Units / day</th><th class="r">vs previous</th><th class="r">vs last 4 avg</th><th class="r">Latest revenue</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="ov-note">Shopee MY is in MYR and Shopee SG in SGD; they are never added together. Clinic is units only. Only one upload per channel is shown per period; overlapping periods are blocked at upload.</p>`;
  }
  async function loadWeekly() {
    try { renderWeekly(await getJson('/api/weekly-sales/summary')); }
    catch (e) { $('weeklyCard').innerHTML = '<div class="ov-sec-head"><div><p class="ov-eyebrow">WEEKLY TREND</p><h2>Weekly sales</h2></div></div><p class="ov-empty">Weekly sales could not be loaded here. Open the Weekly Sales page to check uploads.</p>'; }
  }

  /* ---------- boot ---------- */
  function show(key) {
    return loadMonth(key).then(d => {
      state.data = d; state.summary = A.summarise(d.products, d.meta.today);
      $('lede').innerHTML = narrative(state.summary, d.meta);
      $('asof').textContent = 'Stock as of ' + (d.meta.invSnapshot || d.meta.today);
      kpis(state.summary); renderTabs(); renderPanel(); renderAbc(state.summary); renderChannels(state.summary); renderCategories(state.summary); renderRules();
      $('body').hidden = false; $('err').hidden = true;
      if (!state.weeklyLoaded) { state.weeklyLoaded = true; loadWeekly(); }
    });
  }
  function fail(e) { $('err').hidden = false; $('err').textContent = 'Could not load the dashboard data: ' + e.message; }

  (async function init() {
    loadFees();
    try {
      const m = await loadMonths(); state.source = m.source; state.months = m.list;
      const sel = $('monthSel');
      sel.innerHTML = state.months.slice().reverse().map(x => `<option value="${esc(x.key)}">${esc(x.label || x.key)}</option>`).join('');
      sel.disabled = false;
      sel.addEventListener('change', () => { state.showAll = false; show(sel.value).catch(fail); });
      await show(sel.value);
    } catch (e) { fail(e); }
  })();
})();
