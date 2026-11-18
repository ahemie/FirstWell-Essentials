// Run: node tests/product_trends_render.test.js  — renders the Product Details trend section with fake data (no database).
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const dummy = () => new Proxy(function(){}, {get:(t,k)=> k==='style'||k==='classList'||k==='dataset' ? dummy() : (k===Symbol.toPrimitive ? ()=>'' : dummy()), apply:()=>dummy(), set:()=>true});
const ctx = {document: {getElementById: dummy, querySelector: dummy, querySelectorAll: ()=>[], addEventListener(){}, createElement: dummy, body: dummy(), documentElement: dummy()},
  window: {}, fetch: async () => { throw Error('offline'); }, console: {log(){}, warn(){}, error(){}}, location: {href:'', hash:''}, localStorage: {getItem(){return null}, setItem(){}},
  setTimeout, clearTimeout, URL, Blob, URLSearchParams, Intl, history:{replaceState(){}}};
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync('assets/js/product.js','utf8') + '\n;this.__t={renderProductTrends,trendFeeFor,trendProfitSeries,monthlyPriceSection,state};', ctx);
const t = ctx.__t;
ctx.FIRSTSTEP_FEES = [
  {marketplace:'MY', effective_from:'2026-01-01', keep_pct:80, voucher_per_unit:0},
  {marketplace:'MY', effective_from:'2026-10-01', keep_pct:78, voucher_per_unit:1.5},
  {marketplace:'SG', effective_from:'2026-01-01', keep_pct:70, voucher_per_unit:0}];
// fee lookup respects the effective date
assert.strictEqual(t.trendFeeFor({key:'my'}, '2026-09').keep, 0.8);
assert.strictEqual(t.trendFeeFor({key:'my'}, '2026-10').keep, 0.78);
assert.strictEqual(t.trendFeeFor({key:'my'}, '2026-10').voucher, 1.5);
assert.strictEqual(t.trendFeeFor({key:'sg'}, '2026-10').keep, 0.7);
assert.strictEqual(t.trendFeeFor({key:'clinic'}, '2026-10').keep, 1);
// profit = price*keep - voucher - cost  (price 106.71, cost 60)
const product = {id: 237, lc: 60};
t.state.monthData = {meta:{fx:3.2}};
const p = t.trendProfitSeries(product, {key:'my'}, [106.71, 106.71, null], ['2026-09','2026-10','2026-10']);
assert(Math.abs(p[0] - (106.71*0.8 - 60)) < 1e-9, p[0]);
assert(Math.abs(p[1] - (106.71*0.78 - 1.5 - 60)) < 1e-9, p[1]);
assert.strictEqual(p[2], null);
// rendered section
ctx.FIRSTSTEP_TRENDS = {meta:{months:['2026-05','2026-06','2026-07']}, products:{'237':{
  '2026-05':{clinic:{units:2,revenue:207},my:{units:305,revenue:30808},sg:{units:3,revenue:18}},
  '2026-06':{clinic:{units:1,revenue:103.5},my:{units:292,revenue:30040},sg:{units:null,revenue:null}},
  '2026-07':{clinic:{units:0,revenue:0},my:{units:274,revenue:28250},sg:{units:4,revenue:24}}}}};
t.state.selectedMonth = '2026-07';
const html = t.renderProductTrends(product);
assert(!/<rect[^>]*fill-opacity="\.28"/.test(html), 'unit bars must be gone');
assert(html.includes('#E8590C') && html.includes('#1F5FBF') && html.includes('#12915A'), 'three line colours');
assert((html.match(/Units sold/g)||[]).length >= 3);
assert(html.includes('Shopee payout') && html.includes('80%') && html.includes('70%'), 'fee note shown for Shopee');
assert(!html.includes('Coming Soon'));
const pricing = t.monthlyPriceSection(product, {costPrice: 60});
assert(!pricing.includes('Coming Soon') && !pricing.includes('Price impact'), 'Coming soon removed from pricing table');
assert(pricing.includes('Gross Margin'));
require("fs").writeFileSync(process.env.OUT||"/dev/null", html);
console.log('PASS: product trends — lines, fee/voucher profit, no Coming soon');
