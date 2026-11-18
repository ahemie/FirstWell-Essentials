// Run: node tests/nav.test.js — checks the 3-section navigation matches the real pages. No browser needed.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const root = path.join(__dirname, '..');
const nav = require('../assets/js/nav.js');
const appPy = fs.readFileSync(path.join(root, 'app.py'), 'utf8');

assert.deepStrictEqual(nav.SECTIONS.map((s) => s.id), ['dashboard', 'scraping', 'stock'], 'three sections, in order');
const seen = new Set();
for (const s of nav.SECTIONS) {
  assert.ok(s.pages.length >= 1, s.id + ' has pages');
  for (const p of s.pages) {
    assert.ok(!seen.has(p.page), 'duplicate page id ' + p.page); seen.add(p.page);
    const file = p.href.replace(/^\//, '');
    assert.ok(fs.existsSync(path.join(root, 'pages', file)), 'pages/' + file + ' exists');
    assert.ok(appPy.includes("'" + file + "'"), file + ' is whitelisted in app.py');
    const html = fs.readFileSync(path.join(root, 'pages', file), 'utf8');
    assert.ok(html.includes('data-page="' + p.page + '"'), file + ' has data-page="' + p.page + '"');
    assert.ok(html.includes('/assets/js/nav.js'), file + ' loads nav.js');
    assert.strictEqual(nav.sectionOf(p.page).id, s.id);
  }
}
assert.strictEqual(nav.sectionOf('unknown').id, 'dashboard', 'unknown pages fall back to Dashboard');
assert.ok(nav.pageLinks(nav.SECTIONS[0], 'bi').includes('aria-current="page"'));
assert.ok(!nav.sectionBar(nav.SECTIONS[1]).includes('<script'), 'labels are escaped');
console.log('nav tests passed');
