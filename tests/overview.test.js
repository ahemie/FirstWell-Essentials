// Run: node tests/overview.test.js — pure unit tests for the Action Centre engine. No database, no browser.
const assert = require('assert');
const A = require('../assets/js/analysis.js');
const today = '2026-10-01';
const P = (o) => Object.assign({ id: 1, n: 'X', c: 'Medication', lc: 10, p: 20, q: 0, s: 0, val: null, my: { units: 0, sales: 0, listed: true }, sg: { units: 0, sales: 0, listed: true } }, o);

// revenue / cost / margin
let r = A.analyseProduct(P({ q: 30, s: 10, my: { units: 5, sales: 90, price: 18, listed: true } }), today);
assert.strictEqual(r.units, 15);
assert.strictEqual(r.revenue, 10 * 20 + 90);
assert.strictEqual(r.cogs, 15 * 10);
assert.strictEqual(r.cover, 2);
assert.strictEqual(r.clinicMargin, 50);

// non-moving, slow, excess are mutually exclusive
assert.ok(A.analyseProduct(P({ q: 5 }), today).alerts.nonmoving);
let slow = A.analyseProduct(P({ q: 5, s: 2 }), today); assert.ok(slow.alerts.slow && !slow.alerts.nonmoving);
let high = A.analyseProduct(P({ q: 100, s: 10 }), today); assert.ok(high.alerts.high && !high.alerts.slow);
assert.strictEqual(high.alerts.high.excessUnits, 70);

// reorder: cover 0.5 mo -> suggest up to 1.5 months of sales
let low = A.analyseProduct(P({ q: 5, s: 10 }), today);
assert.ok(low.alerts.lowstock);
assert.strictEqual(low.alerts.lowstock.orderUnits, 10);
assert.strictEqual(low.alerts.lowstock.orderCost, 100);
assert.ok(!A.analyseProduct(P({ q: 30, s: 10 }), today).alerts.lowstock);

// expiry: expired batch + batch that cannot be sold in time
let ex = A.analyseProduct(P({ q: 20, s: 3, b: [['2026-09-01', 5], ['2026-10-31', 15]] }), today);
assert.ok(ex.alerts.expiry.expired);
assert.strictEqual(ex.alerts.expiry.expiredUnits, 5);
assert.ok(ex.alerts.expiry.atRiskUnits > 0);
assert.strictEqual(ex.alerts.expiry.rm, (5 + ex.alerts.expiry.atRiskUnits) * 10);
assert.ok(!A.analyseProduct(P({ q: 20, s: 30, b: [['2029-01-01', 20]] }), today).alerts.expiry);

// margin rules: vaccines use a lower threshold
assert.ok(A.analyseProduct(P({ q: 1, s: 1, lc: 16, p: 20 }), today).alerts.marginClinic);
assert.ok(!A.analyseProduct(P({ c: 'Vaccine', q: 1, s: 1, lc: 16, p: 20 }), today).alerts.marginClinic);

// data warnings
assert.ok(A.analyseProduct(P({ lc: 0 }), today).warnings.includes('No cost price'));

// summary + ABC integrity
const set = [P({ id: 1, s: 100, q: 10 }), P({ id: 2, s: 10, q: 50 }), P({ id: 3, s: 1, q: 40 }), P({ id: 4, q: 60 })];
const s = A.summarise(set, today);
assert.strictEqual(s.items.length, 4);
assert.strictEqual(s.revenue, 2220);
assert.strictEqual(s.grossProfit, 2220 - 111 * 10);
const abc = s.abc;
assert.strictEqual(abc.A.count + abc.B.count + abc.C.count, 4);
assert.ok(Math.abs(abc.A.revShare + abc.B.revShare + abc.C.revShare - 1) < 1e-9);
assert.ok(Math.abs(abc.A.stockShare + abc.B.stockShare + abc.C.stockShare - 1) < 1e-9);
assert.strictEqual(s.channels.reduce((a, c) => a + c.revenue, 0), s.revenue);
assert.strictEqual(s.categories.reduce((a, c) => a + c.revenue, 0), s.revenue);

// empty month must not crash or produce NaN
const empty = A.summarise([], today);
assert.strictEqual(empty.revenue, 0); assert.strictEqual(empty.gm, 0); assert.strictEqual(empty.coverMonths, null);

// real data agrees with the independent Python calculation (rev 389,832 / GP 152,954 / stock 331,918)
try {
  const d = require('../data/2026-09.json'), real = A.summarise(d.products, d.meta.today);
  assert.strictEqual(Math.round(real.revenue), 389832); assert.strictEqual(Math.round(real.grossProfit), 152954); assert.strictEqual(Math.round(real.stockValue), 331918);
} catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
// weekly trend: per-day comparison, change vs previous period, 4-period average
const wk = A.weeklyTrend([
  { channel: 'shopee_my', channel_label: 'Shopee MY', currency: 'MYR', period_start: '2026-10-12', period_end: '2026-10-18', units: 70, revenue: 700 },
  { channel: 'shopee_my', channel_label: 'Shopee MY', currency: 'MYR', period_start: '2026-10-05', period_end: '2026-10-11', units: 35, revenue: 350 },
  { channel: 'clinic', channel_label: 'Clinic', currency: null, period_start: '2026-10-05', period_end: '2026-10-11', units: 14, revenue: null }
]);
const my = wk.find(c => c.channel === 'shopee_my');
assert.strictEqual(my.periods, 2);
assert.strictEqual(my.series[0].start, '2026-10-05');            // sorted by date
assert.strictEqual(my.last.perDay, 10); assert.strictEqual(my.prev.perDay, 5);
assert.strictEqual(my.changePct, 100);
assert.ok(Math.abs(my.avgPerDay4 - 7.5) < 1e-9);
const cl = wk.find(c => c.channel === 'clinic');
assert.strictEqual(cl.changePct, null); assert.strictEqual(cl.last.revenue, null);   // one period, units only
assert.strictEqual(A.weeklyTrend([]).length, 0);
// a 14-day upload is compared per day, not as a bigger week
const mixed = A.weeklyTrend([
  { channel: 'clinic', channel_label: 'Clinic', period_start: '2026-10-01', period_end: '2026-10-07', units: 70 },
  { channel: 'clinic', channel_label: 'Clinic', period_start: '2026-10-08', period_end: '2026-10-21', units: 70 }]);
assert.strictEqual(mixed[0].changePct, -50);

// Shopee fee assumption: percent of sales, per marketplace, clinic untouched, never below 0 or above 100
const base = A.summarise([P({ s: 10, q: 50, my: { units: 10, sales: 200, listed: true }, sg: { units: 5, sales: 100, listed: true } })], today);
const f0 = A.applyFees(base.channels, {});
assert.strictEqual(f0.totalFees, 0); assert.ok(Math.abs(f0.gpAfterFees - base.grossProfit) < 1e-9);
const f1 = A.applyFees(base.channels, { my: 10, sg: 20 });
assert.strictEqual(f1.channels.find(c => c.name === 'Shopee MY').fee, 20);
assert.strictEqual(f1.channels.find(c => c.name === 'Shopee SG').fee, 20);
assert.strictEqual(f1.channels.find(c => c.name === 'Clinic (est.)').fee, 0);
assert.ok(Math.abs(f1.gpAfterFees - (base.grossProfit - 40)) < 1e-9);
assert.strictEqual(A.applyFees(base.channels, { my: 500 }).channels.find(c => c.name === 'Shopee MY').fee, 200);   // capped at 100%
assert.strictEqual(A.applyFees(base.channels, { my: -5 }).totalFees, 0);


// sortRows: display order for the Ranked actions tables (null = engine order = biggest money first)
{
  const rows = [{ n: 'b', rm: 50 }, { n: 'A', rm: 90 }, { n: 'c', rm: null }, { n: 'd', rm: 90 }];
  const g = { 0: x => x.n, 1: x => x.rm };
  const names = l => l.map(x => x.n).join('');
  assert.strictEqual(A.sortRows(rows, g, null), rows);                                   // no sort -> untouched
  assert.strictEqual(names(A.sortRows(rows, g, { col: 1, dir: 'desc' })), 'Adbc');       // highest first, ties keep list order, empty last
  assert.strictEqual(names(A.sortRows(rows, g, { col: 1, dir: 'asc' })), 'bAdc');        // lowest first, empty still last
  assert.strictEqual(names(A.sortRows(rows, g, { col: 0, dir: 'asc' })), 'Abcd');        // text A-Z, case-insensitive
  assert.strictEqual(names(A.sortRows(rows, g, { col: 0, dir: 'desc' })), 'dcbA');
  assert.strictEqual(A.sortRows(rows, g, { col: 9, dir: 'asc' }), rows);                 // unknown column -> untouched
  assert.strictEqual(names(rows), 'bAcd');                                               // input not mutated
}
console.log('overview engine: all tests passed');
