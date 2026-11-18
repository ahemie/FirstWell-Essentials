'use strict';
// Two pages: Scrape (our products | keyword | Shopee site) and Results (every scrape and its competitor prices).
let csrf = '', tab = 'scrape', catalog = [], runs = [], selectedRun = null, selectedRunId = null;
let pick = {name: '', item_id: '', key: '', price: ''}, market = 'MY', busy = false, filterText = '';
const $ = selector => document.querySelector(selector);
const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const SITES = {
    MY: {name: 'Shopee Malaysia', host: 'shopee.com.my', symbol: 'RM', note: 'Prices in Malaysian ringgit (RM)'},
    SG: {name: 'Shopee Singapore', host: 'shopee.sg', symbol: 'S$', note: 'Prices in Singapore dollars (S$)'},
};
const fmt = (value, site = 'MY') => value == null || value === '' ? '—' : (SITES[site] || SITES.MY).symbol + ' ' + Number(value).toFixed(2);
const signed = (value, site) => value == null ? '—' : (value > 0 ? '+' : value < 0 ? '−' : '') + fmt(Math.abs(value), site);
const rowKey = r => `${r.item_id}:${r.variation_id || ''}`;
const ourItem = id => catalog.find(r => String(r.item_id) === String(id));
// Shopee's own address style: https://shopee.com.my/<product-name>-i.<shop id>.<item id>
const ourLink = r => {
    if (!r || !r.shop_id || !r.item_id) return '';
    const slug = cleanTitle(r.title).replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'product';
    return `https://shopee.com.my/${slug}-i.${encodeURIComponent(r.shop_id)}.${encodeURIComponent(r.item_id)}`;
};
const usd = v => v == null || !Number.isFinite(Number(v)) ? '—' : '$' + Number(v).toFixed(Number(v) > 0 && Number(v) < 0.1 ? 3 : 2);
const when = v => { const d = new Date(v); return isNaN(d) ? safe(v) : safe(d.toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'})); };
// Clearance stock is near-expiry stock sold at a discount: the title starts with a tag such as "(CLEARANCE EXP:10/25)".
const tagOf = t => { const m = String(t || '').match(/^\s*[\[(]([^\])]*(?:EXP|CLEARANCE)[^\])]*)[\])]/i) || String(t || '').match(/\bEXP[:.\s]*([0-9]{1,2}\s*[\/.-]\s*[0-9]{2,4})/i); return m ? m[1] : ''; };
const infoOf = t => { const tag = tagOf(t), exp = (tag.match(/EXP[:.\s]*([0-9]{1,2}\s*[\/.-]\s*[0-9]{2,4})/i) || tag.match(/([0-9]{1,2}\s*[\/.-]\s*[0-9]{2,4})/) || [])[1]; return {clearance: /clearance/i.test(String(t)), exp: exp ? exp.replace(/\s+/g, '') : ''}; };
const cleanTitle = t => {
    // Drop leading tags such as "(CLEARANCE EXP:10/25)" or "[EXP 04/27]", emoji and expiry notes; keep the product name.
    const parts = String(t || '').replace(/^\s*[\[(][^\])]*(?:EXP|CLEARANCE)[^\])]*[\])]\s*/i, '').replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '').split('|').map(x => x.replace(/\bEXP[:.\s].*$/i, '').replace(/\s+/g, ' ').trim()).filter(Boolean);
    let name = parts[0] || '';
    if (parts.length > 1 && name.split(' ').length < 2) name = parts[1].toLowerCase().startsWith(name.toLowerCase()) ? parts[1] : name + ' ' + parts[1];
    return name;
};
const ratingCell = r => r.rating == null && r.rating_count == null ? '<span class="muted">—</span>' :
    `<span class="num">${r.rating == null ? '' : '★ ' + Number(r.rating).toFixed(1)}</span>${r.rating_count == null ? '' : `<span class="muted small block">${Number(r.rating_count).toLocaleString()} ratings</span>`}`;
const soldCell = r => r.sold_count == null ? '<span class="muted">—</span>' : `<span class="num">${Number(r.sold_count).toLocaleString()}</span><span class="muted small block">sold</span>`;

async function api(url, options = {}) {
    const headers = {'X-CSRF-Token': csrf, ...options.headers};
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    const response = await fetch(url, {...options, headers});
    let data = {};
    try { data = await response.json(); } catch (_) { throw Error('Unexpected response from the server'); }
    if (!response.ok) { const error = Error(data.error || `HTTP ${response.status}`); error.data = data; throw error; }
    return data;
}
function inform(message, type = 'info') {
    const region = $('#message'); region.textContent = message; region.className = 'message ' + type; region.hidden = false;
    window.scrollTo({top: 0, behavior: 'smooth'});
}
function clearMessage() { $('#message').hidden = true; }
// The page security policy forbids inline style attributes, so widths are set through the DOM.
function applyWidths(root) { root.querySelectorAll('[data-w]').forEach(el => { el.style.width = Math.max(0, Math.min(100, Number(el.dataset.w) || 0)) + '%'; }); }
function setView(html) { const v = $('#view'); v.innerHTML = html; applyWidths(v); return v; }

async function load() {
    const current = await api('/api/auth/session');
    csrf = current.csrf_token;
    const [list, history] = await Promise.all([api('/api/scrap/catalog/list?source=Probiotickids'), api('/api/scrap/runs').catch(error => ({runs: [], setup: error.message}))]);
    catalog = list.products;
    runs = history.runs;
    setupProblem = history.setup || '';
    render();
}
let setupProblem = '';
function changeTab(next) { tab = next; clearMessage(); render(); window.scrollTo(0, 0); }
function render() {
    document.querySelectorAll('.ps-tabs button').forEach(b => {
        const on = b.dataset.tab === tab;
        b.classList.toggle('selected', on);
        if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    const c = $('#runCount'); c.hidden = runs.length === 0; c.textContent = runs.length;
    if (tab === 'scrape') scrapePage(); else if (tab === 'links') linksPage(); else resultsPage();
}

/* ---------- Scrape page ---------- */
function scrapePage() {
    setView(`<div class="head-row"><div><h2>Scrape competitor prices</h2>
      <p>Pick one of our products or type your own keyword, choose the Shopee site, then press Scrape. The prices are worked out for you on the Results page.</p></div>
      </div>
    <section id="credit" class="card credit-card" aria-live="polite"><div class="muted small">Checking Apify credit...</div></section>
    ${setupProblem ? `<p class="alert">${safe(setupProblem)}</p>` : ''}
    <div class="scrape-grid">
      <section class="card col-products" aria-labelledby="h1"><h3 id="h1"><span class="step-n">1</span>Our products</h3>
        <p class="sub">Probiotickids list. Each size or flavour is its own product. Click one to fill the keyword.</p>
        <input id="productFilter" type="search" autocomplete="off" placeholder="Search our products" aria-label="Search our products" value="${safe(filterText)}">
        <p id="productCount" class="muted small"></p>
        <div id="productList" class="product-list" role="listbox" aria-label="Our products"></div></section>
      <section class="card col-keyword" aria-labelledby="h2"><h3 id="h2"><span class="step-n">2</span>Keyword</h3>
        <p class="sub">What to search for on Shopee. Edit it any time.</p>
        <label>Keyword<input id="keyword" autocomplete="off" maxlength="120" placeholder="e.g. orac kids immune booster 5g x 6" value="${safe(pick.name)}"></label>
        <label>Our price, optional (for the comparison)<input id="ourPrice" inputmode="decimal" autocomplete="off" placeholder="e.g. 36.60" value="${safe(pick.price)}"></label>
        <p id="chosen" class="small muted"></p></section>
      <section class="card col-site" aria-labelledby="h3x"><h3 id="h3x"><span class="step-n">3</span>Shopee site</h3>
        <p class="sub">Which Shopee server to search.</p>
        <div class="site-options" role="radiogroup" aria-label="Shopee site">
          ${Object.entries(SITES).map(([key, s]) => `<label class="site ${market === key ? 'on' : ''}"><input type="radio" name="market" value="${key}" ${market === key ? 'checked' : ''}>
            <span><strong>${s.name}</strong><span class="muted small block">${s.host} · ${s.note}</span></span></label>`).join('')}
        </div>
        <button type="button" id="go" class="primary wide big">Scrape now</button>
        <div id="progress" class="progress" hidden><span class="spinner" aria-hidden="true"></span><span id="progressText">Searching Shopee… this takes about 10 to 30 seconds.</span></div>
        <p class="muted small">Each scrape uses a little Apify credit (capped per scrape). Repeating the same keyword within 5 minutes shows the saved result instead.</p></section>
    </div>`);
    drawProducts();
    $('#productFilter').oninput = event => { filterText = event.target.value; drawProducts(); };
    $('#keyword').oninput = () => { pick = {name: $('#keyword').value, item_id: '', key: '', price: $('#ourPrice').value}; $('#chosen').textContent = ''; };
    $('#ourPrice').oninput = () => { pick.price = $('#ourPrice').value; };
    document.querySelectorAll('input[name=market]').forEach(r => r.onchange = () => {
        market = r.value; document.querySelectorAll('.site').forEach(l => l.classList.toggle('on', l.querySelector('input').value === market));
    });
    $('#keyword').onkeydown = event => { if (event.key === 'Enter') { event.preventDefault(); scrapeNow(); } };
    $('#go').onclick = scrapeNow;
    loadCredit();
}
// The exact Shopee address of our product: taken from the scrape itself when our own listing was found in it,
// otherwise built from the shop and item IDs.
function ourUrl(run, mine) {
    const hit = selectedRun && selectedRun.run && selectedRun.run.id === run.id
        ? (selectedRun.results || []).find(r => r.is_own && mine && String(r.item_id) === String(mine.item_id) && /^https:\/\/([a-z0-9-]+\.)?shopee\.[a-z.]+\//i.test(r.url || '')) : null;
    return hit ? hit.url : ourLink(mine);
}
// Our product behind a scrape: the one that was picked, or (for a typed keyword) the one that matches the keyword and our price.
function ourFor(run) {
    const near = (a, b) => a != null && b != null && b !== '' && Math.abs(Number(a) - Number(b)) < 0.005;
    const name = r => cleanTitle(r.title).toLowerCase();
    if (run.product_item_id) {
        const same = catalog.filter(r => String(r.item_id) === String(run.product_item_id));
        return same.find(r => name(r) === String(run.product_name || '').toLowerCase()) || same.find(r => near(r.price, run.our_price)) || same[0] || null;
    }
    const words = t => new Set(String(t).toLowerCase().replace(/[^a-z0-9+]+/g, ' ').split(' ').filter(w => w.length > 1));
    const want = words(run.keyword); if (!want.size) return null;
    let best = null, top = 0;
    for (const r of catalog) {
        if (run.our_price != null && r.price != null && !near(r.price, run.our_price)) continue;
        const have = words(cleanTitle(r.title)), hit = [...want].filter(w => have.has(w)).length, score = hit / (want.size + have.size - hit);
        if (score > top) { top = score; best = r; }
    }
    return top >= 0.6 ? best : null;
}
function ourCardNote(run) {
    const mine = ourFor(run), link = ourUrl(run, mine), name = run.product_name || (mine ? cleanTitle(mine.title) : '');
    if (!name) return 'Typed keyword';
    return link ? `<a href="${safe(link)}" target="_blank" rel="noopener noreferrer">${safe(name)}</a> <span class="ext" aria-hidden="true">↗</span>` : safe(name);
}
function ourRowHtml(run) {
    const mine = ourFor(run), link = ourUrl(run, mine);
    if (!mine) return '';
    const name = run.product_name || cleanTitle(mine.title);
    return `<tr class="ours our-pinned"><td><span class="pill owned">Ours</span></td>
        <td>${link ? `<a href="${safe(link)}" target="_blank" rel="noopener noreferrer">${safe(name)}</a>` : safe(name)}${prodTags(mine.title)}</td>
        <td><span class="pill owned">Our shop</span><span class="muted small block">${link ? 'Our Shopee listing' : ''}</span></td>
        <td class="num"><span>${run.our_price == null ? '—' : fmt(run.our_price, run.market)}</span></td><td class="muted">—</td><td class="muted">—</td></tr>`;
}
function refHtml(run) {
    const mine = ourFor(run), link = ourUrl(run, mine);
    const kw = `<span class="ref-label">Keyword searched on Shopee</span><span class="ref-kw">${safe(run.keyword)}</span>`;
    if (!mine) return `<div class="ref-box"><div>${kw}<span class="muted small">Typed keyword. No matching product of ours was found in the list.</span></div></div>`;
    return `<div class="ref-box"><div><span class="ref-label">Our product (for comparing)</span><strong>${safe(run.product_name || cleanTitle(mine.title))}</strong>${prodTags(mine.title)}${kw}</div>
      <div class="ref-side">${run.our_price != null ? `<span class="num">RM ${Number(run.our_price).toFixed(2)}</span>` : ''}${link ? `<a class="btn-link" href="${safe(link)}" target="_blank" rel="noopener noreferrer">Open our Shopee listing</a>` : ''}</div></div>
      <p class="muted small">Scraped listings can include other products. Open a listing and compare it with ours, then untick any that are not the same product.</p>`;
}
function prodTags(title) {
    const i = infoOf(title);
    return (i.clearance || i.exp) ? `<span class="tags">${i.clearance ? '<span class="tag clr" title="Clearance: near-expiry stock sold at a discount">Clearance</span>' : ''}${i.exp ? `<span class="tag exp">EXP ${safe(i.exp)}</span>` : ''}</span>` : '';
}
function drawProducts() {
    const q = filterText.trim().toLowerCase(), words = q.split(/\s+/).filter(Boolean);
    const rows = catalog.filter(r => { const t = cleanTitle(r.title).toLowerCase(); return words.every(w => t.includes(w)); });
    $('#productCount').textContent = rows.length === catalog.length ? `${catalog.length} products` : `${rows.length} of ${catalog.length} products`;
    const shown = rows.slice(0, 300);
    $('#productList').innerHTML = shown.length ? shown.map((r, i) => `<div class="prodrow"><button type="button" class="prod ${pick.key === rowKey(r) ? 'on' : ''}" role="option" aria-selected="${pick.key === rowKey(r)}" data-i="${i}">
        <span class="prod-main"><span class="prod-name">${safe(cleanTitle(r.title))}</span>${prodTags(r.title)}</span><span class="prod-price num">${r.price == null ? '<span class="muted">No price</span>' : 'RM ' + Number(r.price).toFixed(2)}</span></button><a class="prod-link" href="${safe(ourLink(r))}" target="_blank" rel="noopener noreferrer" title="Open this product on Shopee">Shopee ↗</a></div>`).join('') +
        (rows.length > shown.length ? `<p class="muted small pad">Showing the first ${shown.length}. Type more letters to narrow the list.</p>` : '')
        : '<div class="empty">No product matches. You can still type any keyword in column 2.</div>';
    document.querySelectorAll('#productList .prod').forEach(b => b.onclick = () => {
        const r = shown[Number(b.dataset.i)], name = cleanTitle(r.title);
        pick = {name, item_id: r.item_id, key: rowKey(r), price: r.price == null ? '' : Number(r.price).toFixed(2)};
        $('#keyword').value = name; $('#ourPrice').value = pick.price;
        $('#chosen').innerHTML = (r.price == null ? 'Filled from our product list. No price saved for this item.' : `Filled from our product list. Our price RM ${Number(r.price).toFixed(2)} is the lowest variation price in the Excel export.`) + ` <a href="${safe(ourLink(r))}" target="_blank" rel="noopener noreferrer">Open our Shopee listing</a> to compare.`;
        drawProducts(); $('#keyword').focus();
    });
}
async function loadCredit() {
    const slot = $('#credit'); if (!slot) return;
    try {
        const u = await api('/api/scrap/apify/usage');
        if (!u.configured) { slot.innerHTML = '<div class="credit-top"><h3>Apify credit</h3></div><p class="muted small">Apify is not connected. Add APIFY_TOKEN on the server to see the credit left.</p>'; return; }
        if (!u.available) { slot.innerHTML = '<div class="credit-top"><h3>Apify credit</h3><button type="button" class="ghost" id="creditRefresh">Refresh</button></div><p class="muted small">Credit could not be read just now. Scraping still works.</p>'; $('#creditRefresh').onclick = loadCredit; return; }
        const limit = Number(u.limit_usd) || 0, left = Number(u.remaining_usd) || 0, used = Number(u.used_usd) || 0, cap = Number(u.cap_usd) || 0;
        const pct = limit > 0 ? Math.max(0, Math.min(100, left / limit * 100)) : 0, low = left < cap * 4;
        slot.innerHTML = `<div class="credit-top"><h3>Apify credit left</h3><button type="button" class="ghost" id="creditRefresh">Refresh</button></div>
          <div class="credit-row"><div class="credit-left num">${usd(left)}<span>left this month</span></div>
          <div><div class="credit-meter" role="img" aria-label="${pct.toFixed(0)} percent of the monthly credit left"><div class="credit-fill ${low ? 'low' : ''}" data-w="${pct.toFixed(1)}"></div></div>
          <div class="credit-meta muted small"><span>Used ${usd(used)} of ${usd(limit)}</span>${u.cycle_ends ? `<span>Resets ${safe(String(u.cycle_ends).slice(0, 10))}</span>` : ''}<span>Each scrape costs at most ${usd(cap)}</span></div></div></div>
          ${left < cap ? '<p class="alert">Credit is lower than one scrape. A scrape may be refused until the credit resets or is topped up.</p>' : low ? '<p class="muted small credit-warn">Credit is getting low.</p>' : ''}`;
        applyWidths(slot); $('#creditRefresh').onclick = loadCredit;
    } catch (_) { slot.innerHTML = '<div class="credit-top"><h3>Apify credit</h3></div><p class="muted small">Credit could not be read just now.</p>'; }
}
async function scrapeNow() {
    if (busy) return;
    const keyword = $('#keyword').value.trim();
    if (keyword.length < 2) { inform('Type a keyword first, or click one of our products.', 'error'); $('#keyword').focus(); return; }
    busy = true; clearMessage();
    $('#go').disabled = true; $('#progress').hidden = false;
    try {
        const body = {keyword, market, our_price: $('#ourPrice').value.trim(), product_name: pick.item_id ? pick.name : '', product_item_id: pick.item_id};
        const data = await api('/api/scrap/scrape-keyword', {method: 'POST', body: JSON.stringify(body)});
        runs = [data.run, ...runs.filter(r => r.id !== data.run.id)];
        selectedRunId = data.run.id; selectedRun = {run: data.run, results: data.results};
        busy = false; changeTab('results');
        inform(data.run.message, 'success');
    } catch (error) {
        busy = false;
        if (error.data && error.data.run_id) {   // same keyword scraped a moment ago: open that result
            selectedRunId = error.data.run_id; selectedRun = null; changeTab('results'); inform(error.message, 'info');
        } else if ($('#go')) { $('#go').disabled = false; $('#progress').hidden = true; inform(error.message, 'error'); }
    }
}

/* ---------- Results page ---------- */
function runSummaryRow(r) {
    const site = r.market, gap = r.our_price != null && r.lowest != null ? Number(r.our_price) - Number(r.lowest) : null;
    return `<tr class="run-row ${r.id === selectedRunId ? 'selected' : ''}" data-run="${r.id}" tabindex="0" role="button" aria-label="Open results for ${safe(r.keyword)}">
      <td>${when(r.started_at)}</td><td><strong>${safe(r.keyword)}</strong></td><td><span class="pill neutral">${SITES[site] ? site : safe(site)}</span></td>
      <td>${r.status === 'COMPLETED' ? '' : `<span class="pill ${safe(r.status)}">${safe(r.status)}</span> `}<span class="num">${r.included_count ?? 0}</span></td>
      <td class="num">${fmt(r.lowest, site)}</td><td class="num">${fmt(r.average, site)}</td><td class="num">${fmt(r.highest, site)}</td>
      <td class="num">${fmt(r.our_price, site)}</td><td class="num ${gap > 0 ? 'bad' : gap < 0 ? 'good' : ''}">${signed(gap, site)}</td></tr>`;
}
async function resultsPage() {
    setView(`<div class="head-row"><div><h2>Results</h2><p>Every scrape, with the competitor prices worked out. Click a row to see its listings.</p></div>
      <button type="button" class="primary" id="newScrape">New scrape</button></div>
    ${setupProblem ? `<p class="alert">${safe(setupProblem)}</p>` : ''}
    <section class="card"><h3>All scrapes</h3>
      ${runs.length ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Keyword</th><th>Site</th><th>Counted</th><th class="num">Lowest</th><th class="num">Average</th><th class="num">Highest</th><th class="num">Our price</th><th class="num">Gap to lowest</th></tr></thead>
        <tbody id="runRows">${runs.map(runSummaryRow).join('')}</tbody></table></div>` : '<div class="empty">No scrapes yet. Go to Scrape, pick a product and press Scrape now.</div>'}</section>
    <div id="detail"></div>`);
    $('#newScrape').onclick = () => changeTab('scrape');
    document.querySelectorAll('.run-row').forEach(row => {
        const open = () => openRun(Number(row.dataset.run));
        row.onclick = open; row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
    });
    if (!selectedRunId && runs.length) selectedRunId = runs[0].id;
    if (selectedRunId) openRun(selectedRunId, false);
}
async function openRun(id, scroll = true) {
    selectedRunId = id;
    document.querySelectorAll('.run-row').forEach(r => r.classList.toggle('selected', Number(r.dataset.run) === id));
    const slot = $('#detail'); if (!slot) return;
    try {
        if (!selectedRun || selectedRun.run.id !== id) { slot.innerHTML = '<p class="muted pad">Loading…</p>'; selectedRun = await api('/api/scrap/runs/' + id); }
        if (tab !== 'results' || selectedRunId !== id) return;
        drawRun();
        if (scroll) $('#detail').scrollIntoView({behavior: 'smooth', block: 'start'});
    } catch (error) { if ($('#detail')) $('#detail').innerHTML = `<p class="alert">${safe(error.message)}</p>`; }
}
function liveStats(results) {
    const p = results.filter(r => r.included && !r.is_own && Number(r.price) > 0).map(r => Number(r.price)).sort((a, b) => a - b);
    if (!p.length) return {count: 0};
    const mid = p.length % 2 ? p[(p.length - 1) / 2] : (p[p.length / 2 - 1] + p[p.length / 2]) / 2;
    return {count: p.length, lowest: p[0], highest: p[p.length - 1], average: p.reduce((a, b) => a + b, 0) / p.length, median: mid};
}
// Suggested selling price, worked out from the competitor prices that are ticked. No outside service is used.
function suggestPrices(results) {
    const all = results.filter(r => r.included && !r.is_own && Number(r.price) > 0).map(r => Number(r.price)).sort((a, b) => a - b);
    if (all.length < 3) return null;
    const med = a => a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2;
    const m = med(all), kept = all.filter(p => p >= m * 0.5 && p <= m * 2);   // far-off prices are usually bundles or a different pack
    if (kept.length < 3) return null;
    const q = f => { const x = (kept.length - 1) * f, i = Math.floor(x); return kept[i] + (kept[Math.min(i + 1, kept.length - 1)] - kept[i]) * (x - i); };
    const down = v => Math.floor(v * 10 + 1e-9) / 10, near = v => Math.round(v * 10) / 10;
    return {used: kept.length, skipped: all.length - kept.length, lowest: kept[0],
        aggressive: Math.max(0.1, down(kept[0] * 0.99)), balanced: near(q(0.25)), premium: near(med(kept))};
}
function suggestHtml(run, results) {
    if (run.status === 'FAILED') return '';
    const site = run.market, g = suggestPrices(results), ours = run.our_price == null ? null : Number(run.our_price);
    if (!g) return '<section class="suggest"><h4>Suggested selling price</h4><p class="muted small">Needs at least 3 counted competitor prices. Tick the listings that are the same product.</p></section>';
    const card = (key, name, price, why, main) => `<div class="sg ${main ? 'sg-main' : ''}"><span class="sg-name">${name}${main ? '<span class="pill owned">Recommended</span>' : ''}</span><span class="sg-price num">${fmt(price, site)}</span><span class="muted small">${why}</span></div>`;
    let move = '';
    if (ours != null) {
        const d = ours - g.balanced, pct = ours ? Math.abs(d) / ours * 100 : 0;
        move = Math.abs(d) < 0.05 ? 'Our price is already at the recommended level.'
            : d > 0 ? `Our price is ${fmt(ours, site)}. Lowering it by ${fmt(d, site)} (${pct.toFixed(0)}%) reaches the recommended price.`
            : `Our price is ${fmt(ours, site)}, already ${fmt(-d, site)} (${pct.toFixed(0)}%) below the recommended price. There may be room to raise it.`;
    }
    return `<section class="suggest"><h4>Suggested selling price</h4>
      <div class="sg-row">${card('a', 'Beat the lowest', g.aggressive, 'About 1% under the cheapest competitor. Wins on price, lowest margin.', false)}${card('b', 'Competitive', g.balanced, 'In the cheaper quarter of the market. Good balance of sales and margin.', true)}${card('c', 'Market middle', g.premium, 'The median competitor price. Best margin, slower to win buyers.', false)}</div>
      ${move ? `<p class="small">${move}</p>` : ''}
      <p class="muted small">Worked out from ${g.used} counted competitor prices${g.skipped ? ` (${g.skipped} far-off price${g.skipped > 1 ? 's' : ''} left out as probably a different pack)` : ''}. It does not know our cost, so check the margin before changing the price. Untick wrong listings and it updates.</p></section>`;
}
function statsHtml() {
    const {run, results} = selectedRun, site = run.market, s = liveStats(results), ours = run.our_price == null ? null : Number(run.our_price);
    const gapLow = ours != null && s.count ? ours - s.lowest : null, gapAvg = ours != null && s.count ? ours - s.average : null;
    let verdict = '';
    if (run.status === 'FAILED') verdict = `<p class="alert">${safe(run.message)}</p>`;
    else if (!s.count) verdict = '<p class="callout-plain">No competitor listing is counted yet. Tick the listings below that are the same product.</p>';
    else if (ours == null) verdict = '<p class="callout-plain">Add our price on the Scrape page to see how we compare.</p>';
    else if (Math.abs(gapLow) < 0.005) verdict = '<p class="callout-plain good-box">Our price matches the lowest competitor.</p>';
    else if (gapLow > 0) verdict = `<p class="callout-plain risk-box">We cost <strong>${fmt(gapLow, site)}</strong> more than the lowest competitor${gapAvg > 0 ? ' and above the average.' : ', but below the average.'}</p>`;
    else verdict = `<p class="callout-plain good-box">We cost <strong>${fmt(-gapLow, site)}</strong> less than the lowest competitor.</p>`;
    return `<div class="stats">
        <div class="stat"><div class="label">Competitors counted</div><div class="num">${s.count}</div><div class="note">of ${results.length} listings found</div></div>
        <div class="stat"><div class="label">Lowest</div><div class="num">${fmt(s.lowest, site)}</div><div class="note">${gapLow == null ? '&nbsp;' : 'Our gap ' + signed(gapLow, site)}</div></div>
        <div class="stat"><div class="label">Average</div><div class="num">${fmt(s.average, site)}</div><div class="note">${gapAvg == null ? '&nbsp;' : 'Our gap ' + signed(gapAvg, site)}</div></div>
        <div class="stat"><div class="label">Median</div><div class="num">${fmt(s.median, site)}</div><div class="note">Middle price</div></div>
        <div class="stat"><div class="label">Highest</div><div class="num">${fmt(s.highest, site)}</div><div class="note">&nbsp;</div></div>
        <div class="stat stat-ours"><div class="label">Our price</div><div class="num">${fmt(ours, site)}</div><div class="note">${ourCardNote(run)}</div></div>
      </div>${verdict}${suggestHtml(run, results)}`;
}
function drawRun() {
    const {run, results} = selectedRun, site = run.market, ours = run.our_price == null ? null : Number(run.our_price);
    const max = Math.max(1, ...results.map(r => Number(r.price)), ours || 0);
    $('#detail').innerHTML = `<section class="card"><div class="head-row"><div><h3>${safe(run.keyword)}</h3>
      <p class="sub">${safe(SITES[site]?.name || site)} · ${when(run.started_at)}${run.cost_usd != null ? ' · Apify cost ' + usd(run.cost_usd) : ''}</p></div></div>
      ${refHtml(run)}
      <div id="statsBox">${statsHtml()}</div>
      ${results.length ? `<div class="table-wrap"><table><thead><tr><th>Count</th><th>Shopee listing</th><th>Seller</th><th class="num">Price</th><th>Rating</th><th>Sold</th></tr></thead><tbody>
      ${ourRowHtml(run)}${[...results].sort((a, b) => (b.relevant && !b.is_own) - (a.relevant && !a.is_own) || Number(a.price) - Number(b.price)).map(r => `<tr class="${r.is_own ? 'ours' : r.relevant ? '' : 'dim'}"><td><input type="checkbox" data-result="${r.id}" aria-label="Count this listing" ${r.included ? 'checked' : ''} ${r.is_own ? 'disabled' : ''}></td>
        <td><a href="${safe(r.url)}" target="_blank" rel="noopener noreferrer">${safe(r.title)}</a>${r.relevant || r.is_own ? '' : '<span class="pill stale-pill">May be a different product</span>'}</td>
        <td>${r.is_own ? '<span class="pill owned">Our shop</span>' : safe(r.seller_name || 'Shop ' + r.shop_id)}${r.location ? `<span class="muted small block">${safe(r.location)}</span>` : ''}</td>
        <td class="num"><span>${fmt(r.price, site)}</span>${r.original_price != null && Number(r.original_price) > Number(r.price) ? `<span class="muted small block"><s>${fmt(r.original_price, site)}</s>${r.discount_pct != null ? ' −' + Math.round(r.discount_pct) + '%' : ''}</span>` : ''}
          <div class="bar"><div class="fill comp" data-w="${100 * Number(r.price) / max}"></div></div></td>
        <td>${ratingCell(r)}</td><td>${soldCell(r)}</td></tr>`).join('')}</tbody></table></div>
      <p class="muted small">Listings that look like the same product are counted automatically. Untick any that are not, and the prices above update. Our own shop is never counted.</p>`
        : '<div class="empty">No listings with a price were returned for this keyword. Try a shorter keyword.</div>'}</section>`;
    applyWidths($('#detail'));
    document.querySelectorAll('input[data-result]').forEach(box => box.onchange = async () => {
        const id = Number(box.dataset.result), row = selectedRun.results.find(r => r.id === id); if (!row) return;
        row.included = box.checked; $('#statsBox').innerHTML = statsHtml();
        try {
            const out = await api(`/api/scrap/runs/${run.id}/results/${id}`, {method: 'PATCH', body: JSON.stringify({included: box.checked})});
            selectedRun.run = out.run; runs = runs.map(r => r.id === out.run.id ? out.run : r);
            const rowEl = document.querySelector(`.run-row[data-run="${run.id}"]`);
            if (rowEl) { rowEl.outerHTML = runSummaryRow(out.run); rebindRows(); }
        } catch (error) { row.included = !box.checked; box.checked = row.included; $('#statsBox').innerHTML = statsHtml(); inform(error.message, 'error'); }
    });
}
function rebindRows() {
    document.querySelectorAll('.run-row').forEach(row => {
        const open = () => openRun(Number(row.dataset.run));
        row.onclick = open; row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } };
    });
}

function showError(error) { setView(`<div class="head-row"><div><h2>Unable to load FirstWell Essentials</h2></div></div><p class="alert">${safe(error.message)}</p>`); }
document.querySelectorAll('.ps-tabs button').forEach(button => button.onclick = () => changeTab(button.dataset.tab));
load().catch(showError);


// ---------- Check links: every product with its Shopee link and a Legit / Not available answer, shared by all staff ----------
let linkChecks = {}, linkFilter = 'all', linkText = '', linkNote = '';
const checkKey = r => r.item_id + (r.variation_id ? '_' + r.variation_id : '');
const linkWhen = iso => { try { return new Date(iso).toLocaleString('en-MY', {day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit'}); } catch (_) { return ''; } };
async function linksPage() {
    setView('<div class="head-row"><div><h2>Check links</h2><p class="sub">Loading...</p></div></div>');
    linkNote = '';
    try { linkChecks = (await api('/api/scrap/link-checks')).checks || {}; } catch (error) { linkChecks = {}; linkNote = error.message; }
    if (tab !== 'links') return;
    setView(`<div class="head-row"><div><h2>Check links</h2>
        <p class="sub">Open each product on Shopee. If it opens and it is our product, press Legit. If Shopee says it is not available, press Not available. Everyone on the team sees the same answers.</p></div>
        <button type="button" class="primary" id="linkExport">Download results</button></div>
      ${linkNote ? `<p class="alert">${safe(linkNote)}</p>` : ''}
      <section class="card"><div class="link-prog"><div class="meter" role="img" aria-label="Checked progress"><i class="m-ok" id="mOk"></i><i class="m-bad" id="mBad"></i></div>
        <div class="link-counts" id="linkCounts"></div></div>
        <div class="link-tools"><input type="search" id="linkSearch" placeholder="Search product name" autocomplete="off" aria-label="Search product name" value="${safe(linkText)}">
        <div class="chips" id="linkChips"></div></div>
        <div id="linkList"></div></section>`);
    $('#linkSearch').oninput = e => { linkText = e.target.value; drawLinkList(); };
    $('#linkChips').onclick = e => { const b = e.target.closest('[data-f]'); if (b) { linkFilter = b.dataset.f; drawLinkChips(); drawLinkList(); } };
    $('#linkList').onclick = e => { const b = e.target.closest('button[data-set]'); if (b) saveLinkCheck(b.closest('.linkrow').dataset.key, b.dataset.set); };
    $('#linkExport').onclick = exportLinks;
    drawLinkChips(); drawLinkList();
}
function linkCounts() {
    let ok = 0, bad = 0;
    for (const r of catalog) { const c = linkChecks[checkKey(r)]; if (c && c.s === 'ok') ok++; else if (c && c.s === 'bad') bad++; }
    return {ok, bad, left: catalog.length - ok - bad};
}
function drawLinkChips() {
    const items = [['all', 'All'], ['todo', 'Not checked'], ['ok', 'Legit'], ['bad', 'Not available'], ['zero', 'Stock 0']];
    $('#linkChips').innerHTML = items.map(([k, l]) => `<button type="button" class="chip" data-f="${k}" aria-pressed="${linkFilter === k}">${l}</button>`).join('');
}
function drawLinkList() {
    const c = linkCounts(), n = Math.max(1, catalog.length);
    $('#linkCounts').innerHTML = `<span><b>${c.ok}</b> legit</span><span><b>${c.bad}</b> not available</span><span><b>${c.left}</b> left</span>`;
    $('#mOk').dataset.w = (100 * c.ok / n).toFixed(1); $('#mBad').dataset.w = (100 * c.bad / n).toFixed(1); applyWidths($('#view'));
    const words = linkText.toLowerCase().split(/\s+/).filter(Boolean);
    const rows = catalog.filter(r => {
        const s = (linkChecks[checkKey(r)] || {}).s || '';
        if (linkFilter === 'todo' && s) return false;
        if (linkFilter === 'ok' && s !== 'ok') return false;
        if (linkFilter === 'bad' && s !== 'bad') return false;
        if (linkFilter === 'zero' && Number(r.stock) > 0) return false;
        const t = cleanTitle(r.title).toLowerCase();
        return words.every(w => t.includes(w));
    });
    $('#linkList').innerHTML = rows.length ? rows.map(r => {
        const k = checkKey(r), ck = linkChecks[k] || {}, s = ck.s || '', stock = Number(r.stock);
        return `<div class="linkrow ${s ? 'is-' + s : ''}" data-key="${safe(k)}"><div class="lr-main"><div class="prod-name">${safe(cleanTitle(r.title))}</div>
          <div class="lr-meta"><span class="num">${r.price == null ? 'No price' : 'RM ' + Number(r.price).toFixed(2)}</span>
          ${stock > 0 ? `<span class="tag tag-ok">In stock (${stock})</span>` : '<span class="tag clr">Stock 0 in Excel</span>'}
          ${s === 'ok' ? '<span class="tag tag-ok">Legit</span>' : s === 'bad' ? '<span class="tag tag-bad">Not available</span>' : ''}</div>
          ${s ? `<div class="lr-by muted small">${s === 'ok' ? 'Confirmed legit' : 'Marked not available'}${ck.by ? ' by ' + safe(ck.by) : ''}${ck.at ? ', ' + safe(linkWhen(ck.at)) : ''}</div>` : ''}</div>
          <a class="btn-link" href="${safe(ourLink(r))}" target="_blank" rel="noopener noreferrer">Open on Shopee ↗</a>
          <div class="lr-acts"><button type="button" class="yes" data-set="ok" aria-pressed="${s === 'ok'}">Legit</button><button type="button" class="no" data-set="bad" aria-pressed="${s === 'bad'}">Not available</button>${s ? '<button type="button" data-set="">Clear</button>' : ''}</div></div>`;
    }).join('') : '<div class="empty">No products match.</div>';
}
async function saveLinkCheck(key, status) {
    const before = linkChecks[key];
    if (status) linkChecks[key] = {s: status, by: '', at: new Date().toISOString()}; else delete linkChecks[key];
    drawLinkList();
    try {
        const out = await api('/api/scrap/link-checks/' + encodeURIComponent(key), {method: 'PUT', body: JSON.stringify({status})});
        if (out.check) linkChecks[key] = out.check; else delete linkChecks[key];
    } catch (error) { if (before) linkChecks[key] = before; else delete linkChecks[key]; inform(error.message, 'error'); }
    if (tab === 'links') drawLinkList();
}
function exportLinks() {
    const q = v => '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
    const lines = [['Product', 'Our price (RM)', 'Stock in Excel', 'Link', 'Result', 'Checked by', 'Checked at'].map(q).join(',')];
    for (const r of catalog) {
        const c = linkChecks[checkKey(r)] || {};
        lines.push([cleanTitle(r.title), r.price, r.stock, ourLink(r), c.s === 'ok' ? 'Legit' : c.s === 'bad' ? 'Not available' : 'Not checked', c.by, c.at].map(q).join(','));
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['﻿' + lines.join('\n')], {type: 'text/csv'})); a.download = 'product-link-check.csv';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
