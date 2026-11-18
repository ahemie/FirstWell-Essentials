// Run: node tests/top10_sort.test.js — Top 10 table sorting and full-name chart labels (no database).
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const dummy = () => new Proxy(function(){}, {get:(t,k)=> k===Symbol.toPrimitive ? ()=>'' : dummy(), apply:()=>dummy(), set:()=>true});
for (const file of ['assets/js/product.js', 'assets/js/legacy-dashboard.js']) {
  const listeners = {};
  const ctx = {document: {getElementById: () => dummy(), querySelector: () => null, querySelectorAll: () => [],
    addEventListener(type, fn){ (listeners[type] = listeners[type] || []).push(fn); }, createElement: dummy, body: dummy(), documentElement: dummy()},
    fetch: async () => { throw Error('offline'); }, console: {log(){}, warn(){}, error(){}}, location: {href:'', search:'', hash:''}, URLSearchParams, setTimeout, clearTimeout, URL, Blob, Intl, history:{replaceState(){}}, localStorage:{getItem(){return null},setItem(){}}};
  ctx.window = ctx; ctx.addEventListener = () => {}; vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(file,'utf8') + '\n;this.__t={rankTopProducts,topSortHeader,reportBarRows,state};', ctx);
  const t = ctx.__t;
  const all = [
    {name:'A', units:5, revenue:900}, {name:'B', units:90, revenue:300}, {name:'C', units:0, revenue:0},
    ...Array.from({length: 12}, (_, i) => ({name:'P'+i, units:10+i, revenue:100+i}))];
  const names = r => r.map(p => p.name);
  const rev = t.rankTopProducts(all, {key:'revenue', direction:'desc'});
  assert.strictEqual(rev.length, 10); assert.strictEqual(rev[0].name, 'A');           // highest revenue first
  const units = t.rankTopProducts(all, {key:'units', direction:'desc'});
  assert.strictEqual(units[0].name, 'B');                                              // re-ranks the WHOLE list, not just the first 10
  const low = t.rankTopProducts(all, {key:'units', direction:'asc'});
  assert.strictEqual(low[0].name, 'A'); assert(!names(low).includes('C'));             // lowest first, no-sale products skipped
  assert.strictEqual(t.state.topSort.key, 'revenue');                                  // default order is unchanged
  const head = t.topSortHeader('units', 'Units Sold');
  assert(head.includes('data-action="top-sort"') && head.includes('aria-sort="none"'));
  t.state.topSort = {key:'units', direction:'asc'};
  assert(t.topSortHeader('units', 'Units Sold').includes('aria-sort="ascending"'));
  // clicking a header: new column = highest first, same column = flip
  const click = value => listeners.click.forEach(fn => fn({target:{closest: () => ({getAttribute: a => a === 'data-action' ? 'top-sort' : value})}}));
  t.state.topSort = {key:'revenue', direction:'desc'};
  click('units'); assert.deepStrictEqual(JSON.parse(JSON.stringify(t.state.topSort)), {key:'units', direction:'desc'});
  click('units'); assert.strictEqual(t.state.topSort.direction, 'asc');
  click('units'); assert.strictEqual(t.state.topSort.direction, 'desc');
  // chart keeps the FULL name and uses the stacked layout; other charts are unchanged
  const long = 'QV Dermcare sting-free Ointment 200g with a really long product name';
  const bars = t.reportBarRows([{label:long, value:100}], true, true);
  assert(bars.includes('chart-line-stack') && bars.includes(long) && !bars.includes('…'));
  assert(!t.reportBarRows([{label:'Clinic', value:1}]).includes('chart-line-stack'));
  console.log('PASS:', file);
}
