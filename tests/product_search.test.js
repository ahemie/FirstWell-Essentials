// Run: node tests/product_search.test.js — Product Details search (no database).
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const dummy = () => new Proxy(function(){}, {get:(t,k)=> k===Symbol.toPrimitive ? ()=>'' : dummy(), apply:()=>dummy(), set:()=>true});
const listeners = {}; const els = {};
const ctx = {document: {getElementById: id => els[id] || dummy(), querySelector: () => null,
  querySelectorAll: () => [], addEventListener(type, fn){ (listeners[type] = listeners[type] || []).push(fn); }, createElement: dummy, body: dummy(), documentElement: dummy()},
  fetch: async () => { throw Error('offline'); }, console: {log(){}, warn(){}, error(){}}, location: {href:'', search:'?item=0', hash:''}, URLSearchParams, setTimeout, clearTimeout, URL, Blob, Intl, history:{replaceState(){}}, localStorage:{getItem(){return null},setItem(){}}};
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync('assets/js/product.js','utf8') + '\n;this.__t={productMatchesQuery,productSearchResults,productResultsView,highlightWords,renderProductPicker,state,productSearch};', ctx);
const t = ctx.__t;
t.state.analysedProducts = [
  {product:{n:'MUSTELA Hydra Bébé facial cream 40ml', id:'237', c:'Skincare', q:12}},
  {product:{n:'Influenza vaccine (Influvac QIV) 0.5ml', id:'1001', c:'Vaccine', q:3}},
  {product:{n:'Aerochamber Plus Infant (ORANGE)', id:'507', c:'Devices', q:0}},
  {product:{n:'Mustela Gel Lavant 500ml', id:'88', c:'Skincare', q:7}}];
const n = q => t.productSearchResults(q).length;
assert.strictEqual(n(''), 4);
assert.strictEqual(n('mustela'), 2);
assert.strictEqual(n('MUSTELA cream'), 1);   // all words, any case
assert.strictEqual(n('cream mustela'), 1);   // any order
assert.strictEqual(n('bebe'), 1);            // accent-insensitive
assert.strictEqual(n('507'), 1);             // Avixo ID
assert.strictEqual(n('influvac'), 1);
assert.strictEqual(n('zzz'), 0);

// result rows keep the ORIGINAL index, show ID/category/stock and highlight the typed words
const v = t.productResultsView('gel', 0, 0);
assert(v.html.includes('data-value="3"') && v.activeIndex === 3);
assert(v.html.includes('<mark>Gel</mark>') && v.html.includes('ID 88') && v.html.includes('Skincare') && v.html.includes('Stock 7'));
assert(t.productResultsView('', 0, 0).html.includes('viewing'));       // current product is tagged
assert(t.highlightWords('A & B <b>', 'b').includes('&amp;') && !t.highlightWords('A <b>', 'b').includes('<b>'));  // escaped
assert(t.productResultsView('zzz', 0, 0).message.includes('No product matches'));
assert(t.productResultsView('', 0, 0).message.includes('4 products'));

// long lists are capped but still tell the user how many matched
t.state.analysedProducts = Array.from({length: 120}, (_, i) => ({product:{n:'Item ' + i, id:String(i)}}));
const big = t.productResultsView('', 0, 0);
assert.strictEqual(big.shown, 40); assert(big.message.includes('120 products') && big.message.includes('first 40'));
t.state.analysedProducts = [
  {product:{n:'MUSTELA Hydra Bébé facial cream 40ml', id:'237'}}, {product:{n:'Influenza vaccine', id:'1001'}},
  {product:{n:'Aerochamber Plus Infant (ORANGE)', id:'507'}}, {product:{n:'Mustela Gel Lavant 500ml', id:'88'}}];

// picker markup, typing, arrows, Enter, Escape
const html = t.renderProductPicker();
assert(html.includes('id="product-search"') && html.includes('id="product-results"') && html.includes('role="listbox"'));
els['product-results'] = {innerHTML:''}; els['product-search-count'] = {textContent:''};
const input = {id:'product-search', value:'mustela'};
listeners.input.forEach(fn => fn({target:input}));
assert(els['product-results'].innerHTML.split('<li').length - 1 === 2 && els['product-search-count'].textContent.includes('2 products match'));
const key = k => { let p = false; listeners.keydown.forEach(fn => fn({target:input, key:k, preventDefault(){p = true}})); return p; };
assert(key('ArrowDown') && t.productSearch.active === 1);
assert(key('ArrowDown') && t.productSearch.active === 1);            // stops at last row
assert(key('ArrowUp') && t.productSearch.active === 0);
key('ArrowDown'); assert(key('Enter') && ctx.location.href === 'product.html?item=3', ctx.location.href);   // 2nd Mustela = original index 3
key('Escape'); assert.strictEqual(input.value, ''); assert(els['product-search-count'].textContent.includes('4 products'));
listeners.input.forEach(fn => fn({target:{id:'product-search', value:'zzz'}}));
assert(els['product-search-count'].textContent.includes('No product matches'));
console.log('PASS: product search (words, accents, ID, highlight, caps, arrows, Enter, Escape)');
