// Upload Data > Shopee listing links. Check first (nothing written), then Save.
(() => {
  const $ = id => document.getElementById(id);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let csrf = '', checked = null;

  async function call(url) {
    const data = new FormData();
    data.append('market', $('linksMarket').value);
    data.append('file', $('linksFile').files[0]);
    const r = await fetch(url, {method: 'POST', credentials: 'same-origin', cache: 'no-store', headers: {'X-CSRF-Token': csrf}, body: data});
    let body; try { body = await r.json(); } catch { throw Error('Unexpected server response'); }
    if (!r.ok) throw Error(body.error || `Server error ${r.status}`);
    return body;
  }

  function show(res, saved) {
    const rows = [
      ['Rows with an Avixo ID / FREE', res.rows_in_file],
      ['Shopee listings in the file', res.listings_in_file],
      ['Free gifts (FREE)', res.free_items],
      ['Links before → after', `${res.links_before} → ${res.links_after}`],
      [saved ? 'Sales rows re-matched' : 'Sales rows that will be re-matched', res.sales_rows_rematched],
      ['Sales rows still unmapped after this (parent / variation)', `${res.sales_parent_rows_unmapped_after} / ${res.sales_variation_rows_unmapped_after}`],
    ];
    const unknown = (res.unknown_avixo_ids || []).length
      ? `<div class="message error">These Avixo IDs are not in the product list — fix them in column K: ${esc(res.unknown_avixo_ids.join(', '))}</div>` : '';
    $('linksResult').innerHTML = `${saved ? `<div class="message">${esc(res.message)}</div>` : ''}${unknown}
      <div class="tablewrap"><table><tbody>${rows.map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function init() {
    if (!$('linksForm')) return;
    try { csrf = (await (await fetch('/api/auth/session', {credentials: 'same-origin'})).json()).csrf_token; } catch {}
    $('linksFile').addEventListener('change', () => { checked = null; $('linksSaveBtn').disabled = true; $('linksResult').innerHTML = ''; });
    $('linksMarket').addEventListener('change', () => { checked = null; $('linksSaveBtn').disabled = true; });
    $('linksForm').addEventListener('submit', async e => {
      e.preventDefault();
      if (!$('linksFile').files[0]) return;
      $('linksCheckBtn').disabled = true; $('linksResult').innerHTML = '<div class="empty">Checking…</div>';
      try { checked = await call('/api/links/preview'); show(checked, false); $('linksSaveBtn').disabled = !checked.can_save; }
      catch (err) { $('linksResult').innerHTML = `<div class="message error">${esc(err.message)}</div>`; }
      finally { $('linksCheckBtn').disabled = false; }
    });
    $('linksSaveBtn').addEventListener('click', async () => {
      if (!checked) return;
      $('linksSaveBtn').disabled = true;
      try { show(await call('/api/links/save'), true); checked = null; }
      catch (err) { $('linksResult').innerHTML = `<div class="message error">${esc(err.message)}</div>`; $('linksSaveBtn').disabled = false; }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
