/* FirstWell Essentials analysis engine — pure functions, no DOM.
   Definitions match the existing Inventory / Analytics pages so numbers agree.
   Used by the Action Centre (overview.html) and covered by tests/overview.test.js. */
(function (root) {
  'use strict';

  const RULES = {
    SLOW_UNITS: 5, HIGH_MONTHS: 3, EXPIRY_DAYS: 90, LOW_MONTHS: 0.75, LEAD_MONTHS: 0.5,
    TARGET_COVER_MONTHS: 1.5,                 // reorder up to this many months of sales
    GM_CLINIC: 25, GM_CLINIC_VACCINE: 10, GM_ECOM: 8
  };

  const num = v => (typeof v === 'number' && isFinite(v) ? v : 0);
  const margin = (price, cost) => (!price || !cost ? null : ((price - cost) / price) * 100);
  const daysBetween = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 86400000);

  function analyseProduct(p, today) {
    const cost = p.lc || null, price = p.p || null;
    const cu = num(p.s), mu = num(p.my && p.my.units), su = num(p.sg && p.sg.units);
    const units = cu + mu + su;
    const clinicSales = price ? cu * price : 0;
    const mySales = num(p.my && p.my.sales), sgSales = num(p.sg && p.sg.sales);
    const revenue = clinicSales + mySales + sgSales;
    const stockValue = p.val || (cost ? num(p.q) * cost : 0);
    const q = num(p.q);
    const cover = units > 0 ? q / units : null;
    const clinicMin = p.c === 'Vaccine' ? RULES.GM_CLINIC_VACCINE : RULES.GM_CLINIC;
    const r = {
      product: p, cost, price, units, clinicUnits: cu, myUnits: mu, sgUnits: su,
      clinicSales, mySales, sgSales, revenue, cogs: units * (cost || 0),
      stockValue, cover, clinicMin, alerts: {}, warnings: [],
      clinicMargin: margin(price, cost),
      myPrice: p.my && p.my.price || null, sgPrice: p.sg && p.sg.price || null
    };
    r.myMargin = margin(r.myPrice, cost);
    r.sgMargin = margin(r.sgPrice, cost);

    if (!cost) r.warnings.push('No cost price');
    if (!p.id) r.warnings.push('Not in inventory report');
    if ((p.c === 'Medication' || p.c === 'Vaccine') && !p.x && q > 0) r.warnings.push('No expiry date');
    if (r.clinicMargin !== null && r.clinicMargin < -50) r.warnings.push('Clinic price below cost');
    if (p.mm) r.warnings.push('Stock mismatch between reports');
    if ((p.my && !p.my.listed) || (p.sg && !p.sg.listed)) r.warnings.push('Shopee listing not found');

    if (q > 0 && units === 0) r.alerts.nonmoving = { rm: stockValue };
    else if (q > 0 && units < RULES.SLOW_UNITS) r.alerts.slow = { rm: stockValue };
    else if (units >= RULES.SLOW_UNITS && cover > RULES.HIGH_MONTHS) {
      const excessUnits = Math.max(0, q - RULES.HIGH_MONTHS * units);
      r.alerts.high = { rm: cost ? excessUnits * cost : 0, excessUnits };
    }

    if (p.b) {
      const perDay = units / 30;
      let allocated = 0, atRiskCost = 0, atRiskUnits = 0, expiredUnits = 0, expiredCost = 0, first = null, within = false;
      p.b.forEach(b => {
        if (!b[0]) return;
        const d = daysBetween(b[0], today);
        if (d < 0) { expiredUnits += b[1]; expiredCost += b[1] * (cost || 0); if (!first) first = b; return; }
        if (d > RULES.EXPIRY_DAYS) return;
        within = true; if (!first) first = b;
        const canSell = Math.max(0, perDay * d - allocated);
        const risk = Math.max(0, Math.round(b[1] - canSell));
        allocated += Math.min(b[1], canSell);
        atRiskCost += risk * (cost || 0); atRiskUnits += risk;
      });
      if (expiredUnits > 0 || within) {
        r.alerts.expiry = {
          rm: expiredCost + atRiskCost, expiredUnits, expiredCost, atRiskUnits, atRiskCost,
          first, daysToFirst: first ? daysBetween(first[0], today) : null, expired: expiredUnits > 0
        };
      }
    }

    if (r.clinicMargin !== null && r.clinicMargin < clinicMin && r.clinicMargin >= -50) r.alerts.marginClinic = { rm: stockValue };
    if ((r.myMargin !== null && r.myMargin < RULES.GM_ECOM) || (r.sgMargin !== null && r.sgMargin < RULES.GM_ECOM)) r.alerts.marginEcom = { rm: stockValue };

    if (units > 0 && cover < RULES.LOW_MONTHS) {
      const profitPerUnit = cost && revenue > 0 ? Math.max(0, revenue / units - cost) : 0;
      const gap = Math.max(0, RULES.LEAD_MONTHS - cover);
      const orderUnits = Math.max(1, Math.ceil(RULES.TARGET_COVER_MONTHS * units - q));
      r.alerts.lowstock = { rm: gap * units * profitPerUnit, orderUnits, orderCost: orderUnits * (cost || 0) };
    }
    return r;
  }

  /** Revenue concentration. A = items making the first 80% of revenue, B = next 15%, C = last 5% (+ zero sellers). */
  function abcClasses(items) {
    const total = items.reduce((s, i) => s + i.revenue, 0);
    const sorted = items.slice().sort((a, b) => b.revenue - a.revenue);
    const out = { A: [], B: [], C: [] };
    let run = 0;
    sorted.forEach(i => {
      const before = total > 0 ? run / total : 1;
      run += i.revenue;
      (before < 0.8 && i.revenue > 0 ? out.A : before < 0.95 && i.revenue > 0 ? out.B : out.C).push(i);
    });
    const sum = (arr, k) => arr.reduce((s, i) => s + i[k], 0);
    const totalStock = items.reduce((s, i) => s + i.stockValue, 0);
    const shape = arr => ({
      count: arr.length, revenue: sum(arr, 'revenue'), stockValue: sum(arr, 'stockValue'),
      revShare: total > 0 ? sum(arr, 'revenue') / total : 0,
      stockShare: totalStock > 0 ? sum(arr, 'stockValue') / totalStock : 0
    });
    return { A: shape(out.A), B: shape(out.B), C: shape(out.C), items: out };
  }

  function categoryScorecard(items) {
    const map = new Map();
    items.forEach(i => {
      const k = i.product.c || 'Uncategorised';
      const c = map.get(k) || { name: k, products: 0, revenue: 0, cogs: 0, stockValue: 0, idle: 0, units: 0 };
      c.products++; c.revenue += i.revenue; c.cogs += i.cogs; c.stockValue += i.stockValue; c.units += i.units;
      c.idle += ['nonmoving', 'slow', 'high'].reduce((s, a) => s + (i.alerts[a] ? i.alerts[a].rm : 0), 0);
      map.set(k, c);
    });
    return [...map.values()].map(c => ({
      ...c, grossProfit: c.revenue - c.cogs,
      gm: c.revenue > 0 ? (c.revenue - c.cogs) / c.revenue * 100 : null,
      idleShare: c.stockValue > 0 ? c.idle / c.stockValue : 0,
      coverMonths: c.cogs > 0 ? c.stockValue / c.cogs : null
    })).sort((a, b) => b.revenue - a.revenue);
  }

  function channelEconomics(items) {
    const ch = {
      clinic: { name: 'Clinic (est.)', units: 0, revenue: 0, cogs: 0 },
      my: { name: 'Shopee MY', units: 0, revenue: 0, cogs: 0 },
      sg: { name: 'Shopee SG', units: 0, revenue: 0, cogs: 0 }
    };
    items.forEach(i => {
      const c = i.cost || 0;
      ch.clinic.units += i.clinicUnits; ch.clinic.revenue += i.clinicSales; ch.clinic.cogs += i.clinicUnits * c;
      ch.my.units += i.myUnits; ch.my.revenue += i.mySales; ch.my.cogs += i.myUnits * c;
      ch.sg.units += i.sgUnits; ch.sg.revenue += i.sgSales; ch.sg.cogs += i.sgUnits * c;
    });
    return Object.values(ch).map(c => ({
      ...c, grossProfit: c.revenue - c.cogs,
      gm: c.revenue > 0 ? (c.revenue - c.cogs) / c.revenue * 100 : null,
      asp: c.units > 0 ? c.revenue / c.units : null
    }));
  }

  function summarise(products, today) {
    const items = products.map(p => analyseProduct(p, today));
    const sum = (f) => items.reduce((s, i) => s + f(i), 0);
    const revenue = sum(i => i.revenue), cogs = sum(i => i.cogs), stock = sum(i => i.stockValue);
    const idle = sum(i => ['nonmoving', 'slow', 'high'].reduce((s, a) => s + (i.alerts[a] ? i.alerts[a].rm : 0), 0));
    const by = (key, filter) => items.filter(filter || (i => i.alerts[key])).sort((a, b) => (b.alerts[key] ? b.alerts[key].rm : 0) - (a.alerts[key] ? a.alerts[key].rm : 0));
    const lists = {
      // Products whose stock is kept at FirstStep have 0 stock here by design: not a FirstWell reorder.
      reorder: by('lowstock', i => i.alerts.lowstock && !((i.product.fl || []).includes('Stock kept at FirstStep'))),
      expiry: by('expiry'),
      idle: items.filter(i => i.alerts.nonmoving || i.alerts.slow || i.alerts.high)
        .sort((a, b) => idleRm(b) - idleRm(a)),
      margin: items.filter(i => i.alerts.marginClinic || i.alerts.marginEcom || i.warnings.includes('Clinic price below cost'))
        .sort((a, b) => b.stockValue - a.stockValue),
      data: items.filter(i => i.warnings.length)
    };
    return {
      items, lists, revenue, cogs, grossProfit: revenue - cogs,
      gm: revenue > 0 ? (revenue - cogs) / revenue * 100 : 0,
      stockValue: stock, idleStock: idle,
      coverMonths: cogs > 0 ? stock / cogs : null,
      units: sum(i => i.units),
      abc: abcClasses(items), categories: categoryScorecard(items), channels: channelEconomics(items),
      reorderCash: lists.reorder.reduce((s, i) => s + i.alerts.lowstock.orderCost, 0),
      expiryRm: lists.expiry.reduce((s, i) => s + i.alerts.expiry.rm, 0),
      profitAtRisk: lists.reorder.reduce((s, i) => s + i.alerts.lowstock.rm, 0)
    };
  }
  function idleRm(i) { return ['nonmoving', 'slow', 'high'].reduce((s, a) => s + (i.alerts[a] ? i.alerts[a].rm : 0), 0); }

  /** Weekly (or any period) uploads -> per-channel series of units per day, with change vs the previous period.
      Periods can be longer or shorter than 7 days, so everything is compared per day. */
  function weeklyTrend(weeks) {
    const days = w => Math.max(1, Math.round((Date.parse(w.period_end) - Date.parse(w.period_start)) / 86400000) + 1);
    const byChannel = {};
    (weeks || []).forEach(w => {
      const c = byChannel[w.channel] || (byChannel[w.channel] = { channel: w.channel, label: w.channel_label, currency: w.currency, series: [] });
      const d = days(w);
      c.series.push({ start: w.period_start, end: w.period_end, days: d, units: num(w.units), perDay: num(w.units) / d,
                      revenue: w.revenue == null ? null : num(w.revenue), revenuePerDay: w.revenue == null ? null : num(w.revenue) / d });
    });
    return Object.values(byChannel).map(c => {
      c.series.sort((a, b) => a.start.localeCompare(b.start));
      const n = c.series.length, last = c.series[n - 1], prev = n > 1 ? c.series[n - 2] : null;
      const recent = c.series.slice(-4);
      const u = recent.reduce((s, x) => s + x.units, 0), dd = recent.reduce((s, x) => s + x.days, 0);
      return Object.assign(c, {
        last, prev, periods: n,
        changePct: prev && prev.perDay > 0 ? (last.perDay - prev.perDay) / prev.perDay * 100 : null,
        avgPerDay4: dd > 0 ? u / dd : null,
        vsAvgPct: n > 1 && dd > 0 && u > 0 ? (last.perDay - u / dd) / (u / dd) * 100 : null
      });
    }).sort((a, b) => a.label.localeCompare(b.label));
  }

  /** Apply an assumed Shopee fee (percent of sales) per marketplace. Fees are an assumption supplied by the user,
      never a number from the data. Clinic carries no marketplace fee. */
  function applyFees(channels, fees) {
    const pctFor = c => c.name === 'Shopee MY' ? num(fees && fees.my) : c.name === 'Shopee SG' ? num(fees && fees.sg) : 0;
    const out = channels.map(c => {
      const fee = c.revenue * Math.min(Math.max(pctFor(c), 0), 100) / 100;
      const gp = c.revenue - c.cogs - fee;
      return Object.assign({}, c, { feePct: pctFor(c), fee, gpAfterFees: gp, gmAfterFees: c.revenue > 0 ? gp / c.revenue * 100 : null });
    });
    return { channels: out, totalFees: out.reduce((a, c) => a + c.fee, 0), gpAfterFees: out.reduce((a, c) => a + c.gpAfterFees, 0) };
  }

  /** Re-order an action list for display. getters[col](item) gives the sort value (number or text; null/NaN go last).
      sort = null keeps the engine's own order (biggest money first). Numbers start highest-first, text starts A-Z. */
  function sortRows(list, getters, sort) {
    if (!sort || !getters || !getters[sort.col]) return list;
    const get = getters[sort.col], dir = sort.dir === 'asc' ? 1 : -1;
    const empty = v => v == null || (typeof v === 'number' && !isFinite(v));
    return list.map((item, idx) => ({ item, idx, v: get(item) })).sort((a, b) => {
      if (empty(a.v) || empty(b.v)) return empty(a.v) && empty(b.v) ? a.idx - b.idx : empty(a.v) ? 1 : -1;
      const c = typeof a.v === 'string' || typeof b.v === 'string' ? String(a.v).localeCompare(String(b.v), 'en', { sensitivity: 'base' }) : a.v - b.v;
      return c ? dir * c : a.idx - b.idx;
    }).map(x => x.item);
  }

  const api = { sortRows, applyFees, weeklyTrend, RULES, analyseProduct, abcClasses, categoryScorecard, channelEconomics, summarise, idleRm, daysBetween, margin };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FSAnalysis = api;
})(typeof window !== 'undefined' ? window : globalThis);
