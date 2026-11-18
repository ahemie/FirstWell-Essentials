// Run: node tests/smoke_bi.js — mock front-end API test, NO database access.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const elements = new Map();
const channelBoxes = ['Clinic','Shopee MY','Shopee SG'].map(value=>({value, checked:true, addEventListener(type,fn){this['on'+type]=fn}}));
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    id, value: id==='topMarket'?'MY':id==='trendMarket'?'Shopee MY':'', checked:id==='channelAll', innerHTML:'', textContent:'', disabled:false, style:{}, attributes:{}, setAttribute(k,v){this.attributes[k]=v},
    classList: {values:new Set(['bi-hidden']), add(x){this.values.add(x)}, remove(x){this.values.delete(x)}, toggle(x,yes){if(yes)this.add(x); else this.remove(x)}},
    addEventListener(type,fn){this['on'+type]=fn}
  });
  return elements.get(id);
}
const payload={
 ok:true,source:'supabase',months:['2026-07','2026-08','2026-09'],
 monthly:[
 {report_month:'2026-09-01',channel:'Shopee MY',currency:'MYR',units_sold:'30',revenue:'1000.25',matched_rows:1,unmatched_rows:0,revenue_basis:'source sales'},
 {report_month:'2026-09-01',channel:'Shopee SG',currency:'SGD',units_sold:'5',revenue:'150.50',matched_rows:1,unmatched_rows:0,revenue_basis:'source sales'},
 {report_month:'2026-09-01',channel:'Clinic',currency:'MYR',units_sold:'6',revenue:'300.00',matched_rows:1,unmatched_rows:0,revenue_basis:'estimated: units × clinic price'}],
 inventory:{snapshot_date:'2026-10-01',total_products:512,products_with_snapshot:512,total_stock_units:20224,total_stock_value_rm:'331917.82'},
 stock_alerts:[{name:'Test stock',quantity:0}],low_stock_count:1,
 inventory_charts:{snapshot_date:'2026-10-01',categories:[{name:'Baby Care',healthy:15,low_stock:3,out_of_stock:2,unknown:0},{name:'Accessories',healthy:4,low_stock:1,out_of_stock:0,unknown:0}],value_bands:[{label:'RM 0–500',count:100,total_value_rm:15000},{label:'RM 501–2k',count:70,total_value_rm:83000},{label:'RM 2k–5k',count:30,total_value_rm:99000},{label:'Over RM 5k',count:16,total_value_rm:134917.82}],value_missing_or_negative_products:0},
 shopee_details:[{month:'2026-09-01',marketplace:'MY',item_id:'12',variation_id:'0',name:'Test item',avixo_id:'010',mapped:true,units:30,revenue:1000.25,currency:'MYR'},
  ...Array.from({length:24},(_,i)=>({month:'2026-09-01',marketplace:'MY',item_id:String(100+i),variation_id:'0',name:i===23?'Lowest seller':'Filler '+i,avixo_id:String(500+i),mapped:true,units:1,revenue:500-i*20,currency:'MYR'}))],
 shopee_listings:{MY:[{key:'p:010',name:'Test item',avixo_id:'010',mapped:true},{key:'p:999',name:'Never sold A',avixo_id:'999',mapped:true},{key:'u:777',name:'Free gift 777',avixo_id:null,mapped:false,flag:'free_item'}],SG:[]},
 listing_prices:{MY:{date:'2026-10-10',rows:574,items:490,min:1.50,max:217.40,currency:'MYR'}},recent_imports:[]
};
const ctx={
 document:{getElementById:element,querySelectorAll(selector){return selector==='.bi-channel-select'?channelBoxes:[]},createElement:()=>({click(){},remove(){}}),body:{append(){}}},
 fetch:async()=>({ok:true,json:async()=>payload}),
 console, URL, Blob, location:{href:''}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('assets/js/bi.js','utf8'),ctx);
setTimeout(()=>{
 try {
  assert(element('kpiMY').textContent.includes('1,000.25'));
  assert(element('kpiSG').textContent.includes('150.50'));
  assert(element('kpiClinic').textContent.includes('300.00'));
  assert(element('kpiStock').textContent.includes('331,917.82'));
  assert(element('topProducts').innerHTML.includes('Test item'));
  assert(element('priceSnapshots').innerHTML.includes('574'));
  assert(element('monthlyTable').innerHTML.includes('2026-09'));
  assert(element('salesDonutLegend').innerHTML.includes('Shopee SG'));
  assert(element('salesDonut').style.background.includes('conic-gradient'));
  assert(element('salesAreaChart').innerHTML.includes('<svg'));
  // Removed sections must stay removed (no render target left behind).
  assert(!element('inventoryCategoryBars').innerHTML && !element('inventoryValueBands').innerHTML && !element('channelSummary').innerHTML);
  // Top products: table of 20 (name, unit sold, revenue); toggle lists ONLY listings with no sales.
  const rows=()=>(element('topProducts').innerHTML.match(/<tr>/g)||[]).length-1;
  assert.strictEqual(rows(),20);
  assert(element('topProducts').innerHTML.includes('Unit sold') && element('topProducts').innerHTML.includes('Revenue (MYR)'));
  assert(element('topProducts').innerHTML.includes('Test item'));
  assert(!element('topProducts').innerHTML.includes('Never sold A'));
  assert(element('topToggle').textContent.includes('no sales (2)'));
  // Sort buttons: Unit sold / Revenue re-rank the whole list; a second click flips the order.
  const clickSort=key=>element('topProducts').onclick({target:{closest:()=>({dataset:{sort:key}})}});
  const firstName=()=>((element('topProducts').innerHTML.match(/<td title="([^"]*)"/)||[])[1]);
  assert(element('topProducts').innerHTML.includes('data-sort="units"') && element('topProducts').innerHTML.includes('data-sort="revenue"'));
  assert.strictEqual(firstName(),'Test item');                    // default: highest revenue
  clickSort('units'); assert.strictEqual(firstName(),'Test item'); // 30 units is the most
  assert(element('topProducts').innerHTML.includes('aria-sort="descending"') && element('topSub').textContent.includes('units sold'));
  clickSort('units'); assert.notStrictEqual(firstName(),'Test item'); assert(element('topSub').textContent.includes('lowest first')); // flipped: lowest units first
  clickSort('revenue'); assert.strictEqual(firstName(),'Test item'); // new column starts highest first
  clickSort('revenue'); assert.strictEqual(firstName(),'Lowest seller'); // flipped: lowest revenue
  clickSort('revenue'); assert.strictEqual(firstName(),'Test item');
  element('topToggle').onclick();
  assert.strictEqual(rows(),2);
  assert(element('topProducts').innerHTML.includes('Never sold A') && element('topProducts').innerHTML.includes('Free gift 777'));
  assert(!element('topProducts').innerHTML.includes('Test item'));
  element('topToggle').onclick();
  assert.strictEqual(rows(),20);
  assert(element('salesAreaChart').innerHTML.includes('Shopee MY'));
  assert(element('salesAreaChart').innerHTML.includes('Shopee SG'));
  assert(element('revenueDetailChart').innerHTML.includes('1,000.25') || element('revenueDetailChart').innerHTML.includes('1000.25'));
  // Unticking Shopee SG must remove its line while leaving other lines displayed.
  channelBoxes[2].checked=false;
  channelBoxes[2].onchange();
  assert(!element('channelAll').checked);
  assert(!element('salesAreaChart').innerHTML.includes('Shopee SG'));
  assert(element('salesAreaChart').innerHTML.includes('Clinic'));
  // All checkbox re-enables every channel.
  element('channelAll').checked=true;
  element('channelAll').onchange();
  assert(channelBoxes.every(b=>b.checked));
  assert(element('salesAreaChart').innerHTML.includes('Shopee SG'));
  assert(!element('error').textContent);
  console.log('PASS: BI charts + checkbox all/individual controls, separated MYR/SGD revenue drilldown, inventory and KPIs');
 } catch (e) { console.error(e);process.exitCode=1; }
},40);
