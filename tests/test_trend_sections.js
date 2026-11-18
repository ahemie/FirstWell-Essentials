// Run: node tests/test_trend_sections.js — unit test for the per-channel price chart + month table on the product page.
// No database, no browser: pulls the needed functions out of assets/js/product.js and runs them on stub data.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'assets', 'js', 'product.js'), 'utf8');
const grab = (re, label) => { const m = src.match(re); assert.ok(m, 'could not find ' + label); return m[0]; };
const fn = name => grab(new RegExp('^function ' + name + '\\(.*?\\n\\}\\n', 'ms'), name);
const code = [
  grab(/^const MONTHS = .*$/m, 'MONTHS'),
  fn('escapeHtml'), fn('formatNumber'),
  grab(/^const TREND_CHANNELS = \[.*?\n\];/ms, 'TREND_CHANNELS'),
  ...['trendSeries', 'clinicReferencePrice', 'channelMonthlyPriceSeries', 'trendReported', 'trendNiceStep', 'trendAxisLabel',
      'trendSegments', 'trendMonthName', 'trendPriceChart', 'trendChannelTable', 'renderProductTrends'].map(fn),
  'this.api = {trendNiceStep, trendPriceChart, trendChannelTable, renderProductTrends, channels: TREND_CHANNELS};'
].join('\n');
const mk = (trends, selected) => {
  const ctx = { window: { FIRSTSTEP_TRENDS: trends }, state: { selectedMonth: selected, monthData: { meta: { fx: 1 } } }, console };
  vm.createContext(ctx); vm.runInContext(code, ctx); return ctx.api;
};
const trends = {
  meta: { months: ['2026-07', '2026-08', '2026-09'] },
  products: { 7: {
    '2026-07': { my: { units: 61, revenue: 3453.21 }, sg: { units: null, revenue: null }, clinic: { units: null, revenue: null } },
    '2026-08': { my: { units: 0, revenue: 0 }, sg: { units: 3, revenue: 60.72 }, clinic: { units: null, revenue: null } },
    '2026-09': { my: { units: 81, revenue: 4651.83 }, sg: { units: 2, revenue: 40.08 }, clinic: { units: 2, revenue: 85.8 } }
  } }
};
const api = mk(trends, '2026-09');
const P = { id: 7, p: 42.9 };
const ch = k => api.channels.find(c => c.key === k);
const rowsOf = html => [...html.matchAll(/<tr><td>(.*?)<\/td>(.*?)<\/tr>/g)].map(m => ({
  month: m[1], cells: [...m[2].matchAll(/<td[^>]*>(.*?)<\/td>/g)].map(c => c[1].replace(/<small.*?<\/small>/, '').trim())
}));

// axis steps are round numbers
assert.strictEqual(api.trendNiceStep(14.36, [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10], 0), 15);
assert.strictEqual(api.trendNiceStep(0, [1, 2], 1), 1);

// ---- chart: price only, left scale only. No dashed units line, no right scale. ----
const my = api.trendPriceChart(P, ch('my'));
assert.ok(my.includes('<svg') && my.includes('RM PRICE / UNIT'));
assert.ok(!my.includes('stroke-dasharray="7 6"'), 'no dashed units line');
assert.ok(!my.includes('UNITS SOLD'), 'no right-hand units scale');
assert.ok(my.includes('Jul 2026 • RM 56.61 • 61 units'), 'tooltip still shows month, price and units');
assert.ok(!/NaN|undefined|null/.test(my));
const sg = api.trendPriceChart(P, ch('sg'));
assert.ok(sg.includes('S$ PRICE / UNIT'));
assert.ok(!sg.includes('Jul 2026 • S$'), 'a month with no report gets no price dot');
assert.ok(sg.includes('Aug 2026 • S$ 20.24 • 3 units'));
const cl = api.trendPriceChart(P, ch('clinic'));
assert.ok(cl.includes('Sep 2026 • RM 42.90 • 2 units'), 'clinic shows its one reference price');
assert.strictEqual((cl.match(/<path d=[^>]*stroke="#0e5a52"/g) || []).length, 0, 'a single clinic price draws no line');
const none = api.trendPriceChart({ id: 999, p: null }, ch('sg'));
assert.ok(none.includes('No price recorded for this channel yet.'), 'channel with no price shows a message');

// ---- table: one per channel, Month | Units sold | Price / unit ----
const tMy = rowsOf(api.trendChannelTable(P, ch('my')));
assert.deepStrictEqual(tMy.map(r => r.month), ['Jul 2026', 'Aug 2026', 'Sep 2026']);
assert.deepStrictEqual(tMy.map(r => r.cells), [['61', 'RM 56.61'], ['0', '—'], ['81', 'RM 57.43']], 'reported 0 stays 0; no price when nothing sold');
const tSg = rowsOf(api.trendChannelTable(P, ch('sg')));
assert.deepStrictEqual(tSg.map(r => r.cells), [['—', '—'], ['3', 'S$ 20.24'], ['2', 'S$ 20.04']], 'unreported month is a dash, not zero');
const tCl = api.trendChannelTable(P, ch('clinic'));
assert.deepStrictEqual(rowsOf(tCl).map(r => r.cells), [['—', '—'], ['—', '—'], ['2', 'RM 42.90']]);
assert.ok(tCl.includes('Latest reference'), 'clinic price is marked as a reference');
assert.ok(!/NaN|undefined|null/.test(tCl));

// ---- section: three separate channel blocks, each with its own chart and table; no dropdown ----
const section = api.renderProductTrends(P);
assert.strictEqual((section.match(/class="trend-channel-group"/g) || []).length, 3);
assert.strictEqual((section.match(/<table class="trend-monthly-table"/g) || []).length, 3, 'one table per channel');
assert.strictEqual((section.match(/<svg /g) || []).length, 3, 'one chart per channel');
['Clinic', 'Shopee MY', 'Shopee SG'].forEach(l => assert.ok(section.includes('<h3>' + l + '</h3>'), l + ' has its own heading'));
assert.ok(!section.includes('<select'), 'no channel dropdown');
assert.ok(section.indexOf('<h3>Clinic</h3>') < section.indexOf('<h3>Shopee MY</h3>') && section.indexOf('<h3>Shopee MY</h3>') < section.indexOf('<h3>Shopee SG</h3>'));
console.log('PASS: per-channel trend chart + table');
