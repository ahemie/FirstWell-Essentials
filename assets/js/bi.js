/* FirstWell Essentials BI — reads only /api/bi/overview. No database secrets in this file. */
'use strict';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const n = v => Number(v || 0);
const digits = (v, places=0) => n(v).toLocaleString('en-MY', {minimumFractionDigits:places, maximumFractionDigits:places});
const cash = (v, cur) => `${cur === 'SGD' ? 'S$' : 'RM '}${digits(v,2)}`;
const first7 = v => String(v || '').slice(0,7);
let state = null;
let displayedRows = [];

async function fetchBI() {
  const response = await fetch('/api/bi/overview', {credentials:'same-origin',cache:'no-store'});
  if (response.status === 401) { location.href = '/login'; throw Error('Sign in required'); }
  let payload;
  try { payload = await response.json(); } catch { throw Error('Unexpected server response. Is Flask running?'); }
  if (!response.ok) throw Error(payload.error || `Server error ${response.status}`);
  return payload;
}

function setError(text) { $('error').textContent = text || ''; $('error').classList.toggle('bi-hidden', !text); }
function fillMonthOptions(months, preserve=false) {
  const previousStart = preserve ? $('startMonth').value : null;
  const previousEnd = preserve ? $('endMonth').value : null;
  for (const id of ['startMonth','endMonth']) {
    $(id).innerHTML = months.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
    $(id).disabled = months.length === 0;
  }
  if (months.length) {
    $('startMonth').value = previousStart && months.includes(previousStart) ? previousStart : months[0];
    $('endMonth').value = previousEnd && months.includes(previousEnd) ? previousEnd : months[months.length - 1];
  }
  $('topMarket').disabled = false;
}
const inRange = month => month >= $('startMonth').value && month <= $('endMonth').value;
function getFilteredMonthly() { return (state?.monthly || []).filter(row => inRange(first7(row.report_month))); }
function sumWhere(rows, field) { return rows.reduce((total, row) => total + n(row[field]), 0); }
function channelRows(rows, channel) { return rows.filter(row => row.channel === channel); }

function renderKpis(rows) {
  const my = channelRows(rows, 'Shopee MY');
  const sg = channelRows(rows, 'Shopee SG');
  const clinic = channelRows(rows, 'Clinic');
  $('kpiMY').textContent = my.length ? cash(sumWhere(my,'revenue'), 'MYR') : 'No report';
  $('kpiSG').textContent = sg.length ? cash(sumWhere(sg,'revenue'), 'SGD') : 'No report';
  $('kpiClinic').textContent = clinic.length ? cash(sumWhere(clinic,'revenue'), 'MYR') : 'No report';
  $('kpiMYUnits').textContent = my.length ? `${digits(sumWhere(my,'units_sold'))} units · source sales` : 'No MY report in selected months';
  $('kpiSGUnits').textContent = sg.length ? `${digits(sumWhere(sg,'units_sold'))} units · source sales` : 'No SG report in selected months';
  $('kpiClinicUnits').textContent = clinic.length ? `${digits(sumWhere(clinic,'units_sold'))} units · revenue estimated` : 'No Clinic report for selected period';
  // Month-end stock of the selected "To month": the snapshot dated that month's last day or the next day.
  const end = $('endMonth').value;
  let monthEnd = null;
  if (end && Array.isArray(state.inventory_by_date)) {
    const [y, m] = end.split('-').map(Number);
    const last = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10);
    const next = new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 10);
    monthEnd = state.inventory_by_date.filter(r => r.snapshot_date === last || r.snapshot_date === next)
      .sort((a, b) => b.snapshot_date.localeCompare(a.snapshot_date))[0] || null;
  }
  $('kpiStockLabel').textContent = monthEnd ? `Stock at end of ${end}` : 'Latest inventory value';
  if (monthEnd) {
    $('kpiStock').textContent = cash(monthEnd.total_stock_value_rm,'MYR');
    $('kpiStockDate').textContent = `Snapshot ${monthEnd.snapshot_date} · month-end stock`;
  } else {
    const inventory = state.inventory;
    $('kpiStock').textContent = inventory ? cash(inventory.total_stock_value_rm,'MYR') : 'Not available';
    $('kpiStockDate').textContent = inventory ? `No month-end stock for ${end || 'this month'} · showing latest, as of ${inventory.snapshot_date}` : 'No inventory snapshot';
  }
}
const channelStyle = {
  'Shopee MY': {color:'#527bbc',cur:'MYR'},
  'Shopee SG': {color:'#15b49e',cur:'SGD'},
  'Clinic': {color:'#c98b47',cur:'MYR'}
};
function compact(v, cur='') {
  const amount = n(v);
  const prefix = cur === 'SGD' ? 'S$' : cur === 'MYR' ? 'RM ' : '';
  if (Math.abs(amount) >= 1000000) return prefix + digits(amount/1000000, 1) + 'm';
  if (Math.abs(amount) >= 1000) return prefix + digits(amount/1000, 1) + 'k';
  return prefix + digits(amount, 0);
}
function renderDonut(rows) {
  // Comparable counts only. Currency and estimated Clinic revenue are NOT added.
  const channels = [
    {name:'Shopee MY',units:sumWhere(channelRows(rows,'Shopee MY'),'units_sold'),hasReport:channelRows(rows,'Shopee MY').length>0,color:'#527bbc'},
    {name:'Shopee SG',units:sumWhere(channelRows(rows,'Shopee SG'),'units_sold'),hasReport:channelRows(rows,'Shopee SG').length>0,color:'#15b49e'},
    {name:'Clinic movement',units:sumWhere(channelRows(rows,'Clinic'),'units_sold'),hasReport:channelRows(rows,'Clinic').length>0,color:'#f19b60'}
  ];
  const total = channels.reduce((v,x)=>v+x.units,0);
  let offset=0;
  const slices = channels.map(c => {
    const from=offset;
    offset += total > 0 ? c.units/total*100 : 0;
    return `${c.color} ${from.toFixed(5)}% ${offset.toFixed(5)}%`;
  });
  $('salesDonut').style.background = total > 0 ? `conic-gradient(${slices.join(',')})` : '#e9eeeb';
  $('salesDonut').setAttribute('aria-label', total>0
    ? channels.map(c=>`${c.name}: ${digits(c.units)} units`).join(', ')
    : 'No sales quantities in selected months');
  $('salesDonut').innerHTML=`<div class="bi-donut-center"><span>All channels</span><strong>${digits(total)}</strong><small>reported units</small></div>`;
  $('salesDonutLegend').innerHTML=channels.map(c=>{
    const pct=total>0?(c.units/total*100):0;
    return `<div class="bi-donut-row"><span class="bi-donut-swatch" style="background:${c.color}"></span><div><span class="bi-donut-label">${esc(c.name)}</span><span class="bi-donut-units">${c.hasReport?digits(c.units)+' units':'No report'}</span></div><span class="bi-donut-pct">${c.hasReport?digits(pct,1)+'%':'—'}</span></div>`;
  }).join('');
}
function niceTop(max) {
  if (max <= 0) return 1;
  const base = 10 ** Math.floor(Math.log10(max));
  for (const step of [1,2,2.5,5,10]) if (max <= step*base) return step*base;
  return 10*base;
}
function segments(points) {
  const parts=[];
  let current=[];
  for (const p of points) {
    if (!p) {if (current.length) parts.push(current);current=[];}
    else current.push(p);
  }
  if (current.length) parts.push(current);
  return parts;
}
// Checkboxes control *units sold* on one comparable axis. Do not add SGD to MYR.
const selectableChannels = ['Clinic', 'Shopee MY', 'Shopee SG'];
function selectedSalesChannels() {
  return [...document.querySelectorAll('.bi-channel-select')]
    .filter(box => box.checked)
    .map(box => box.value);
}
function renderUnitComparison(rows) {
  const selected = selectedSalesChannels();
  const target = $('salesAreaChart');
  const months = (state.months || []).filter(inRange);
  if (!selected.length) {
    target.innerHTML = '<div class="bi-chart-empty">Choose at least one channel above.</div>';
    target.setAttribute('aria-label', 'No channels selected');
    return;
  }
  if (!months.length) {
    target.innerHTML = '<div class="bi-chart-empty">No reporting months in this date range.</div>';
    return;
  }
  const values = selected.map(name => {
    const reports = new Map(channelRows(rows, name).map(row => [first7(row.report_month), row]));
    return {name, color:channelStyle[name].color, points:months.map(month => reports.has(month) ? n(reports.get(month).units_sold) : null)};
  });
  if (!values.some(series => series.points.some(value => value !== null))) {
    target.innerHTML = '<div class="bi-chart-empty">No reports for the selected channels and months.</div>';
    target.setAttribute('aria-label', 'No reported unit sales for selected channels');
    return;
  }
  const vw = 760, left = 58, right = 20, top = 30, bottom = 255;
  const chartWidth = vw - left - right, chartHeight = bottom - top;
  const scaleTop = niceTop(Math.max(0, ...values.flatMap(series => series.points.filter(value => value !== null))));
  const x = i => months.length === 1 ? left + chartWidth / 2 : left + i * chartWidth / (months.length - 1);
  const y = v => bottom - v / scaleTop * chartHeight;
  let graphic = '';
  for (let tick = 0; tick <= 4; tick++) {
    const yy = bottom - tick / 4 * chartHeight;
    graphic += `<line class="bi-gridline" x1="${left}" x2="${vw-right}" y1="${yy}" y2="${yy}"/>`;
    graphic += `<text x="${left-11}" y="${yy+4}" text-anchor="end">${esc(compact(scaleTop*tick/4))}</text>`;
  }
  graphic += `<text x="${left}" y="15" class="bi-axis-caption">UNITS SOLD · ALL SELECTED CHANNELS</text>`;
  const interval = Math.max(1, Math.ceil(months.length / (chartWidth / 68)));
  months.forEach((month, i) => {
    if (i % interval === 0 || i === months.length - 1)
      graphic += `<text x="${x(i)}" y="${bottom+24}" text-anchor="middle" class="bi-axis-month">${esc(month.slice(5))}/${esc(month.slice(2,4))}</text>`;
  });
  for (const series of values) {
    const points = series.points.map((value,i) => value === null ? null : {x:x(i), y:y(value), value, month:months[i]});
    for (const part of segments(points)) {
      const path = part.map((pt,i) => `${i ? 'L' : 'M'}${pt.x.toFixed(2)},${pt.y.toFixed(2)}`).join(' ');
      graphic += `<path d="${path}" fill="none" stroke="${series.color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>`;
    }
    for (const point of points.filter(Boolean)) {
      graphic += `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="5" fill="${series.color}" stroke="white" stroke-width="2"><title>${esc(series.name)} · ${esc(point.month)} · ${digits(point.value)} units</title></circle>`;
    }
  }
  target.innerHTML = `<svg viewBox="0 0 ${vw} 300" role="img" aria-label="Monthly reported units for ${esc(selected.join(', '))}">${graphic}</svg>`;
  target.setAttribute('aria-label', 'Monthly units sold trend: ' + selected.join(', '));
}
function wireChannelCheckboxes() {
  const all = $('channelAll');
  const boxes = [...document.querySelectorAll('.bi-channel-select')];
  all.addEventListener('change', () => {
    boxes.forEach(box => { box.checked = all.checked; });
    render();
  });
  boxes.forEach(box => box.addEventListener('change', () => {
    all.checked = boxes.every(option => option.checked);
    // Mixed state makes it clear when some, but not all, channels are selected.
    all.indeterminate = !all.checked && boxes.some(option => option.checked);
    render();
  }));
}

function renderRevenueDetail(rows) {
  const name=$('trendMarket').value;
  const info=channelStyle[name] || channelStyle['Shopee MY'];
  const months=(state.months||[]).filter(inRange);
  const bucket=new Map(channelRows(rows,name).map(r=>[first7(r.report_month),r]));
  $('trendCurrency').textContent=info.cur;
  $('trendNote').textContent=name==='Clinic'
    ? 'Clinic revenue is estimated using inventory prices, not POS receipts. Dashed line = stock-movement units.'
    : `Shopee ${name.endsWith('SG')?'Singapore':'Malaysia'} source sales in ${info.cur}. Missing months have no plotted values, not zero sales.`;
  if (!months.length || !months.some(m=>bucket.has(m))) {
    $('revenueDetailChart').innerHTML='<div class="bi-chart-empty">No data for this channel in the selected period.</div>';
    $('revenueDetailChart').setAttribute('aria-label','No monthly data available');
    return;
  }
  const vw=760, left=66, right=67, top=29, bottom=267;
  const width=vw-left-right, height=bottom-top;
  const found=months.map(m=>bucket.get(m)||null);
  const revenueTop=niceTop(Math.max(...found.map(r=>r?n(r.revenue):0),0));
  const unitsTop=niceTop(Math.max(...found.map(r=>r?n(r.units_sold):0),0));
  const x=i=>months.length===1?left+width/2:left+i*width/(months.length-1);
  const yRev=v=>bottom-n(v)/revenueTop*height;
  const yUnits=v=>bottom-n(v)/unitsTop*height;
  const coords=found.map((r,i)=>r?{x:x(i),y:yRev(r.revenue),month:months[i],r}:null);
  const dots=coords.filter(Boolean);
  const unitCoords=found.map((r,i)=>r?{x:x(i),y:yUnits(r.units_sold),month:months[i],r}:null);
  let graphic='';
  for(let step=0;step<=4;step++) {
    const y=bottom-step/4*height;
    graphic+=`<line class="bi-gridline" x1="${left}" x2="${vw-right}" y1="${y}" y2="${y}"/>`;
    graphic+=`<text x="${left-11}" y="${y+4}" text-anchor="end">${esc(compact(revenueTop*step/4))}</text>`;
    graphic+=`<text x="${vw-right+13}" y="${y+4}">${esc(compact(unitsTop*step/4))}</text>`;
  }
  graphic+=`<text x="${left}" y="15" class="bi-axis-caption">${esc(info.cur)} REVENUE</text>`;
  graphic+=`<text x="${vw-right}" y="15" class="bi-axis-caption" text-anchor="end">UNITS SOLD</text>`;
  const gradients=`<defs><linearGradient id="biRevGradient" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="${info.color}" stop-opacity=".38"/><stop offset="100%" stop-color="${info.color}" stop-opacity=".025"/></linearGradient></defs>`;
  for (const part of segments(coords)) {
    const line=part.map((p,i)=>(i===0?'M':'L')+p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ');
    if(part.length>1) {
      const first=part[0],last=part[part.length-1];
      graphic+=`<path d="${line} L${last.x.toFixed(2)},${bottom} L${first.x.toFixed(2)},${bottom} Z" fill="url(#biRevGradient)"/>`;
    }
    graphic+=`<path d="${line}" stroke="${info.color}" stroke-width="3.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  }
  for (const part of segments(unitCoords)) {
    const line=part.map((p,i)=>(i===0?'M':'L')+p.x.toFixed(2)+','+p.y.toFixed(2)).join(' ');
    graphic+=`<path d="${line}" stroke="#ef9b60" stroke-width="2.5" stroke-dasharray="7 6" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`;
  }
  for (const p of dots) {
    graphic+=`<circle cx="${p.x}" cy="${p.y}" r="5.5" fill="${info.color}" stroke="white" stroke-width="2"><title>${esc(p.month)} • ${esc(cash(p.r.revenue,info.cur))} • ${digits(p.r.units_sold)} units</title></circle>`;
  }
  const minSpacing=56, sampleEvery=Math.max(1,Math.ceil(months.length/(width/minSpacing)));
  months.forEach((m,i)=>{if(i%sampleEvery===0 || i===months.length-1) graphic+=`<text x="${x(i)}" y="${bottom+24}" text-anchor="middle" class="bi-axis-month">${esc(m.slice(5))}/${esc(m.slice(2,4))}</text>`});
  $('revenueDetailChart').innerHTML=`<svg viewBox="0 0 ${vw} 306" role="img" aria-label="Revenue and unit sales for ${esc(name)}, selected months">${gradients}${graphic}</svg>`;
  $('revenueDetailChart').setAttribute('aria-label',`Revenue and units trend for ${name} (${info.cur})`);
}
let topShowAll=false;   // false = top 20 sellers, true = listings with no sales
let topSort={key:'revenue',direction:'desc'};   // click Unit sold / Revenue in the table header to change
function renderTopProducts() {
  const market = $('topMarket').value;
  const currency = market === 'SG' ? 'SGD' : 'MYR';
  $('topTag').textContent = currency;
  // Aggregate inside only one currency, and use clean view's sales levels.
  const grouped = new Map();
  for (const row of state.shopee_details || []) {
    if (row.marketplace !== market || !inRange(first7(row.month))) continue;
    if (!row.mapped) continue;   // only listings linked to an Avixo product are listed (totals still include all sales)
    const key = row.mapped ? `p:${row.avixo_id}` : `u:${row.item_id}`;
    const group = grouped.get(key) || {key, name:row.name, units:0, revenue:0, mapped:row.mapped, avixo_id:row.avixo_id};
    group.units += n(row.units);
    group.revenue += n(row.revenue);
    grouped.set(key,group);
  }
  const sk=topSort.key==='units'?'units':'revenue', sd=topSort.direction==='asc'?1:-1;
  const sold=[...grouped.values()].filter(x=>x.units>0 || x.revenue>0).sort((a,b)=>sd*(a[sk]-b[sk]) || b.revenue-a.revenue || b.units-a.units || a.name.localeCompare(b.name));
  const soldKeys=new Set(sold.map(x=>x.key));
  const catalogue=(state.shopee_listings||{})[market]||[];
  const unsold=catalogue.filter(x=>!soldKeys.has(x.key));
  const LIMIT=20;
  const sortHead=(key,label)=>{const on=sk===key;return `<th class="bi-num" aria-sort="${on?(sd===1?'ascending':'descending'):'none'}"><button type="button" class="bi-sort${on?' on':''}" data-sort="${key}">${label}<span class="bi-sort-arrow">${on?(sd===1?' ▲':' ▼'):' ↕'}</span></button></th>`;};
  const table=(rows,withRank)=>`<div class="bi-top-table"><table class="bi-table"><thead><tr>${withRank?'<th class="bi-rank-col">#</th>':''}<th>Name</th>${sortHead('units','Unit sold')}${sortHead('revenue',`Revenue (${currency})`)}</tr></thead><tbody>${rows.map((x,i)=>`<tr>${withRank?`<td class="bi-rank-col">${i+1}</td>`:''}<td title="${esc(x.name)}">${esc(x.name)}</td><td class="bi-num">${digits(x.units)}</td><td class="bi-num">${esc(cash(x.revenue,currency))}</td></tr>`).join('')}</tbody></table></div>`;
  const noSaleTable=rows=>`<div class="bi-top-table bi-ranked-scroll"><table class="bi-table"><thead><tr><th>Name</th><th>Avixo ID</th><th class="bi-num">Unit sold</th></tr></thead><tbody>${rows.map(x=>`<tr><td title="${esc(x.name)}">${esc(x.name)}</td><td>${x.mapped?esc(x.avixo_id):(x.flag==='free_item'?'<span class="bi-free-tag">Free item</span>':'Unmapped')}</td><td class="bi-num">0</td></tr>`).join('')}</tbody></table></div>`;
  if (topShowAll) {
    $('topHeading').textContent='Products with no sales';
    $('topSub').textContent='Shopee listings in the selected marketplace that sold nothing in the selected months.';
    $('topProducts').innerHTML = unsold.length ? noSaleTable(unsold) : '<div class="bi-empty">Every listing in this marketplace had at least one sale in this period.</div>';
    $('topCount').textContent=`${digits(unsold.length)} of ${digits(catalogue.length)} listings had no sales`;
  } else {
    const shown=sold.slice(0,LIMIT);
    $('topHeading').textContent='Top Shopee products';
    $('topSub').textContent=`Top 20 by ${sk==='units'?'units sold':'revenue'}${sd===1?' (lowest first)':''} within the selected marketplace only. Click Unit sold or Revenue to sort.`;
    $('topProducts').innerHTML = shown.length ? table(shown,true) : '<div class="bi-empty">No Shopee sales in this period for the selected marketplace.</div>';
    $('topCount').textContent=sold.length?`Showing ${digits(shown.length)} of ${digits(sold.length)} products with sales`:'';
  }
  const btn=$('topToggle');
  btn.hidden=false;
  btn.textContent=topShowAll?`Back to top ${LIMIT}`:`Show products with no sales (${digits(unsold.length)})`;
  btn.setAttribute('aria-expanded',String(topShowAll));
}
function renderStock() {
  const i=state.inventory;
  $('inventoryDate').textContent = i?.snapshot_date || 'No snapshot';
  $('stockSummary').innerHTML = i ? `
    <div class="bi-stock-item"><strong>${digits(i.products_with_snapshot)}</strong><small>Products with stock snapshot</small></div>
    <div class="bi-stock-item"><strong>${digits(i.total_stock_units)}</strong><small>Stock units</small></div>
    <div class="bi-stock-item"><strong>${digits(state.low_stock_count)}</strong><small>Products with ≤ 5 units</small></div>` : '<div class="bi-empty">No inventory snapshot available.</div>';
  $('lowStock').innerHTML = state.stock_alerts?.length ? state.stock_alerts.slice(0,7).map(x=>`
     <div class="bi-low-item"><span class="bi-low-name" title="${esc(x.name)}">${esc(x.name)}</span><span class="bi-low-qty">${digits(x.quantity)} units</span></div>`).join('') : '<div class="bi-empty">No stock alerts in the latest snapshot.</div>';
}
function renderPrices() {
  const markets=[['MY','Malaysia'],['SG','Singapore']];
  $('priceSnapshots').innerHTML = markets.map(([id,label]) => {
    const p=state.listing_prices?.[id];
    return p ? `<div class="bi-price-card"><div class="bi-price-head"><span>Shopee ${esc(label)}</span><span class="bi-small-tag">${esc(p.date)}</span></div><div class="bi-price-n">${digits(p.rows)} <span style="font-size:12px;font-weight:500">variation prices</span></div><div class="bi-price-summary">${digits(p.items)} unique items · range ${esc(cash(p.min,p.currency))} – ${esc(cash(p.max,p.currency))}</div></div>`
      : `<div class="bi-price-card"><div class="bi-price-head">Shopee ${esc(label)} <span class="bi-small-tag">Not imported</span></div><div class="bi-price-summary">No listing-price snapshot has been saved yet.</div></div>`;
  }).join('');
}
function renderImports() {
  const rows=(state.recent_imports||[]).slice(0,7);
  $('importList').innerHTML = rows.length ? rows.map(x=>{
    const bad=x.status!=='imported';
    return `<div class="bi-import"><div style="min-width:0"><strong title="${esc(x.original_filename)}">${esc(x.original_filename)}</strong><small>${esc(x.kind)} · ${esc(first7(x.reporting_month)||x.snapshot_date||'Date not supplied')}</small></div><span class="bi-state ${bad?'pending':''}">${esc(x.status)}</span></div>`;
  }).join('') : '<div class="bi-empty">No import history recorded.</div>';
}
function renderMonthlyTable(rows) {
  displayedRows=[...rows].sort((a,b)=>String(b.report_month).localeCompare(String(a.report_month))||a.channel.localeCompare(b.channel));
  $('monthlyTable').innerHTML=displayedRows.length ? `<table class="bi-table"><thead><tr><th>Month</th><th>Channel</th><th>Revenue basis</th><th>Currency</th><th class="bi-num">Units</th><th class="bi-num">Matched</th><th class="bi-num">Unmatched</th><th>Revenue</th></tr></thead><tbody>${displayedRows.map(x=>`<tr><td>${esc(first7(x.report_month))}</td><td><b>${esc(x.channel)}</b></td><td>${esc(x.revenue_basis||'Source sales')}</td><td>${esc(x.currency)}</td><td class="bi-num">${digits(x.units_sold)}</td><td class="bi-num">${digits(x.matched_rows)}</td><td class="bi-num">${digits(x.unmatched_rows)}</td><td class="bi-num"><b>${esc(cash(x.revenue,x.currency))}</b></td></tr>`).join('')}</tbody></table>` : '<div class="bi-empty">No complete monthly summaries for your selected dates.</div>';
}
function render() {
  if (!state) return;
  if ($('startMonth').value > $('endMonth').value) {
    setError('From month must be before or equal to To month.');
    $('dashboard').classList.add('bi-hidden');
    return;
  }
  setError('');
  const rows=getFilteredMonthly();
  $('filterInfo').textContent=`${rows.length} reporting rows · ${$('startMonth').value || '—'} to ${$('endMonth').value || '—'}`;
  renderKpis(rows);
  renderDonut(rows);
  renderUnitComparison(rows);
  renderRevenueDetail(rows);
  renderTopProducts();
  renderStock();
  renderPrices();
  renderImports();
  renderMonthlyTable(rows);
  $('dashboard').classList.remove('bi-hidden');
}
function csvCell(value) {
  // Prevent spreadsheet formula injection when opening an exported CSV.
  let content=String(value ?? '');
  if (/^[\s]*[=+@-]/.test(content)) content="'"+content;
  return '"'+content.replaceAll('"','""')+'"';
}
function exportCsv(){
  const headers=['Month','Channel','Revenue basis','Currency','Units','Matched rows','Unmatched rows','Revenue'];
  const values=displayedRows.map(x=>[first7(x.report_month),x.channel,x.revenue_basis,x.currency,x.units_sold,x.matched_rows,x.unmatched_rows,x.revenue]);
  const csv='\uFEFF'+[headers,...values].map(row=>row.map(csvCell).join(',')).join('\r\n');
  const url=URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=`FirstWell_Essentials_BI_${$('startMonth').value}_${$('endMonth').value}.csv`;
  document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url);
}
async function load(preserve=false) {
  $('loading').classList.remove('bi-hidden');$('dashboard').classList.add('bi-hidden');setError('');
  try {
    const response=await fetchBI();
    state=response;
    fillMonthOptions(response.months||[],preserve);
    $('asof').textContent=response.inventory ? `Inventory as of ${response.inventory.snapshot_date}` : 'Connected to Supabase';
    render();
  } catch(e){setError(e.message)} finally{$('loading').classList.add('bi-hidden')}
}
for(const id of ['startMonth','endMonth','topMarket','trendMarket']) $(id).addEventListener('change',render);
$('topMarket').addEventListener('change',()=>{topShowAll=false;});
$('topToggle').addEventListener('click',()=>{topShowAll=!topShowAll;renderTopProducts();});
// Sort buttons live inside the re-drawn table, so listen on the container.
$('topProducts').addEventListener('click',event=>{
  const button=event.target&&event.target.closest?event.target.closest('[data-sort]'):null;
  if(!button) return;
  const key=button.dataset.sort==='units'?'units':'revenue';
  topSort={key,direction:topSort.key===key&&topSort.direction==='desc'?'asc':'desc'};
  renderTopProducts();
});
$('refresh').addEventListener('click',()=>load(true));
$('exportCsv').addEventListener('click',exportCsv);
wireChannelCheckboxes();
load();
