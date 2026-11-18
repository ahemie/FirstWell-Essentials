// Run: node tests/rules_panel.test.js — "How each card is calculated": 3 panels like Data uploads, collapsed, stays open once opened.
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const dummy = () => new Proxy(function(){}, {get:(t,k)=> k===Symbol.toPrimitive ? ()=>'' : dummy(), apply:()=>dummy(), set:()=>true});
for (const file of ['assets/js/product.js', 'assets/js/legacy-dashboard.js']) {
  const listeners = {};
  const ctx = {document: {getElementById: () => dummy(), querySelector: () => null, querySelectorAll: () => [],
    addEventListener(type, fn){ (listeners[type] = listeners[type] || []).push(fn); }, createElement: dummy, body: dummy(), documentElement: dummy()},
    fetch: async () => { throw Error('offline'); }, console: {log(){}, warn(){}, error(){}}, location: {href:'', search:'', hash:''}, URLSearchParams, setTimeout, clearTimeout, URL, Blob, Intl, history:{replaceState(){}}, localStorage:{getItem(){return null},setItem(){}}};
  ctx.window = ctx; ctx.addEventListener = () => {}; vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(file,'utf8') + '\n;this.__t={renderRules,state,CARD_ORDER};', ctx);
  const t = ctx.__t, mi = {fx: 3.18};
  const closed = t.renderRules(mi);
  assert(closed.includes('<details id="rules-details"') && !/<details[^>]* open/.test(closed));   // collapsed by default
  assert.strictEqual((closed.match(/class="up rule-row"/g) || []).length, t.CARD_ORDER.length);     // one row per card
  assert.strictEqual((closed.match(/<h3 /g) || []).length, 3);                                        // three panels, like Data uploads
  assert(closed.includes('Low margin · clinic') && closed.includes('SGD 1 = RM 3.18'));
  listeners.toggle.forEach(fn => fn({target:{id:'rules-details', open:true}}));                      // user opens it
  assert(/<details[^>]* open/.test(t.renderRules(mi)));                                              // stays open after a redraw
  listeners.toggle.forEach(fn => fn({target:{id:'rules-details', open:false}}));
  assert(!/<details[^>]* open/.test(t.renderRules(mi)));
  console.log('PASS:', file);
}
