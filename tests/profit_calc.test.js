// Run: node tests/profit_calc.test.js — the profit calculation table beside the product cards and the Est. profit column.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
for (const file of ['assets/js/product.js', 'assets/js/legacy-dashboard.js']) {
  const dummy = () => new Proxy(function(){}, {get:(t,k)=> k==='style'||k==='classList'||k==='dataset' ? dummy() : (k===Symbol.toPrimitive ? ()=>'' : dummy()), apply:()=>dummy()});
  const ctx = {document: {getElementById: dummy, querySelector: dummy, querySelectorAll: ()=>[], addEventListener(){}, createElement: dummy, body: dummy(), documentElement: dummy()},
    window: {}, fetch: async () => { throw Error('offline'); }, console: {log(){}, warn(){}, error(){}}, location: {href:'', hash:''}, localStorage: {getItem(){return null;}, setItem(){}},
    setTimeout, clearTimeout, URL, Blob, URLSearchParams, Intl, history:{replaceState(){}}};
  ctx.window = ctx; ctx.addEventListener = () => {}; vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(file, 'utf8') + '\n;this.__t={renderSplitCards:typeof renderSplitCards===\"function\"?renderSplitCards:null,setMonthFee:typeof setMonthFee===\"function\"?setMonthFee:null,feePctFor:typeof feePctFor===\"function\"?feePctFor:null,customCalcState,customCalcResult,channelProfit,viewProfit,renderProfitCalc,state,TABLE_COLUMNS};', ctx);
  const t = ctx.__t;
  const item = {product: {s: 2, my: {units: 3, sales: 90}, sg: null}, costPrice: 10, clinicSales: 60, malaysiaSales: 90, singaporeSales: 0};
  const r = t.channelProfit(item);
  assert.strictEqual(r.clinic.profit, 40); assert.strictEqual(r.my.profit, 60); assert.strictEqual(r.sg.profit, 0);
  assert.strictEqual(r.total.profit, 100); assert.strictEqual(r.total.units, 5);
  t.state.view = 'my'; assert.strictEqual(t.viewProfit(item), 60);
  t.state.view = 'all'; assert.strictEqual(t.viewProfit(item), 100);
  assert.strictEqual(t.viewProfit({...item, costPrice: null}), null);
  const html = t.renderProfitCalc(item);
  assert(html.includes('Profit calculation') && html.includes('Total') && html.includes('Shopee MY'));
  assert(t.TABLE_COLUMNS.some(c => c.key === 'profit'));
  // staff fee assumption (MY 10%, SG 5%) is taken off Shopee sales only
  ctx.localStorage.getItem = () => JSON.stringify({my: 10, sg: 5});
  const f = t.channelProfit(item);
  assert.strictEqual(f.my.fee, 9); assert.strictEqual(f.my.profit, 51); assert.strictEqual(f.clinic.profit, 40);
  assert.strictEqual(f.total.profit, 91); assert.strictEqual(f.total.fee, 9);
  t.state.view = 'my'; assert.strictEqual(t.viewProfit(item), 51);
  const h = t.renderProfitCalc(item);
  assert(h.includes('fee 10.0%') && h.includes('Per unit') && h.includes('Kept %'));
  // per unit: MY sells 3 units for 90 => price 30, keeps 90% = 27, cost 10 => 17/unit => 51 total
  assert(h.includes('30.00') && h.includes('27.00') && h.includes('17.00'));
  // custom what-if: (price x percentage) - cost
  item.product.id = 1;
  assert.strictEqual(t.customCalcResult(item), null);
  t.customCalcState[1] = {price: '40', pct: '75', cost: ''};
  const cr = t.customCalcResult(item);
  assert.strictEqual(cr.keep, 30); assert.strictEqual(cr.profit, 20); assert.strictEqual(cr.margin, 50);
  t.customCalcState[1] = {price: '40', pct: '75', cost: '12'}; assert.strictEqual(t.customCalcResult(item).profit, 18);
  assert(t.renderProfitCalc(item).includes('Try your own price'));
  if (file.endsWith('product.js')) {
    // monthly kept % history: a month's own value beats the default (MY default fee 10%)
    const store = {fw_shopee_fee_assumption: JSON.stringify({my: 10, sg: 5})};
    ctx.localStorage.getItem = k => store[k] == null ? null : store[k]; ctx.localStorage.setItem = (k, v) => { store[k] = v; };
    t.setMonthFee('2026-10', 'my', 12);
    assert.strictEqual(t.feePctFor('my', '2026-10').pct, 12); assert.strictEqual(t.feePctFor('my', '2026-10').source, 'month');
    assert.strictEqual(t.feePctFor('my', '2026-09').pct, 10); assert.strictEqual(t.feePctFor('my', '2026-09').source, 'default');
    t.state.selectedMonth = '2026-10'; t.state.view = 'all';
    assert(Math.abs(t.channelProfit(item).my.fee - 10.8) < 1e-9);
    t.setMonthFee('2026-10', 'my', null); assert.strictEqual(t.feePctFor('my', '2026-10').source, 'default');
    // KPI boxes are split by channel and match the Profit calculation (after fees)
    t.state.selectedMonth = null;
    const cards = t.renderSplitCards(item);
    assert(cards.includes('Clinic') && cards.includes('Shopee MY') && cards.includes('Shopee SG') && cards.includes('After Shopee fees'));
    assert(cards.includes('RM 40.00') && cards.includes('RM 51.00'), 'clinic 40 and MY 51 profit shown');
    assert(t.renderProfitCalc(item).includes('Profit calculation'));
  }
  console.log('PASS:', file);
}
