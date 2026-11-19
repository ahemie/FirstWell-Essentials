/* =======================================================================
   FIRSTSTEP INVENTORY DASHBOARD — BEGINNER-FRIENDLY JAVASCRIPT
   =======================================================================
   READ THIS FIRST:
   1. SETTINGS:        The numbers used to decide which stock needs attention.
   2. DATA FORMAT:     Short field names from the existing monthly data files.
   3. CALCULATIONS:    Work out stock values, sales, margins and alerts.
   4. LOADING DATA:    Read data/months.js and data/YYYY-MM.js.
   5. DISPLAY:         Build the filters, cards, product table and warnings.
   6. BUTTONS:         React when someone clicks or types.

   You do NOT need React, npm or a database to read this file.
   Keep index.html in the SAME folder as the data/ folder.
   ======================================================================= */

// -----------------------------------------------------------------------
// 1. SETTINGS AND LABELS
// -----------------------------------------------------------------------
// Change these numbers only if the clinic decides to change its stock rules.
// For example, SLOW_UNITS: 5 means selling 1–4 units is "slow moving".

const RULES = {
  SLOW_UNITS: 5,          // slow moving = 1..4 units in the month (all channels)
  HIGH_MONTHS: 3,         // high stock = cover above 3 months (and 5+ units a month)
  EXPIRY_DAYS: 90,        // expiry window from the stock date
  LOW_MONTHS: 0.75,       // low stock = cover below 0.75 month
  LEAD_MONTHS: 0.5,       // supplier lead time used for profit at risk
  GM_CLINIC: 25, GM_CLINIC_VACCINE: 10, GM_ECOM: 8
};
const CARD_INFO = {
  all: { label: 'All inventory', color: '#17201D', sub: 'Stock value at latest cost', rule: 'Every product in stock on the stock date or sold in the month.', value: 'Value: stock × latest cost.' },
  sales: { label: 'Total sales', color: '#0E5A52', sub: '', rule: 'Sales in the month across the channels in the current view.', value: 'Top: RM. Bottom: units. Clinic = units × clinic price (estimate); Shopee = confirmed (MY) and paid (SG) order value; SG converted to RM.' },
  nonmoving: { label: 'Non-moving', color: '#5E636B', sub: 'Stock value', rule: 'Zero units sold in the month in any channel, with stock on hand.', value: 'Value: stock at cost.' },
  slow: { label: 'Slow moving', color: '#8A6D1F', sub: 'Stock value', rule: '1 to 4 units sold in the month, all channels combined.', value: 'Value: stock at cost.' },
  high: { label: 'High stock', color: '#1F5FA8', sub: 'Value above 3 months of cover', rule: '5 or more units a month, but more than 3 months of cover.', value: 'Value: stock above 3 months × cost.' },
  expiry: { label: 'Expiry risk', color: '#A3262E', sub: 'Cost of units that will not sell', rule: 'A batch expires within 3 months of the stock date, or has expired.', value: 'Value: units that will not sell before expiry at this month’s rate, plus expired units.' },
  marginClinic: { label: 'Low margin · clinic', color: '#7A3A00', sub: 'Stock value affected', rule: 'Clinic GM below 25% (vaccines below 10%).', value: 'Value: stock at cost.' },
  marginEcom: { label: 'Low margin · e-com', color: '#6B3FA0', sub: 'Stock value affected', rule: 'Shopee MY or SG GM below 8%, before Shopee fees.', value: 'Value: stock at cost.' },
  lowstock: { label: 'Low stock', color: '#B35400', sub: 'Gross profit at risk', rule: 'Less than 0.75 month (about 3 weeks) of cover.', value: 'Value: gross profit lost over a 2-week supplier lead time if not reordered, at this month’s blended margin.' }
};
const CARD_ORDER = ['all', 'sales', 'nonmoving', 'slow', 'high', 'expiry', 'marginClinic', 'marginEcom', 'lowstock'];
const ALERT_KEYS = ['expiry', 'nonmoving', 'slow', 'high', 'marginClinic', 'marginEcom', 'lowstock'];
const BADGE = { nonmoving: ['#ECEDEF', '#41454D'], slow: ['#F5EDD6', '#5E4A12'], high: ['#E3EEFB', '#1A4C86'], expiry: ['#FBEAEA', '#7E1A22'], marginClinic: ['#F6E9DA', '#6B3500'], marginEcom: ['#EFE7F8', '#4F2C7A'], lowstock: ['#FCEBDC', '#7A3A00'] };
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

// -----------------------------------------------------------------------
// 2. HOW TO READ THE SHORT NAMES IN YOUR MONTHLY JSON/JS DATA
// -----------------------------------------------------------------------
// The data files were created with short keys. The code below explains them.
// p.n  = name                 p.id = product ID
// p.c  = category             p.q  = current quantity in stock
// p.s  = clinic units sold    p.lc = latest cost (RM per unit)
// p.p  = clinic selling price p.val = stock value from the source data
// p.x  = earliest expiry date p.b = expiry batches ([date, quantity])
// p.my = Shopee Malaysia data (units, sales, price, listed)
// p.sg = Shopee Singapore data (units, sales, price, listed)
// p.mm, p.mc, p.bs, p.qs, p.eg = source-data checking fields
//
// Example: A product with p.q = 20, p.s = 3 and p.my.units = 2
//          has 20 items in stock and sold 5 items this month.

// -----------------------------------------------------------------------
// 3. SMALL REUSABLE HELPERS
// -----------------------------------------------------------------------

// Never insert unescaped product names into HTML. This protects the page
// if a product name contains characters such as < or &.
function escapeHtml(value) {
  const text = value == null ? '' : String(value);
  const specialCharacters = {
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  };
  return text.replace(/[&<>"']/g, character => specialCharacters[character]);
}

function formatNumber(number, decimalPlaces = 0) {
  return Math.abs(number)
    .toFixed(decimalPlaces)
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Example: formatMoney(12.5) -> "RM 12.50"
function formatMoney(amount) {
  if (amount == null) return 'Unavailable';
  const sign = amount < 0 ? '−RM ' : 'RM ';
  return sign + formatNumber(amount, 2);
}

// Shopee Singapore data is stored in RM (S$ x the month's rate). The rate lets us show the original S$ beside the RM.
function singaporeRate() {
  const fx = Number(state.monthData && state.monthData.meta && state.monthData.meta.fx);
  return Number.isFinite(fx) && fx > 0 ? fx : null;
}
function formatSgd(rmAmount) {
  const fx = singaporeRate();
  return rmAmount == null || !fx ? null : 'S$ ' + formatNumber(rmAmount / fx, 2);
}

// This is the rounded version shown on the big summary cards.
function formatRoundedMoney(amount) {
  const sign = amount < 0 ? '−RM ' : 'RM ';
  return sign + formatNumber(Math.round(amount));
}

function formatPercent(value) {
  return value == null ? 'n/a' : value.toFixed(1) + '%';
}

// Example: "2026-10-13" -> "13 Oct 2026"
function formatDate(dateText) {
  if (!dateText) return null;
  const parts = dateText.split('-');
  const day = Number(parts[2]);
  const month = MONTHS[Number(parts[1]) - 1];
  return `${day} ${month} ${parts[0]}`;
}

function daysBetween(dateText, stockDate) {
  const millisecondsInOneDay = 86400000;
  return Math.round(
    (Date.parse(dateText) - Date.parse(stockDate)) / millisecondsInOneDay
  );
}

// Gross margin (%) = (selling price - cost) / selling price * 100.
// A missing or zero price/cost returns null, meaning "not available".
function calculateGrossMargin(sellingPrice, costPrice) {
  if (!sellingPrice || !costPrice) return null;
  return ((sellingPrice - costPrice) / sellingPrice) * 100;
}

function makeTag(text, backgroundColor, textColor) {
  return `<span class="tag" style="background:${backgroundColor};color:${textColor}">${escapeHtml(text)}</span>`;
}

// Sorting helper. Empty values are placed after known values.
function compareValues(first, second) {
  const firstEmpty = first == null;
  const secondEmpty = second == null;
  if (firstEmpty && secondEmpty) return 0;
  if (firstEmpty) return 1;
  if (secondEmpty) return -1;
  if (typeof first === 'string') return first.localeCompare(second);
  return first - second;
}

// -----------------------------------------------------------------------
// 4. ANALYSE ONE PRODUCT
// -----------------------------------------------------------------------
// This is the most important function to study first.
// Input:  one raw product from the monthly file, plus month information.
// Output: the same product with calculated sales, stock value and alerts.
function analyseProduct(product, monthInfo) {
  const costPrice = product.lc || null;
  const clinicPrice = product.p || null;
  const shopeeMalaysia = product.my;
  const shopeeSingapore = product.sg;

  // Combine sales from the clinic and both Shopee shops.
  const clinicUnitsSold = product.s || 0;
  const malaysiaUnitsSold = shopeeMalaysia ? shopeeMalaysia.units : 0;
  const singaporeUnitsSold = shopeeSingapore ? shopeeSingapore.units : 0;
  const totalUnitsSold = clinicUnitsSold + malaysiaUnitsSold + singaporeUnitsSold;

  // Months of stock cover = stock on hand / units sold this month.
  // Example: 30 in stock / 10 sold = 3 months of cover.
  const stockCoverMonths = totalUnitsSold > 0
    ? product.q / totalUnitsSold
    : null;

  const clinicMarginMinimum = product.c === 'Vaccine'
    ? RULES.GM_CLINIC_VACCINE
    : RULES.GM_CLINIC;

  const result = {
    product: product,
    costPrice: costPrice,
    clinicPrice: clinicPrice,
    totalUnitsSold: totalUnitsSold,
    stockValue: product.val || (costPrice ? product.q * costPrice : 0),
    clinicMargin: calculateGrossMargin(clinicPrice, costPrice),
    malaysiaPrice: shopeeMalaysia && shopeeMalaysia.price || null,
    singaporePrice: shopeeSingapore && shopeeSingapore.price || null,
    stockCoverMonths: stockCoverMonths,
    clinicMarginMinimum: clinicMarginMinimum,
    clinicSales: clinicPrice ? clinicUnitsSold * clinicPrice : 0,
    malaysiaSales: shopeeMalaysia ? shopeeMalaysia.sales : 0,
    singaporeSales: shopeeSingapore ? shopeeSingapore.sales : 0,
    alerts: {},
    warnings: []
  };

  result.malaysiaMargin = calculateGrossMargin(result.malaysiaPrice, costPrice);
  result.singaporeMargin = calculateGrossMargin(result.singaporePrice, costPrice);

  const stockValue = result.stockValue || 0;

  // A. DATA QUALITY WARNINGS — these are NOT stock alerts.
  if (product.mm) {
    result.warnings.push(`Stock: Movement Report ${product.mc} vs Inventory ${product.q}`);
  }
  if (product.bs) {
    result.warnings.push(`Batch total ≠ summary (${product.qs})`);
  }
  if (product.eg !== undefined) {
    const shopeeUnits = malaysiaUnitsSold + singaporeUnitsSold;
    result.warnings.push(`Avixo e-com deduction ${product.eg} vs Shopee ${shopeeUnits}`);
  }
  if (!costPrice) result.warnings.push('No cost price');
  if (!product.id) result.warnings.push('Not in Inventory Report');
  if ((product.c === 'Medication' || product.c === 'Vaccine') && !product.x && product.q > 0) {
    result.warnings.push('No expiry date');
  }
  if (result.clinicMargin !== null && result.clinicMargin < -50) {
    result.warnings.push('Clinic price below cost');
  }
  if ((shopeeMalaysia && !shopeeMalaysia.listed) ||
      (shopeeSingapore && !shopeeSingapore.listed)) {
    result.warnings.push('Shopee listing not found');
  }

  // B. STOCK MOVEMENT ALERTS — these three possibilities are exclusive.
  if (product.q > 0 && totalUnitsSold === 0) {
    result.alerts.nonmoving = { rm: stockValue };
  } else if (product.q > 0 && totalUnitsSold < RULES.SLOW_UNITS) {
    result.alerts.slow = { rm: stockValue };
  } else if (totalUnitsSold >= RULES.SLOW_UNITS &&
             stockCoverMonths > RULES.HIGH_MONTHS) {
    const stockAboveLimit = Math.max(
      0,
      product.q - RULES.HIGH_MONTHS * totalUnitsSold
    );
    result.alerts.high = {
      rm: costPrice ? stockAboveLimit * costPrice : 0
    };
  }

  // C. EXPIRY RISK — calculated batch by batch.
  // Keep the original calculation so existing dashboard results do not change.
  if (product.b) {
    const unitsSoldPerDay = totalUnitsSold / 30;
    let unitsAlreadyAllocated = 0;
    let upcomingExpiryCost = 0;
    let expiredUnits = 0;
    let expiredCost = 0;
    let firstExpiringBatch = null;
    let hasBatchWithinWindow = false;

    product.b.forEach(batch => {
      const expiryDate = batch[0];
      const batchQuantity = batch[1];
      if (!expiryDate) return;

      const daysRemaining = daysBetween(expiryDate, monthInfo.today);

      if (daysRemaining < 0) {
        expiredUnits += batchQuantity;
        expiredCost += batchQuantity * (costPrice || 0);
        if (!firstExpiringBatch) firstExpiringBatch = batch;
        return;
      }

      if (daysRemaining > RULES.EXPIRY_DAYS) return;

      hasBatchWithinWindow = true;
      if (!firstExpiringBatch) firstExpiringBatch = batch;

      const canSellBeforeExpiry = Math.max(
        0,
        unitsSoldPerDay * daysRemaining - unitsAlreadyAllocated
      );
      const unitsAtRisk = Math.max(
        0,
        Math.round(batchQuantity - canSellBeforeExpiry)
      );

      unitsAlreadyAllocated += Math.min(batchQuantity, canSellBeforeExpiry);
      upcomingExpiryCost += unitsAtRisk * (costPrice || 0);
    });

    if (expiredUnits > 0 || hasBatchWithinWindow) {
      result.alerts.expiry = {
        rm: expiredCost + upcomingExpiryCost,
        expQty: expiredUnits,
        first: firstExpiringBatch,
        expired: expiredUnits > 0
      };
    }
  }

  // D. LOW MARGIN — compare cost against selling prices.
  if (result.clinicMargin !== null &&
      result.clinicMargin < clinicMarginMinimum &&
      result.clinicMargin >= -50) {
    result.alerts.marginClinic = { rm: stockValue };
  }

  const malaysiaMarginTooLow = result.malaysiaMargin !== null &&
    result.malaysiaMargin < RULES.GM_ECOM;
  const singaporeMarginTooLow = result.singaporeMargin !== null &&
    result.singaporeMargin < RULES.GM_ECOM;
  if (malaysiaMarginTooLow || singaporeMarginTooLow) {
    result.alerts.marginEcom = { rm: stockValue };
  }

  // E. LOW STOCK — estimate the gross profit at risk during lead time.
  if (totalUnitsSold > 0 && stockCoverMonths < RULES.LOW_MONTHS) {
    const totalSalesRM = result.clinicSales + result.malaysiaSales + result.singaporeSales;
    const profitPerUnit = costPrice && totalSalesRM > 0
      ? Math.max(0, totalSalesRM / totalUnitsSold - costPrice)
      : 0;

    const monthsWithoutStock = Math.max(0, RULES.LEAD_MONTHS - stockCoverMonths);
    result.alerts.lowstock = {
      rm: monthsWithoutStock * totalUnitsSold * profitPerUnit
    };
  }

  return result;
}

function calculateBusinessAnalytics(products) {



    let revenue = 0;

    let estimatedCost = 0;

    let deadStockValue = 0;

    let totalStockValue = 0;

    let totalUnitsSold = 0;



    const topProducts = [];



    products.forEach(item => {



        const p = item.product;



        const clinicUnits = p.s || 0;

        const myUnits = p.my?.units || 0;

        const sgUnits = p.sg?.units || 0;



        const unitsSold = clinicUnits + myUnits + sgUnits;



        const productRevenue =

            item.clinicSales +

            item.malaysiaSales +

            item.singaporeSales;



        const productCost =

            unitsSold * (item.costPrice || 0);



        revenue += productRevenue;

        estimatedCost += productCost;

        totalStockValue += item.stockValue || 0;

        totalUnitsSold += unitsSold;



        if (p.q > 0 && unitsSold === 0) {

            deadStockValue += item.stockValue || 0;

        }



        topProducts.push({

            name: p.n,

            units: unitsSold,

            revenue: productRevenue

        });

    });



    const grossProfit = revenue - estimatedCost;



    const grossMargin = revenue > 0

        ? grossProfit / revenue * 100

        : 0;



    const stockTurnover = totalStockValue > 0

        ? estimatedCost / totalStockValue

        : 0;



    topProducts.sort((a, b) => b.revenue - a.revenue);



    return {

        revenue,

        grossProfit,

        grossMargin,

        deadStockValue,

        stockTurnover,

        totalUnitsSold,

        topProducts: topProducts.slice(0, 10),
        allProducts: topProducts

    };

}



// Top 10 table: click "Units Sold" or "Revenue" to re-rank. A second click
// flips between highest-first and lowest-first (products with no sales are skipped).
function rankTopProducts(all, sort) {
  const key = sort && sort.key === 'units' ? 'units' : 'revenue';
  const dir = sort && sort.direction === 'asc' ? 1 : -1;
  return (all || []).filter(p => (p[key] || 0) > 0)
    .sort((a, b) => dir * ((a[key] || 0) - (b[key] || 0)) || (b.revenue - a.revenue))
    .slice(0, 10);
}
function topSortHeader(key, label) {
  const on = state.topSort && state.topSort.key === key;
  const dir = on ? state.topSort.direction : 'none';
  const arrow = on ? (dir === 'asc' ? ' ▲' : ' ▼') : ' ↕';
  return `<th aria-sort="${on ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}"><button type="button" class="sortbtn top-sort${on ? ' on' : ''}" data-action="top-sort" data-value="${key}">${label}<span class="top-sort-arrow">${arrow}</span></button></th>`;
}

function renderBusinessAnalytics(products) {



    const data = calculateBusinessAnalytics(products);



    const topList = rankTopProducts(data.allProducts, state.topSort);
    const rows = topList.map((product, index) => `

        <tr>

            <td>${index + 1}</td>

            <td><button class="product-link" data-action="product" data-value="${state.analysedProducts.findIndex(item => item.product.n === product.name)}">${escapeHtml(product.name)} ↗</button></td>

            <td>${formatNumber(product.units)}</td>

            <td>${formatMoney(product.revenue)}</td>

        </tr>

    `).join('');



    return `

        <section class="panel">



            <div class="thead-bar">

                <h2>Business Analytics</h2>

                <span class="muted">${escapeHtml(state.reportLabel || state.monthData.meta.label)} performance</span>

            </div>



            <div class="ba-grid">



                <div class="ba-card">

                    <h3>Estimated Gross Profit</h3>

                    <div class="value">

                        ${formatRoundedMoney(data.grossProfit)}

                    </div>

                    <p>Revenue minus estimated product cost</p>

                </div>



                <div class="ba-card">

                    <h3>Estimated Gross Margin</h3>

                    <div class="value">

                        ${data.grossMargin.toFixed(1)}%

                    </div>

                    <p>Before fees and operating expenses</p>

                </div>



                <div class="ba-card">

                    <h3>Dead Stock Value</h3>

                    <div class="value">

                        ${state.reportProducts && state.reportLabel.includes(" to ") ? "Not comparable" : formatRoundedMoney(data.deadStockValue)}

                    </div>

                    <p>Stock with no sales this month</p>

                </div>



                <div class="ba-card">

                    <h3>Monthly Stock Turnover Proxy</h3>

                    <div class="value">

                        ${state.reportProducts && state.reportLabel.includes(" to ") ? "Not comparable" : data.stockTurnover.toFixed(2) + "x"}

                    </div>

                    <p>Estimated cost sold / ending stock value</p>

                </div>



            </div>



            <div class="thead-bar">

                <h2>Top 10 Best-Selling Products</h2>

            </div>



            <div class="scroll">

                <table class="ba-table">

                    <thead>

                        <tr>

                            <th>Rank</th>

                            <th>Product</th>

                            ${topSortHeader('units', 'Units Sold')}

                            ${topSortHeader('revenue', 'Revenue (RM)')}

                        </tr>

                    </thead>

                    <tbody>${rows}</tbody>

                </table>

            </div>



            ${state.reportProducts && state.reportLabel.includes(" to ") ? `<p class="date-summary">Stock-related KPIs and stock alerts are not comparable across different month-end snapshots.</p>` : renderBusinessInsights(data)}



        </section>

    `;

}



function renderBusinessInsights(data) {



    const insights = [];



    if (data.grossMargin < 20) {

        insights.push(

            "Estimated gross margin is below 20%. Review pricing and product costs."

        );

    }



    if (data.deadStockValue > 20000) {

        insights.push(

            "More than RM 20,000 is tied up in non-moving inventory. Review slow-selling products."

        );

    }



    if (data.stockTurnover < 0.5) {

        insights.push(

            "Monthly stock turnover proxy is below 0.5x. Review excess inventory."

        );

    }



    if (insights.length === 0) {

        insights.push(

            "No additional business review triggers were detected."

        );

    }



    return `

        <div class="thead-bar">

            <h2>Business Insights & Recommendations</h2>

        </div>



        ${insights.map(insight => `

            <div class="ba-note">

                ${escapeHtml(insight)}

            </div>

        `).join('')}



        <p class="muted" style="padding:0 20px 20px">

            These are suggested review thresholds, not approved clinic

            policies. Results are estimates based on matched data.

        </p>

    `;

}










// A product may have more than one alert, e.g. expiry + low margin.
function getProductAlerts(analysedProduct) {
  return ALERT_KEYS.filter(key => analysedProduct.alerts[key]);
}

// -----------------------------------------------------------------------
// 5. PRODUCT TABLE COLUMNS
// -----------------------------------------------------------------------
// Each column has a name, a heading, an alignment and a sorting value.
const TABLE_COLUMNS = [
  { key: 'name',   label: 'Name',     right: false, value: item => item.product.n.toLowerCase() },
  { key: 'qty',    label: 'Stock',            right: true,  value: item => item.product.q },
  { key: 'exp',    label: 'Earliest expiry',  right: false, value: item => item.product.x || null },
  { key: 'value',  label: 'Value',            right: true,  value: item => item.stockValue },
  { key: 'clinic', label: 'Clinic sold',      right: true,  value: item => item.product.s },
  { key: 'my',     label: 'MY sold',          right: true,  value: item => item.product.my ? item.product.my.units : null },
  { key: 'sg',     label: 'SG sold',          right: true,  value: item => item.product.sg ? item.product.sg.units : null },
  { key: 'use',    label: 'Units / month',    right: true,  value: item => item.totalUnitsSold },
  { key: 'cover',  label: 'Cover',            right: true,  value: item => item.stockCoverMonths },
  { key: 'cost',   label: 'Latest cost',      right: true,  value: item => item.costPrice },
  { key: 'profit', label: 'Est. profit',    right: true,  value: item => viewProfit(item) },
  { key: 'price',  label: 'Clinic price',     right: true,  value: item => item.clinicPrice },
  { key: 'myp',    label: 'Shopee MY price',  right: true,  value: item => item.malaysiaPrice },
  { key: 'sgp',    label: 'Shopee SG price',  right: true,  value: item => item.singaporePrice },
  { key: 'gm',     label: 'Clinic GM',        right: true,  value: item => item.clinicMargin },
  { key: 'mygm',   label: 'Shopee MY GM',     right: true,  value: item => item.malaysiaMargin },
  { key: 'sggm',   label: 'Shopee SG GM',     right: true,  value: item => item.singaporeMargin },
  { key: 'alerts', label: 'Alerts',           right: false, value: item => getProductAlerts(item).length }
];

// -----------------------------------------------------------------------
// 6. DASHBOARD STATE — what the user has selected
// -----------------------------------------------------------------------
// If the user clicks "Shopee Malaysia", state.view becomes "my".
// We then redraw the page using the new state.
const state = {
  availableMonths: [],
  dateMode: 'month',
  dateFrom: '',
  dateTo: '',
  dateMessage: '',
  reportProducts: null,
  reportLabel: '',
  selectedMonth: null,
  monthData: null,
  analysedProducts: [],
  view: 'all',
  category: 'all',
  selectedCard: 'all',
  searchText: '',
  displayLimit: 50,
  showWarningsOnly: false,
  sortKey: 'name',
  sortDirection: 'desc',
  topSort: { key: 'revenue', direction: 'desc' },
  rulesOpen: false,
  filteredProducts: []
};

// -----------------------------------------------------------------------
// 7. LOAD THE MONTHLY DATA FILES
// -----------------------------------------------------------------------
// We load JavaScript files, not fetch(JSON). This means index.html also works
// when opened directly by double-clicking, provided the data/ files exist.
window.DASHBOARD_DATA = window.DASHBOARD_DATA || {};

function showError(message) {
  document.getElementById('app').innerHTML = `
    <div class="panel" style="padding:32px">${escapeHtml(message)}</div>
  `;
}

function loadJavaScriptFile(filePath) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = filePath;
    script.onload = resolve;
    script.onerror = () => reject(new Error(
      `Could not load ${filePath}. Keep index.html next to the data folder.`
    ));
    document.head.appendChild(script);
  });
}

// Original processed months (output of process_month.py). Supabase first, original files as fallback.
async function fetchApiJson(url) {
  const response = await fetch(url, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } });
  if (!response.ok) throw new Error('API ' + response.status);
  return response.json();
}
async function loadSavedMonthList() {
  try {
    const list = await fetchApiJson('/api/dashboard/months');
    if (Array.isArray(list) && list.length) { window.DASHBOARD_SAVED_SOURCE = 'supabase'; return list; }
  } catch (e) { /* fall back to the original file below */ }
  window.DASHBOARD_SAVED_SOURCE = 'files';
  try { await loadJavaScriptFile('data/months.js'); } catch (e) { console.warn('Legacy saved-month list unavailable:', e.message); return []; }
  return window.DASHBOARD_MONTHS || [];
}
async function ensureMonthLoaded(key) {
  if (window.DASHBOARD_DATA[key]) return;
  if (window.DASHBOARD_SAVED_SOURCE === 'supabase') {
    window.DASHBOARD_DATA[key] = await fetchApiJson('/api/dashboard/' + encodeURIComponent(key));
  } else {
    await loadJavaScriptFile(`data/${key}.js`);
  }
}

// Supabase bridge: only reporting months from actual monthly sales/movement.
// Legacy JSON is still used for the months where it exists. All other months
// render the Supabase-backed monthly detail without fabricating stock history.
async function fetchMonthlyJSON(path) {
  const response = await fetch(path, {credentials:'same-origin', cache:'no-store'});
  if (response.status === 401) { location.href = '/login'; throw Error('Please sign in again.'); }
  let payload;
  try { payload = await response.json(); } catch { throw Error('Unexpected response from monthly API.'); }
  if (!response.ok) throw Error(payload.error || `Monthly API error ${response.status}`);
  return payload;
}

function liveNum(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}
function liveQty(value) { const n = liveNum(value); return n === null ? '—' : n.toLocaleString('en-MY',{maximumFractionDigits:2}); }
function liveMoney(value, currency='MYR') {
  const n = liveNum(value);
  if (n === null) return 'Unavailable';
  return `${currency==='SGD'?'S$':'RM '}${n.toLocaleString('en-MY',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
function availableChannel(month, channel) {
  return (month.monthly||[]).some(row => row.channel===channel);
}
// The API returns snapshot_date only when this month's own month-end Avixo inventory
// report (month-end or the day after) has been uploaded. Otherwise stock and prices
// are shown as "No data" instead of presenting a different date's snapshot.
function liveStockApplies(data) {
  return Boolean(data && data.snapshot_date);
}
function liveStockText(data) {
  return data.snapshot_date
    ? `Stock, cost and Clinic prices are from the <strong>${escapeHtml(data.snapshot_date)}</strong> month-end inventory report for ${escapeHtml(data.month_label)}.`
    : `No month-end Avixo inventory report has been uploaded for ${escapeHtml(data.month_label)}, so stock, cost and Clinic prices show <strong>No data</strong>. Sales figures are real ${escapeHtml(data.month_label)} data. Upload that month's Avixo Inventory Report on the Upload Data page to fill them in.`;
}
/**
 * Match the legacy nine-card layout for live Supabase months, without
 * inventing historical inventory risk metrics from a later snapshot.
 * Unlike the full legacy dashboard, these cards are informational only.
 */
function renderLiveNineCards(data) {
  const rows = data.monthly || [];
  const byChannel = new Map(rows.map(row => [row.channel, row]));
  const month = data.month_label || data.month || 'selected month';
  const dated = data.snapshot_date ? `as of ${data.snapshot_date}` : 'date unavailable';
  const stockOk = liveStockApplies(data);
  const priced = (data.products || []).filter(p =>
    liveNum(p.clinic_price_rm) > 0 &&
    liveNum(p.latest_cost_rm) > 0 &&
    liveNum(p.stock_quantity) !== null
  );
  const stocked = (data.products || []).filter(p => liveNum(p.stock_quantity) !== null);
  const stockValue = stocked.reduce((sum, p) => sum + (liveNum(p.stock_value_rm) || 0), 0);
  const snapshotValueAvailable = data.snapshot_date && stocked.some(p => liveNum(p.stock_value_rm) !== null);
  const clinicLowMargin = priced.filter(p => {
    const margin = (liveNum(p.clinic_price_rm) - liveNum(p.latest_cost_rm)) /
                   liveNum(p.clinic_price_rm) * 100;
    const threshold = p.category === 'Vaccine' ? RULES.GM_CLINIC_VACCINE : RULES.GM_CLINIC;
    return margin < threshold;
  });
  const clinicLowValue = clinicLowMargin.reduce((sum, p) => sum + (liveNum(p.stock_value_rm) || 0), 0);

  const channelText = (name, currency) => {
    const r = byChannel.get(name);
    return r ? `${name}: ${liveMoney(r.revenue,currency)} (${liveQty(r.units_sold)} units)`
             : `${name}: No report`;
  };
  const display = {
    all: {
      amount: (stockOk && snapshotValueAvailable) ? liveMoney(stockValue, 'MYR') : 'No data',
      note: stockOk ? `Month-end stock value at cost · ${dated}` : 'No month-end stock snapshot for this month',
      footer: stockOk ? `${stocked.length} products with snapshot` : 'Upload this month\'s Avixo inventory report'
    },
    sales: {
      amount: 'By channel',
      note: [channelText('Clinic','MYR'),channelText('Shopee MY','MYR'),channelText('Shopee SG','SGD')].join(' · '),
      footer: `Sales/movement reports for ${month} · No FX conversion`
    },
    nonmoving: {amount:'No data',note:'Requires complete monthly sales matching and a corresponding stock snapshot.',footer:'Cannot verify historical non-moving stock'},
    slow: {amount:'No data',note:'Requires complete monthly unit sales for stock on that reporting date.',footer:'No verified historical classification'},
    high: {amount:'No data',note:'Needs month-specific stock cover, not a later stock snapshot.',footer:'No verified historical classification'},
    expiry: {amount:'No data',note:'Requires dated expiry batches and matching stock quantities.',footer:'No verified historical expiry risk'},
    marginClinic: {
      amount: (stockOk && priced.length) ? liveMoney(clinicLowValue,'MYR') : 'No data',
      note: (stockOk && priced.length) ? `Stock value affected · prices/cost ${dated}` : 'No month-end price and cost data for this month',
      footer: (stockOk && priced.length) ? `${clinicLowMargin.length} products` : 'Not calculated from a later snapshot'
    },
    marginEcom: {amount:'No data',note:'Historical listing prices, fees and SG exchange rates are incomplete.',footer:'Do not calculate from mixed currencies'},
    lowstock: {amount:'No data',note:'Requires same-date inventory and demand to estimate stockout risk.',footer:'No verified historical risk calculation'}
  };
  return `<section class="cards live-month-nine-cards" aria-label="Monthly summary cards">
    ${CARD_ORDER.map(key => {
      const info = CARD_INFO[key];
      const card = display[key];
      return `<article class="card live-month-summary-card" title="${escapeHtml(card.footer)}">
        <div class="live-month-card-heading"><span class="dot" style="background:${info.color}"></span><strong>${escapeHtml(info.label)}</strong></div>
        <div class="num big">${escapeHtml(card.amount)}</div>
        <div class="sub">${escapeHtml(card.note)}</div>
        <div class="num foot">${escapeHtml(card.footer)}</div>
      </article>`;
    }).join('')}
  </section>`;
}

function renderLiveMonth() {
  // Load the styling only when the Supabase read-only month view is displayed.
  // No changes to the user's existing HTML or navigation are necessary.
  if (!document.querySelector('link[data-monthly-live-css]')) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/assets/css/monthly-live.css';
    link.setAttribute('data-monthly-live-css', '');
    document.head.appendChild(link);
  }
  const data = state.liveMonth;
  if (!data) return;
  const dropdown = [...state.availableMonths].sort((a,b)=>b.key.localeCompare(a.key))
    .map(m=>`<option value="${escapeHtml(m.key)}" ${m.key===data.month?'selected':''}>${escapeHtml(m.label)}</option>`).join('');
  const mode = state.liveChannel || 'all';
  const category = state.liveCategory || 'all';
  const search = (state.liveSearch || '').toLowerCase();
  const categories = [...new Set((data.products||[]).map(p=>p.category||'Uncategorised'))].sort();
  const reports={clinic:availableChannel(data,'Clinic'),my:availableChannel(data,'Shopee MY'),sg:availableChannel(data,'Shopee SG')};
  const candidates=(data.products||[]).filter(p=>{
    if (category!=='all' && (p.category||'Uncategorised')!==category) return false;
    if (search && !(`${p.name||''} ${p.avixo_id||''}`.toLowerCase().includes(search))) return false;
    if (mode==='my' && !(p.my_sold>0)) return false;
    if (mode==='sg' && !(p.sg_sold>0)) return false;
    const stockOk = liveStockApplies(data);
    if (mode==='clinic' && !(p.clinic_sold>0 || (stockOk && (p.stock_quantity||0)>0))) return false;
    return (stockOk && (p.stock_quantity||0)>0) || (p.clinic_sold||0)>0 || (p.my_sold||0)>0 || (p.sg_sold||0)>0;
  });
  candidates.sort((a,b)=>a.name.localeCompare(b.name,undefined,{sensitivity:'base'}));
  const shown = candidates.slice(0, 600);
  const channelCell=(value,exists)=>exists?liveQty(value):'—';
  const salesHeader = mode==='my'?'MY units':mode==='sg'?'SG units':mode==='clinic'?'Clinic units':'Units sold';
  const salesCell=(p)=>mode==='my'?channelCell(p.my_sold,reports.my):mode==='sg'?channelCell(p.sg_sold,reports.sg):mode==='clinic'?channelCell(p.clinic_sold,reports.clinic):[
    reports.clinic?`Clinic ${liveQty(p.clinic_sold)}`:'Clinic —',
    reports.my?`MY ${liveQty(p.my_sold)}`:'MY —',
    reports.sg?`SG ${liveQty(p.sg_sold)}`:'SG —'
  ].join(' · ');
  const table = shown.map(p=>`<tr>
    <td><strong>${escapeHtml(p.name)}</strong><small>ID: ${escapeHtml(p.avixo_id??'—')} · ${escapeHtml(p.category||'Uncategorised')}</small></td>
    <td data-label="Stock (month-end)">${liveStockApplies(data)?liveQty(p.stock_quantity):'No data'}</td>
    <td data-label="${escapeHtml(salesHeader)}">${salesCell(p)}</td>
    <td data-label="Clinic price">${liveStockApplies(data)?liveMoney(p.clinic_price_rm,'MYR'):'No data'}</td>
    <td data-label="MY sales (MYR)">${mode==='clinic'||mode==='sg'?'—':reports.my?liveMoney(p.my_revenue_myr,'MYR'):'—'}</td>
    <td data-label="SG sales (SGD)">${mode==='clinic'||mode==='my'?'—':reports.sg?liveMoney(p.sg_revenue_sgd,'SGD'):'—'}</td>
  </tr>`).join('');
  const unknown = data.unmapped_shopee||[];
  const unknownUnits = unknown.reduce((total,x)=>total+(liveNum(x.units)||0),0);
  const inventoryNotice = liveStockText(data);
  const clinicRef = data.clinic_price_reference_dates?.length
    ? `Clinic estimated-revenue price reference dates: ${data.clinic_price_reference_dates.map(escapeHtml).join(', ')}.`
    : 'Clinic selling-price reference is not available for this month.';
  const viewOptions=[['all','All'],['clinic','Clinic'],['my','Shopee MY'],['sg','Shopee SG']];
  document.getElementById('asof').textContent = `Supabase reports · ${data.month_label}`;
  document.getElementById('app').innerHTML = `
  <section class="panel live-month-filter"><div class="live-month-row">
     <label>Reporting month<select id="report-month">${dropdown}</select></label>
     <div class="live-month-source">Live monthly reports · Supabase</div></div>
     <p class="live-month-note">${inventoryNotice}</p>${state.legacyMonthKeys?.has(data.month)?`<p class="live-month-note"><button class="btn" type="button" data-action="month" data-value="${escapeHtml(data.month)}">Open original saved dashboard for ${escapeHtml(data.month_label)}</button></p>`:''}</section>
  ${renderLiveNineCards(data)}
  <section class="panel live-month-panel"><h2>Products · ${escapeHtml(data.month_label)}</h2>
    <p class="live-month-note">Monthly sales are for the selected month. Clinic revenue is estimated; MYR and SGD are never added together. ${clinicRef}</p>
    <div class="live-month-filters"><label>View <select id="live-month-channel">${viewOptions.map(([k,name])=>`<option value="${k}" ${mode===k?'selected':''}>${name}</option>`).join('')}</select></label>
    <label>Category <select id="live-month-category"><option value="all">All categories</option>${categories.map(c=>`<option value="${escapeHtml(c)}" ${category===c?'selected':''}>${escapeHtml(c)}</option>`).join('')}</select></label>
    <label>Search <input id="live-month-search" type="search" value="${escapeHtml(state.liveSearch||'')}" placeholder="Product name or Avixo ID"></label></div>
    <p class="live-month-note">${shown.length} of ${candidates.length} products shown. ${unknown.length} unmapped Shopee listing groups (${liveQty(unknownUnits)} units) remain in channel totals, but cannot be assigned to a verified Avixo product.</p>
    <div class="live-month-table-wrap"><table class="live-month-table"><thead><tr><th>Product · ID · Category</th><th>Stock (month-end)</th><th>${escapeHtml(salesHeader)}</th><th>Clinic price</th><th>MY revenue (RM)</th><th>SG revenue (S$)</th></tr></thead><tbody>${table||'<tr><td colspan="6">No matching products for this filter.</td></tr>'}</tbody></table></div>
    <p class="live-month-note"><a href="/bi.html">View full Live Sales analysis</a> · Source: cleaned monthly Shopee sales and Clinic movements. This is a read-only monthly view, not a reconstructed historical inventory snapshot.</p>
  </section>`;
  document.querySelector(`[data-nav="${document.body.dataset.page}"]`)?.classList.add('active');
}

async function loadSupabaseMonth(monthKey) {
  const detail = await fetchMonthlyJSON('/api/monthly/detail?month='+encodeURIComponent(monthKey));
  state.liveMonth = detail;
  state.monthData = null;
  state.selectedMonth = monthKey;
  state.dateMode = 'month';
  renderLiveMonth();
}

async function loadMonth(monthKey) {
  const localMonth = state.legacyMonthKeys?.has(monthKey);
  // No JSON file? Read real Supabase monthly rows instead of requesting a missing script.
  if (!localMonth && state.supabaseMonthKeys?.has(monthKey)) {
    await loadSupabaseMonth(monthKey);
    return;
  }
  await ensureMonthLoaded(monthKey);
  const newMonth = window.DASHBOARD_DATA[monthKey];
  if (!newMonth || !Array.isArray(newMonth.products)) {
    throw new Error(`Missing dashboard data for ${monthKey}`);
  }
  state.liveMonth = null;
  state.selectedMonth = monthKey;
  state.monthData = newMonth;
  state.analysedProducts = newMonth.products.map(product =>
    analyseProduct(product, newMonth.meta)
  );
  state.dateMode = 'month';
  state.reportProducts = null;
  state.reportLabel = '';
  state.dateMessage = '';
  renderDashboard();
}

async function startDashboard() {
  try {
    const localMonths = await loadSavedMonthList();
    state.legacyMonthKeys = new Set(localMonths.map(m=>m.key));
    state.supabaseMonthKeys = new Set();
    const months = new Map(localMonths.map(m=>[m.key,m]));
    try {
      const live = await fetchMonthlyJSON('/api/monthly/months');
      for (const m of live.months||[]) {
        state.supabaseMonthKeys.add(m.key);
        months.set(m.key,m);
      }
    } catch (e) {
      console.warn('Supabase month list unavailable. Local data only:',e.message);
      if (!months.size) throw e;
    }
    state.availableMonths = [...months.values()].sort((a,b)=>b.key.localeCompare(a.key));
    if (!state.availableMonths.length) throw new Error('No monthly reports are available.');
    const latest = state.availableMonths[0];
    await loadMonth(latest.key);
  } catch (error) {
    showError('Could not load reporting months: ' + error.message);
  }
}

// -----------------------------------------------------------------------
// 8. FILTER AND SORT THE PRODUCTS
// -----------------------------------------------------------------------
function getProductsInSelectedView() {
  return state.analysedProducts.filter(item => {
    const product = item.product;

    // "Clinic" here means products that are NOT in either Shopee dataset,
    // exactly as in the original code (not all products sold by the clinic).
    // Clinic shares inventory with Shopee: do not hide products also listed online.
    // All inventory products remain available in Clinic view.
    if (state.view === 'my' && !product.my) return false;
    if (state.view === 'sg' && !product.sg) return false;
    if (state.category !== 'all' && product.c !== state.category) return false;
    return true;
  });
}

function getProductsForTable(productsInView) {
  const search = state.searchText.toLowerCase();

  return productsInView.filter(item => {
    const product = item.product;

    // Search using product name or ID.
    const nameMatches = product.n.toLowerCase().includes(search);
    const idMatches = String(product.id || '').includes(search);
    if (search && !nameMatches && !idMatches) return false;

    if (state.showWarningsOnly && item.warnings.length === 0) return false;

    if (state.selectedCard === 'all') {
      return product.q > 0 || item.totalUnitsSold > 0;
    }
    if (state.selectedCard === 'sales') return item.totalUnitsSold > 0;

    return Boolean(item.alerts[state.selectedCard]);
  });
}

function sortTableProducts(products) {
  // Sort using the value callback defined by each visible inventory column.
  // Date strings are ISO YYYY-MM-DD, so lexical order = chronological order.
  // Missing values (e.g. unlisted Shopee prices or no expiry) always go last.
  const activeColumn = TABLE_COLUMNS.find(column => column.key === state.sortKey) || TABLE_COLUMNS[0];
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  const compareValues = (left, right) => {
    const leftMissing = left == null || left === '' || (typeof left === 'number' && !Number.isFinite(left));
    const rightMissing = right == null || right === '' || (typeof right === 'number' && !Number.isFinite(right));
    if (leftMissing && rightMissing) return 0;
    if (leftMissing) return 1;
    if (rightMissing) return -1;
    if (typeof left === 'number' && typeof right === 'number') {
      return (left - right) * direction;
    }
    return String(left).localeCompare(String(right), undefined, {numeric:true, sensitivity:'base'}) * direction;
  };
  products.sort((a, b) => {
    const result = compareValues(activeColumn.value(a), activeColumn.value(b));
    return result || a.product.n.localeCompare(b.product.n, undefined, {numeric:true, sensitivity:'base'});
  });
  return `${activeColumn.label}, ${state.sortDirection === 'asc' ? 'ascending ↑' : 'descending ↓'}`;
}

function renderSegmentedFilter(label, action, options, selectedValue) {
  const buttons = options.map(option => {
    const value = option[0];
    const text = option[1];
    const selected = value === selectedValue;
    return `<button data-action="${action}" data-value="${escapeHtml(value)}"
                    aria-pressed="${selected}">${escapeHtml(text)}</button>`;
  }).join('');

  return `
    <div class="fg">
      <span class="lbl">${label}</span>
      <div class="seg" role="group" aria-label="${label}">${buttons}</div>
    </div>
  `;
}


function allMonthKeys() {
  return state.availableMonths.map(m => m.key).sort();
}
async function readMonth(key) {
  await ensureMonthLoaded(key);
  return window.DASHBOARD_DATA[key];
}
function monthFullyInside(key, from, to) {
  const start = key + '-01';
  const end = new Date(Date.UTC(Number(key.slice(0,4)), Number(key.slice(5,7)), 0)).toISOString().slice(0,10);
  return start >= from && end <= to;
}
async function applyReportDates() {
  const keys = allMonthKeys();
  const page = document.body.dataset.page;
  if (state.dateMode === 'mtd') {
    // Date-filtered units/revenue are unavailable in source's monthly aggregates.
    state.reportProducts = null;
    state.dateMessage = 'Month-to-date sales are unavailable: this inventory dashboard has monthly report totals, not dated transactions. Showing the latest saved inventory snapshot and its original full-month figures for reference only.';
    renderDashboard(); return;
  }
  if (state.dateMode === 'month') {
    await loadMonth(state.selectedMonth || keys[keys.length-1]);
    return;
  }
  let matching = keys;
  if (state.dateMode === 'range') {
    if (!state.dateFrom || !state.dateTo || state.dateFrom > state.dateTo) {
      state.dateMessage = 'Choose a valid From and To date.';
      renderDashboard(); return;
    }
    matching = keys.filter(k => monthFullyInside(k,state.dateFrom,state.dateTo));
  }
  if (!matching.length) {
    state.reportProducts = [];
    state.dateMessage = 'No complete processed months fall entirely inside this range. Exact mid-month sales cannot be calculated from monthly aggregates.';
    renderDashboard();return;
  }
  const last = matching[matching.length-1];
  const recent = await readMonth(last);
  state.monthData = recent;
  state.selectedMonth = last;
  state.analysedProducts = recent.products.map(p=>analyseProduct(p,recent.meta));
  state.reportLabel = matching.length === 1 ? recent.meta.label : `${matching[0]} to ${last}`;
  if (page === 'analytics') {
    const chunks = await Promise.all(matching.map(readMonth));
    state.reportProducts = chunks.flatMap(data => data.products.map(p=>analyseProduct(p,data.meta)));
    state.dateMessage = matching.length === 1 ? 'One complete saved month is included.' : `${matching.length} complete saved months combined. Revenue and units are summed; inventory snapshots are not summed.`;
  } else {
    state.reportProducts = null;
    state.dateMessage = `Showing the latest available stock snapshot (${recent.meta.label}). Stock snapshots from separate months are never added together.`;
  }
  renderDashboard();
}
function renderDateControls() {
  if (!['analytics','inventory'].includes(document.body.dataset.page)) return '';
  const months=[...state.availableMonths].sort((a,b)=>b.key.localeCompare(a.key));
  const opts=months.map(m=>`<option value="${escapeHtml(m.key)}" ${m.key===state.selectedMonth?'selected':''}>${escapeHtml(m.label)}</option>`).join('');
  const legacy = state.legacyMonthKeys?.has(state.selectedMonth);
  const liveAvailable = state.supabaseMonthKeys?.has(state.selectedMonth);
  const sourceNote = legacy ? 'This month uses the saved legacy JSON report. To see newer Supabase sales for this month, choose Live data.' : 'This month is loaded directly from Supabase.';
  const liveButton = legacy && liveAvailable ? `<button type="button" class="btn" data-action="live-month" data-value="${escapeHtml(state.selectedMonth)}">View live Supabase data</button>` : '';
  return `<section class="panel" aria-label="Reporting month filter">
    <div class="date-controls simple-month-controls"><label>Reporting month<select id="report-month">${opts}</select></label>${liveButton}</div>
    <div class="date-summary">${months.length} available saved month(s). ${escapeHtml(sourceNote)}</div>
  </section>`;
}

function renderFilters() {
  const monthButtons = state.availableMonths.map(month => `
    <button data-action="month" data-value="${escapeHtml(month.key)}"
            aria-pressed="${month.key === state.selectedMonth}">${escapeHtml(month.label)}</button>
  `).join('');

  return `
    <section class="panel filters" aria-label="Filters">
      ${document.body.dataset.page === 'analytics' ? '' : renderSegmentedFilter('View', 'view', [
        ['all', 'All'], ['clinic', 'Clinic'],
        ['my', 'Shopee Malaysia'], ['sg', 'Shopee Singapore']
      ], state.view)}
      ${renderSegmentedFilter('Category', 'category', [
        ['all', 'All'], ['Medication', 'Medication'], ['Item', 'Items'],
        ['Vaccine', 'Vaccines'], ['Consumable', 'Consumables']
      ], state.category)}
    </section>
  `;
}

function renderExpiredBanner(monthInfo) {
  const expiredDescriptions = [];
  let totalExpiredValue = 0;

  // This warning includes the whole dataset, exactly like the original.
  state.analysedProducts.forEach(item => {
    const expiry = item.alerts.expiry;
    if (!expiry || !expiry.expired) return;

    expiredDescriptions.push(
      `${escapeHtml(item.product.n)} (${expiry.expQty}, ${formatDate(expiry.first[0])})`
    );
    totalExpiredValue += expiry.expQty * (item.costPrice || 0);
  });

  if (expiredDescriptions.length === 0) return '';

  return `
    <div class="banner red">
      <strong>Expired stock on ${formatDate(monthInfo.today)} ·
      ${expiredDescriptions.length} batches (${formatRoundedMoney(totalExpiredValue)}):</strong>
      ${expiredDescriptions.join('; ')}. Quarantine and dispose.
    </div>
  `;
}

function renderDataQualityBanner(monthInfo) {
  let mismatchProducts = 0;
  let mismatchValue = 0;
  let ecomMismatchProducts = 0;
  let malaysiaUnits = 0;
  let malaysiaSales = 0;
  let singaporeUnits = 0;
  let singaporeSales = 0;

  state.analysedProducts.forEach(item => {
    const product = item.product;

    if (product.mm) {
      mismatchProducts++;
      mismatchValue += Math.abs(product.mc - product.q) * (item.costPrice || 0);
    }
    if (product.eg !== undefined) ecomMismatchProducts++;
    if (product.my) {
      malaysiaUnits += product.my.units;
      malaysiaSales += product.my.sales;
    }
    if (product.sg) {
      singaporeUnits += product.sg.units;
      singaporeSales += product.sg.sales;
    }
  });

  const malaysiaMatchPercent = monthInfo.myFileSales
    ? malaysiaSales / monthInfo.myFileSales * 100
    : 0;
  const singaporeMatchPercent = monthInfo.sgFileSalesSGD
    ? singaporeSales / (monthInfo.sgFileSalesSGD * monthInfo.fx) * 100
    : 0;

  return `
    <div class="banner amber">
      <strong>Data check:</strong>
      Shopee sales matched to Avixo products:
      MY ${malaysiaMatchPercent.toFixed(1)}%
      (${formatNumber(malaysiaUnits)} of ${formatNumber(monthInfo.myFileUnits)} units),
      SG ${singaporeMatchPercent.toFixed(1)}%
      (${formatNumber(singaporeUnits)} of ${formatNumber(monthInfo.sgFileUnits)} units).
      ${mismatchProducts} products differ by more than 5 units between the Movement
      Report closing and the Inventory Report, ${formatRoundedMoney(mismatchValue)}
      at cost; the Inventory Report is used.
      ${ecomMismatchProducts} products show Avixo e-commerce deductions that differ
      from Shopee units sold. All are marked ⚑.
    </div>
  `;
}

function calculateCardSummary(cardKey, productsInView) {
  let productCount = 0;
  let amount = 0;
  let description = CARD_INFO[cardKey].sub;
  let footer = '';

  if (cardKey === 'all') {
    productsInView.forEach(item => {
      if (item.product.q > 0 || item.totalUnitsSold > 0) {
        productCount++;
        amount += item.stockValue || 0;
      }
    });
  } else if (cardKey === 'sales') {
    let clinicUnits = 0;
    let malaysiaUnits = 0;
    let singaporeUnits = 0;
    let clinicAmount = 0;
    let malaysiaAmount = 0;
    let singaporeAmount = 0;

    productsInView.forEach(item => {
      clinicUnits += item.product.s || 0;
      clinicAmount += item.clinicSales;
      if (item.product.my) {
        malaysiaUnits += item.product.my.units;
        malaysiaAmount += item.product.my.sales;
      }
      if (item.product.sg) {
        singaporeUnits += item.product.sg.units;
        singaporeAmount += item.product.sg.sales;
      }
    });

    if (state.view === 'my') {
      amount = malaysiaAmount;
      description = 'Shopee Malaysia';
      footer = `${formatNumber(malaysiaUnits)} units`;
    } else if (state.view === 'sg') {
      amount = singaporeAmount;
      description = 'Shopee Singapore (in RM)';
      const sgdTotal = formatSgd(singaporeAmount);
      footer = `${formatNumber(singaporeUnits)} units` + (sgdTotal ? ` · ${sgdTotal} (SGD 1 = RM ${singaporeRate()})` : '');
    } else if (state.view === 'clinic') {
      amount = clinicAmount;
      description = 'Clinic (units × clinic price)';
      footer = `${formatNumber(clinicUnits)} units`;
    } else {
      amount = clinicAmount + malaysiaAmount + singaporeAmount;
      description = `Clinic ${formatRoundedMoney(clinicAmount)} · MY ${formatRoundedMoney(malaysiaAmount)} · SG ${formatRoundedMoney(singaporeAmount)}`;
      footer = `${formatNumber(clinicUnits + malaysiaUnits + singaporeUnits)} units · ${formatNumber(clinicUnits)} clinic · ${formatNumber(malaysiaUnits)} MY · ${formatNumber(singaporeUnits)} SG`;
    }
  } else {
    productsInView.forEach(item => {
      if (item.alerts[cardKey]) {
        productCount++;
        amount += item.alerts[cardKey].rm;
      }
    });
  }

  if (!footer) {
    footer = `${productCount} ${productCount === 1 ? 'product' : 'products'}`;
  }
  return { amount, description, footer };
}

function renderCards(productsInView) {
  const cards = CARD_ORDER.map(cardKey => {
    const info = CARD_INFO[cardKey];
    const summary = calculateCardSummary(cardKey, productsInView);
    const selected = state.selectedCard === cardKey;
    const activeStyle = selected
      ? `border-color:${info.color};box-shadow:0 2px 10px rgba(23,32,29,.08)`
      : '';
    const dotStyle = `background:${info.color}${cardKey === 'all' ? ';border-radius:2px' : ''}`;

    return `
      <button class="card" data-action="card" data-value="${cardKey}"
              aria-pressed="${selected}" style="${activeStyle}">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="dot" style="${dotStyle}"></span>
          <span style="font-size:14px;font-weight:600">${info.label}</span>
        </div>
        <div class="num big">${formatRoundedMoney(summary.amount)}</div>
        <div class="sub">${escapeHtml(summary.description)}</div>
        <div class="num foot">${summary.footer}</div>
      </button>
    `;
  }).join('');

  return `<section class="cards" aria-label="Alert views">${cards}</section>`;
}

// ----- Helpers for ONE table row -----
function renderShopeeUnits(channel) {
  if (!channel) return '<div class="num r muted">Not listed</div>';
  return `<div class="num r" style="font-size:14px;color:#6B3FA0">${formatNumber(channel.units)}</div>`;
}

function renderShopeePrice(channel, price, showSgd = false) {
  if (!channel) return '<div class="num r muted">Not listed</div>';
  if (!price) return '<div class="num r muted">No price</div>';
  const sgd = showSgd ? formatSgd(price) : null;
  return `<div class="num r" style="font-size:13px">${formatMoney(price)}${sgd ? `<span class="sub-currency">${sgd}</span>` : ''}</div>`;
}

function renderMarginCell(margin, minimum, isListed) {
  if (!isListed) return '<div class="num r muted">Not listed</div>';
  if (margin == null) return '<div class="num r muted">n/a</div>';
  const warningClass = margin < minimum ? ' bad' : '';
  return `<div class="num r${warningClass}" style="font-size:14px">${formatPercent(margin)}</div>`;
}

function inventoryColumnsForView() {
  // Keep all applicable metrics visible: no "More" or "Details" button.
  // All channels: all figures; channel views: only that channel's sales,
  // prices and margins, while keeping shared stock / cost / expiry fields.
  const views = {
    all: ['name','qty','exp','value','clinic','my','sg','use','cover','cost','profit','price','myp','sgp','gm','mygm','sggm','alerts'],
    clinic: ['name','qty','exp','value','clinic','use','cover','cost','profit','price','gm','alerts'],
    my: ['name','qty','exp','value','my','use','cover','cost','profit','myp','mygm','alerts'],
    sg: ['name','qty','exp','value','sg','use','cover','cost','profit','sgp','sggm','alerts']
  };
  const keys = views[state.view] || views.all;
  return keys.map(key => TABLE_COLUMNS.find(column => column.key === key));
}
function inventoryRowTemplate() {
  // Identical, fractional tracks for headings AND product rows.
  // The grid always stays at 100% width (no minimum 1990px table).
  const widths = {
    name:3.85,qty:.65,exp:1.20,value:1.18,clinic:.60,my:.55,sg:.55,
    use:.70,cover:.66,cost:.95,profit:.95,price:.95,myp:.95,sgp:.95,
    gm:.70,mygm:.70,sggm:.70,alerts:1.15
  };
  return inventoryColumnsForView().map(col => `minmax(0,${widths[col.key]}fr)`).join(' ');
}
function inventoryGridStyle() {
  return `grid-template-columns:${inventoryRowTemplate()};width:100%;min-width:0;`;
}
function renderProductRow(item) {
  const product = item.product;
  const activeAlerts = getProductAlerts(item);

  // Show which Shopee shops have this product.
  const shopeeMarkets = [
    product.my ? 'MY' : null,
    product.sg ? 'SG' : null
  ].filter(Boolean).join(' + ');

  let extraTags = shopeeMarkets
    ? makeTag('Shopee ' + shopeeMarkets, '#EFE7F8', '#4F2C7A')
    : '';
  item.warnings.forEach(message => {
    extraTags += makeTag('⚑ ' + message, '#FFF1D9', '#6E3F00');
  });

  let coverHtml = '<div class="num r" style="color:#4F5A55">No sales</div>';
  if (item.stockCoverMonths != null) {
    const isLow = item.stockCoverMonths < RULES.LOW_MONTHS;
    const isHigh = item.stockCoverMonths > RULES.HIGH_MONTHS;
    const style = isLow
      ? 'color:#B35400;font-weight:600'
      : (isHigh ? 'color:#1F5FA8;font-weight:600' : '');
    coverHtml = `<div class="num r" style="${style}">${formatNumber(item.stockCoverMonths, 1)} mo</div>`;
  }

  const expiryAlert = item.alerts.expiry;
  let expiryHtml = '<div style="font-size:13px;color:#4F5A55;font-style:italic">Unavailable</div>';
  if (product.x) {
    const color = expiryAlert && expiryAlert.expired
      ? 'color:#7E1A22;font-weight:600'
      : (expiryAlert ? 'color:#A3262E;font-weight:600' : '');
    expiryHtml = `<div class="num" style="font-size:13px;${color}">${formatDate(product.x)}</div>`;
  }

  const alertTags = activeAlerts.length > 0
    ? activeAlerts.map(key => {
        const title = CARD_INFO[key].label +
          (key === 'expiry' && item.alerts.expiry.expired ? ' · expired' : '');
        return makeTag(title, BADGE[key][0], BADGE[key][1]);
      }).join(' ')
    : makeTag('OK', '#E0F1E7', '#1B6340');

  const cells = {
    name: `<div class="inventory-product-identity">
      <button class="product-link" data-action="product" data-value="${state.analysedProducts.indexOf(item)}" title="Open product analytics">${escapeHtml(product.n)} ↗</button>
      <div class="inventory-product-meta"><span>ID: ${product.id == null ? '—' : escapeHtml(product.id)}</span><span>${escapeHtml(product.c || 'Uncategorised')}</span></div>
    </div>`,
    qty: `<span class="num r">${formatNumber(product.q)}</span>`,
    exp: expiryHtml,
    value: `<span class="num r">${formatMoney(item.stockValue)}</span>`,
    clinic: `<span class="num r">${formatNumber(product.s || 0)}</span>`,
    my: renderShopeeUnits(product.my),
    sg: renderShopeeUnits(product.sg),
    use: `<span class="num r">${formatNumber(state.view === 'clinic' ? (product.s||0) : state.view === 'my' ? (product.my?.units||0) : state.view === 'sg' ? (product.sg?.units||0) : item.totalUnitsSold)}</span>`,
    cover: coverHtml,
    cost: `<span class="num r">${formatMoney(item.costPrice)}</span>`,
    profit: `<span class="num r${viewProfit(item) != null && viewProfit(item) < 0 ? ' calc-neg' : ''}">${viewProfit(item) == null ? 'n/a' : formatMoney(viewProfit(item))}</span>`,
    price: `<span class="num r">${formatMoney(item.clinicPrice)}</span>`,
    myp: renderShopeePrice(product.my,item.malaysiaPrice),
    sgp: renderShopeePrice(product.sg,item.singaporePrice,true),
    gm: renderMarginCell(item.clinicMargin,item.clinicMarginMinimum,true),
    mygm: renderMarginCell(item.malaysiaMargin,RULES.GM_ECOM,Boolean(product.my)),
    sggm: renderMarginCell(item.singaporeMargin,RULES.GM_ECOM,Boolean(product.sg)),
    alerts: `<div style="display:flex;flex-wrap:wrap;gap:4px">${alertTags}${extraTags}</div>`
  };
  return `<div class="trow" style="${inventoryGridStyle()}">${inventoryColumnsForView().map(c=>`<div class="inventory-cell${c.key === 'name' ? ' inventory-cell-name' : ''}" data-label="${escapeHtml(c.label)}">${cells[c.key]??'—'}</div>`).join('')}</div>`;
}

function renderTableHeading() {
  // Every visible column has a sortable heading with a directional indicator.
  return inventoryColumnsForView().map(column => {
    const selected = state.sortKey === column.key;
    const status = selected ? (state.sortDirection === 'asc' ? 'ascending' : 'descending') : 'none';
    const arrow = selected ? (state.sortDirection === 'asc' ? '▲' : '▼') : '↕';
    const next = selected && state.sortDirection === 'asc' ? 'descending' : 'ascending';
    return `<div class="inventory-sort-heading" role="columnheader" aria-sort="${status}">
      <button type="button" class="sortbtn${column.right ? ' r' : ''}${selected ? ' on' : ''}"
              data-action="sort" data-value="${escapeHtml(column.key)}"
              title="Sort ${escapeHtml(column.label)} ${next}"
              aria-label="Sort ${escapeHtml(column.label)} ${next}">
        <span class="inventory-heading-label">${escapeHtml(column.label)}</span>
        <span class="inventory-sort-arrow" aria-hidden="true">${arrow}</span>
      </button>
    </div>`;
  }).join('');
}

function renderCompactSortControl() {
  // The normal header is intentionally hidden on narrow screens.
  // Supply the same full-column sorting in an accessible compact control.
  return `<div class="inventory-mobile-sort" role="group" aria-label="Inventory sorting">
    <label for="inventory-sort-select">Sort by</label>
    <select id="inventory-sort-select" aria-label="Sort products by column">
      ${inventoryColumnsForView().map(column => `<option value="${escapeHtml(column.key)}"${state.sortKey === column.key ? ' selected' : ''}>${escapeHtml(column.label)}</option>`).join('')}
    </select>
    <button type="button" class="btn inventory-sort-direction" data-action="sort-direction"
      aria-label="Switch sort direction">${state.sortDirection === 'asc' ? '↑ Ascending' : '↓ Descending'}</button>
  </div>`;
}

function renderProductTable(productsInView) {
  const selectedProducts = getProductsForTable(productsInView);
  const sortingExplanation = sortTableProducts(selectedProducts);

  // Save ALL matching rows for CSV export (not just the first 50).
  state.filteredProducts = selectedProducts;

  const warningCount = productsInView.filter(item => item.warnings.length > 0).length;
  const viewNames = {
    all: 'All products',
    clinic: 'Clinic inventory (all shared stock)',
    my: 'Listed on Shopee Malaysia',
    sg: 'Listed on Shopee Singapore'
  };

  const visibleRows = selectedProducts
    .slice(0, state.displayLimit)
    .map(renderProductRow)
    .join('');

  const emptyMessage = selectedProducts.length === 0
    ? '<div style="padding:32px 16px;font-size:14px;color:#4F5A55">No products match these filters.</div>'
    : '';

  const showMoreButtons = selectedProducts.length > state.displayLimit
    ? `
      <div style="display:flex;flex-wrap:wrap;gap:10px;padding:14px 20px;border-top:1px solid #E4E7E2">
        <button class="btn" data-action="more">Show 50 more</button>
        <button class="btn" data-action="allrows">Show all ${selectedProducts.length}</button>
      </div>
    `
    : '';

  return `
    <section class="panel" aria-label="Product table" style="overflow:visible">
      <div class="thead-bar">
        <div>
          <h2>${CARD_INFO[state.selectedCard].label} · ${viewNames[state.view]}</h2>
          <div style="font-size:13px;color:#4F5A55">
            ${CARD_INFO[state.selectedCard].rule} ·
            showing ${Math.min(selectedProducts.length, state.displayLimit)} of ${selectedProducts.length} ·
            ${state.category === 'all' ? 'all categories' : state.category} ·
            sorted by ${sortingExplanation}
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
          <button class="btn" data-action="warnings" aria-pressed="${state.showWarningsOnly}">
            Flagged data only · ${warningCount}
          </button>
          <label class="search">
            <span class="sr">Search product or ID</span>
            <input type="search" id="q" placeholder="Search product or ID"
                   value="${escapeHtml(state.searchText)}">
          </label>
          <button class="btn" data-action="csv">Export CSV</button>
        </div>
      </div>
      ${renderCompactSortControl()}
      <div class="scroll inventory-fit-scroll">
        <div class="trow thead" style="${inventoryGridStyle()}">${renderTableHeading()}</div>
        ${visibleRows}
        ${emptyMessage}
      </div>
      ${showMoreButtons}
    </section>
  `;
}

// The nine summary cards, grouped into three panels that look like the "Data uploads" panels below.
const RULE_GROUPS = [
  ['Sales and stock', ['all', 'sales']],
  ['Movement and cover', ['nonmoving', 'slow', 'high', 'lowstock']],
  ['Risk and margin', ['expiry', 'marginClinic', 'marginEcom']]
];
function renderRules(monthInfo) {
  const panels = RULE_GROUPS.map(([title, keys]) => {
    const rows = keys.filter(k => CARD_INFO[k]).map(cardKey => {
      const info = CARD_INFO[cardKey];
      const corner = cardKey === 'all' ? '2px' : '50%';
      return `
        <div class="up rule-row">
          <div style="display:flex;flex-direction:column;gap:3px">
            <span style="font-size:14px;font-weight:600"><i class="rule-dot" style="background:${info.color};border-radius:${corner}"></i>${info.label}</span>
            <span style="font-size:12px;color:#4F5A55">${info.rule}</span>
            <span style="font-size:12px;color:#4F5A55">${info.value}</span>
          </div>
        </div>`;
    }).join('');
    return `<div class="panel" style="padding:16px 20px"><h3 style="margin:0 0 6px;font-size:15px">${title}</h3>${rows}</div>`;
  }).join('');

  // Collapsed by default: this is reference text. state.rulesOpen keeps it open across redraws.
  return `
    <details id="rules-details" class="rules-section" aria-label="Rules"${state.rulesOpen ? ' open' : ''}>
      <summary><h2>How each card is calculated <span class="rules-count">· ${CARD_ORDER.length} rules</span></h2><b class="rules-toggle" aria-hidden="true"></b></summary>
      <div class="ups rules-groups">${panels}</div>
      <p class="rules-note">
        SGD converted at SGD 1 = RM ${monthInfo.fx}.
        GM = (price − latest cost) ÷ price, before Shopee fees.
        Clinic sales = clinic units × clinic price (estimate).
        Full rules: SPEC.md.
      </p>
    </details>
  `;
}
// Remember whether the rules panel is open (the page is redrawn on every filter / sort click).
document.addEventListener('toggle', event => {
  if (event.target && event.target.id === 'rules-details') state.rulesOpen = event.target.open;
}, true);

function renderUploadGroup(title, files) {
  const fileRows = files.map(file => `
    <div class="up">
      <div style="display:flex;flex-direction:column;gap:3px">
        <span style="font-size:14px;font-weight:600">
          <span class="num" style="color:#4F5A55">${file[0]}.</span> ${file[1]}
        </span>
        <span style="font-size:12px;color:#4F5A55">${file[2]}</span>
      </div>
      ${makeTag('Uploaded', '#E0F1E7', '#1B6340')}
    </div>
  `).join('');

  return `
    <div class="panel" style="padding:16px 20px">
      <h3 style="margin:0 0 6px;font-size:15px">${title}</h3>
      ${fileRows}
    </div>
  `;
}

function renderUploadStatus(monthInfo) {
  // Display ONLY: the original page does not actually upload files.
  return `
    <section aria-label="Data uploads" style="display:flex;flex-direction:column;gap:12px">
      <h2>Data uploads
        <span style="font-size:13px;font-weight:500;color:#4F5A55">· ${escapeHtml(monthInfo.label)}</span>
      </h2>
      <div class="ups">
        ${renderUploadGroup('Avixo', [
          [1, 'Inventory Report', `Snapshot ${escapeHtml(monthInfo.invSnapshot)} · ${monthInfo.invProducts} products, ${monthInfo.invBatches} batches`],
          [2, 'Drug Movement Report', `${escapeHtml(monthInfo.movement)} · ${monthInfo.movProducts} products`]
        ])}
        ${renderUploadGroup('Shopee Malaysia', [
          [3, 'Latest product price', `${monthInfo.myListings} listings`],
          [4, 'Product performance', 'Confirmed orders']
        ])}
        ${renderUploadGroup('Shopee Singapore', [
          [5, 'Latest product price', `${monthInfo.sgListings} listings (SGD)`],
          [6, 'Product performance', 'Paid orders']
        ])}
      </div>
    </section>
  `;
}


function reportBarRows(entries, money = false, stacked = false) {
  const max = Math.max(1, ...entries.map(e => Math.max(0, e.value)));
  return `<div class="chart-rows">${entries.map(e => {
    const percentage = Math.max(0, e.value) / max * 100;
    const label = money ? formatRoundedMoney(e.value) : formatNumber(e.value);
    return `<div class="chart-line${stacked ? ' chart-line-stack' : ''}"><span title="${escapeHtml(e.label)}">${escapeHtml(e.label)}</span>
      <div class="chart-track" role="img" aria-label="${escapeHtml(e.label)}: ${label}">
        <div class="chart-fill" style="width:${percentage.toFixed(2)}%;background:${e.color || '#0e5a52'}"></div></div>
      <strong class="num r">${label}</strong></div>`;
  }).join('')}</div>`;
}
function renderDonut(values, names, colors) {
  const total = values.reduce((a,b)=>a+b,0);
  const radius = 66, circumference = 2 * Math.PI * radius;
  let running = 0;
  const circles = values.map((value,i) => {
    const length = total ? value / total * circumference : 0;
    const svg = `<circle cx="90" cy="90" r="${radius}" fill="none" stroke="${colors[i]}" stroke-width="23" stroke-dasharray="${length} ${circumference-length}" stroke-dashoffset="${-running}" transform="rotate(-90 90 90)"><title>${escapeHtml(names[i])}: ${total ? (value/total*100).toFixed(1) : '0'}%</title></circle>`;
    running += length;
    return svg;
  }).join('');
  const legend = values.map((value,i) => `<div><i style="background:${colors[i]}"></i>${escapeHtml(names[i])}<b>${total ? (100*value/total).toFixed(1) : '0.0'}%</b></div>`).join('');
  return `<div class="channel-composition"><svg viewBox="0 0 180 180" width="195" height="195" role="img" aria-label="Revenue share by channel">
    <circle cx="90" cy="90" r="${radius}" fill="none" stroke="#e8eeea" stroke-width="23"/>${circles}
    <text x="90" y="84" text-anchor="middle" font-size="12" fill="#4f5a55">Total revenue</text>
    <text x="90" y="105" text-anchor="middle" font-size="15" font-weight="700" fill="#0e5a52">${formatNumber(Math.round(total))}</text>
    <text x="90" y="121" text-anchor="middle" font-size="10" fill="#4f5a55">RM (estimated)</text>
    </svg><div class="channel-legend">${legend}</div></div>`;
}
function renderGraphs(products) {
  const sales = [0,0,0], units = [0,0,0];
  products.forEach(item => {
    sales[0] += item.clinicSales || 0;
    sales[1] += item.malaysiaSales || 0;
    sales[2] += item.singaporeSales || 0;
    units[0] += item.product.s || 0;
    units[1] += item.product.my?.units || 0;
    units[2] += item.product.sg?.units || 0;
  });
  const colors = ['#0e5a52','#245ca6','#ae8525'];
  const names = ['Clinic','Shopee MY','Shopee SG'];
  const totals = sales.reduce((a,b)=>a+b,0), totalUnits=units.reduce((a,b)=>a+b,0);
  const revenueBars = reportBarRows(names.map((label,i)=>({label,value:sales[i],color:colors[i]})),true);
  const unitBars = reportBarRows(names.map((label,i)=>({label,value:units[i],color:colors[i]})));
  const top = products.map(item => ({label:item.product.n,value:item.clinicSales+item.malaysiaSales+item.singaporeSales})).sort((a,b)=>b.value-a.value).slice(0,10);
  return `<section class="chart-grid" aria-label="Business charts">
    <div class="panel chart-panel"><h2>Revenue by channel</h2><p class="chart-description">${escapeHtml(state.reportLabel || state.monthData.meta.label)} · ${formatRoundedMoney(totals)} combined</p>${revenueBars}</div>
    <div class="panel chart-panel"><h2>Units sold by channel</h2><p class="chart-description">${escapeHtml(state.reportLabel || state.monthData.meta.label)} · ${formatNumber(totalUnits)} units combined</p>${unitBars}</div>
    <div class="panel chart-panel" style="grid-column:1/-1"><h2>Channel revenue share</h2><p class="chart-description">Share of total estimated / matched revenue</p>${renderDonut(sales,names,colors)}</div>
    <div class="panel chart-panel" style="grid-column:1/-1"><h2>Top 10 products by revenue</h2><p class="chart-description">Across all three channels · ${escapeHtml(state.reportLabel || state.monthData.meta.label)}</p>${reportBarRows(top,true,true)}</div>
  </section>`;
}
function renderProductPicker() {
  const chosen = Number(new URLSearchParams(location.search).get('item') || 0);
  const options = state.analysedProducts.map((item,i)=>`<option value="${i}" ${i===chosen?'selected':''}>${escapeHtml(item.product.n)} (${escapeHtml(item.product.id || 'No ID')})</option>`).join('');
  return `<section class="panel product-picker"><h2>Product details</h2><p class="muted">Choose a product to see its individual charts and alerts.</p>
    <label class="lbl" for="product-choice">Select product</label><div style="margin-top:8px"><select id="product-choice">${options}</select></div></section>`;
}

// This short main function joins together the smaller sections above.
function renderDashboard() {
  if (!state.monthData) return;

  const monthInfo = state.monthData.meta;
  const productsInView = getProductsInSelectedView();
  document.getElementById('asof').textContent =
    `${monthInfo.label} · stock as of ${formatDate(monthInfo.today)}`;

  // Remember whether the user was typing before rebuilding the HTML.
  const userWasSearching = document.activeElement && document.activeElement.id === 'q';

  const page = document.body.dataset.page;
  const pageHtml = page === 'analytics'
    ? [renderDateControls(), renderFilters(), `<section class="analytics-intro"><h2>All-channel sales overview</h2><p>Clinic includes every recorded clinic sale, including products also listed on Shopee. Category can be filtered above. Clinic revenue is estimated from units × clinic price; Shopee revenue uses matched orders. All channels share the same stock pool.</p></section>`, renderBusinessAnalytics((state.reportProducts || state.analysedProducts).filter(item => state.category === 'all' || item.product.c === state.category)), renderGraphs((state.reportProducts || state.analysedProducts).filter(item => state.category === 'all' || item.product.c === state.category)),
       `<div class="report-note"><strong>Date accuracy:</strong> Custom ranges include only complete processed months. Partial-month intervals require daily or transaction-level reports. Inventory quantities from different dates are not summed.</div>`].join('')
    : page === 'product'
    ? [renderProductPicker(), '<div id="product-report"></div>'].join('')
    : [renderDateControls(), renderFilters(), state.dateMode === 'mtd' ? `<div class="date-feedback">MTD sales and margins cannot be calculated from monthly totals. Below are historical full-month results, NOT month-to-date figures.</div>` : '', renderExpiredBanner(monthInfo), renderDataQualityBanner(monthInfo),
       renderCards(productsInView), renderProductTable(productsInView),
       renderRules(monthInfo), renderUploadStatus(monthInfo)].join('');

  document.getElementById('app').innerHTML = pageHtml;

  const searchInput = document.getElementById('q');
  if (searchInput) searchInput.addEventListener('input', event => {
    state.searchText = event.target.value;
    state.displayLimit = 50;
    renderDashboard();
  });

  if (userWasSearching && searchInput) {
    searchInput.focus();
    searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
  }
  document.querySelector(`[data-nav="${page}"]`)?.classList.add('active');
  if (page === 'product') {
    const requested = Number(new URLSearchParams(location.search).get('item') || 0);
    openProductDetail(Math.max(0, Math.min(requested, state.analysedProducts.length - 1)));
  }
}

// -----------------------------------------------------------------------
// 10. EXPORT MATCHING TABLE ROWS TO CSV
// -----------------------------------------------------------------------
function exportCsv() {
  const headings = [
    'ID', 'Product', 'Category', 'Stock', 'Earliest expiry', 'Value RM',
    'Clinic sold', 'MY sold', 'SG sold', 'Units per month', 'Cover months',
    'Latest cost', 'Est. gross profit RM', 'Clinic price', 'Shopee MY price', 'Shopee SG price',
    'Clinic GM %', 'Shopee MY GM %', 'Shopee SG GM %', 'Alerts', 'Data flags'
  ];

  const rows = state.filteredProducts.map(item => {
    const product = item.product;
    const alertNames = getProductAlerts(item).map(key => CARD_INFO[key].label);

    return [
      product.id, product.n, product.c, product.q, product.x, item.stockValue,
      product.s, product.my ? product.my.units : '',
      product.sg ? product.sg.units : '', item.totalUnitsSold,
      item.stockCoverMonths == null ? '' : item.stockCoverMonths.toFixed(2),
      item.costPrice, (viewProfit(item) == null ? '' : viewProfit(item).toFixed(2)), item.clinicPrice, item.malaysiaPrice, item.singaporePrice,
      item.clinicMargin == null ? '' : item.clinicMargin.toFixed(1),
      item.malaysiaMargin == null ? '' : item.malaysiaMargin.toFixed(1),
      item.singaporeMargin == null ? '' : item.singaporeMargin.toFixed(1),
      alertNames.join('; '), item.warnings.join('; ')
    ];
  });

  // Put quotes around a CSV cell if it contains commas, quotation marks or newlines.
  function escapeCsvCell(value) {
    const text = value == null ? '' : String(value);
    if (/[",\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
    return text;
  }

  const csvFieldKeys = ['id','name','cat','qty','exp','value','clinic','my','sg','use','cover','cost','profit','price','myp','sgp','gm','mygm','sggm','alerts','flags'];
  const excludedExport = {all:[],clinic:['my','sg','myp','sgp','mygm','sggm'],my:['clinic','sg','sgp','sggm'],sg:['clinic','my','myp','mygm']}[state.view] || [];
  const includedIndices = csvFieldKeys.map((key,i) => excludedExport.includes(key)?-1:i).filter(i=>i>=0);
  const safeRows = [headings,...rows].map(row=>includedIndices.map(i=>row[i]));
  const csv = safeRows
    .map(row => row.map(escapeCsvCell).join(','))
    .join('\n');

  const downloadLink = document.createElement('a');
  downloadLink.href = URL.createObjectURL(
    new Blob(['\uFEFF' + csv], { type: 'text/csv' })
  );
  downloadLink.download = `hartamas-inventory-${state.selectedMonth}-${state.selectedCard}.csv`;
  downloadLink.click();
}


// Power BI-style product drill-down, built with HTML/CSS (no Power BI license required).
function detailBar(label, value, max, color, suffix = '') {
  const percent = max > 0 ? Math.max(0, Math.min(100, value / max * 100)) : 0;
  return `<div class="detail-bar-row"><span>${escapeHtml(label)}</span>
    <div class="detail-bar-track"><div class="detail-bar-fill" style="width:${percent}%;background:${color}"></div></div>
    <span class="num r">${formatNumber(value)}${suffix}</span></div>`;
}
// Shopee fee assumption set by staff on the Action Centre (percent of sales, saved in this browser).
const FEE_ASSUMPTION_KEY = 'fs_shopee_fee_assumption';
function readFeeAssumption() {
  try {
    const f = JSON.parse(localStorage.getItem(FEE_ASSUMPTION_KEY) || '{}');
    const c = v => { const n = Number(v); return Number.isFinite(n) ? Math.min(Math.max(n, 0), 100) : 0; };
    return {my: c(f.my), sg: c(f.sg)};
  } catch (e) { return {my: 0, sg: 0}; }
}
function saveFeeAssumption(f) { try { localStorage.setItem(FEE_ASSUMPTION_KEY, JSON.stringify(f)); } catch (e) { /* storage unavailable */ } }
// Estimated profit per channel = sales - units x latest cost - Shopee fee (sales x the staff fee %). Other expenses are not included.
function channelProfit(item) {
  const p = item.product, cost = item.costPrice || 0, has = Boolean(item.costPrice), fees = readFeeAssumption();
  const mk = (units, revenue, feePct) => {
    const fee = revenue * (feePct || 0) / 100;
    return {units, revenue, feePct: feePct || 0, fee, cost: has ? units * cost : null, profit: has ? revenue - units * cost - fee : null,
      margin: has && revenue > 0 ? (revenue - units * cost - fee) / revenue * 100 : null};
  };
  const rows = {clinic: mk(p.s || 0, item.clinicSales || 0, 0), my: mk(p.my ? p.my.units : 0, item.malaysiaSales || 0, fees.my), sg: mk(p.sg ? p.sg.units : 0, item.singaporeSales || 0, fees.sg)};
  const t = {units: 0, revenue: 0, fee: 0};
  ['clinic', 'my', 'sg'].forEach(k => { t.units += rows[k].units; t.revenue += rows[k].revenue; t.fee += rows[k].fee; });
  rows.total = {units: t.units, revenue: t.revenue, fee: t.fee, feePct: null, cost: has ? t.units * cost : null,
    profit: has ? t.revenue - t.units * cost - t.fee : null, margin: has && t.revenue > 0 ? (t.revenue - t.units * cost - t.fee) / t.revenue * 100 : null};
  return rows;
}
function viewProfit(item) {
  const r = channelProfit(item);
  return (r[state.view] || r.total).profit;
}
const customCalcState = {};
function customCalcResult(item) {
  const c = customCalcState[item.product.id] || {};
  const price = c.price === '' || c.price == null ? null : Number(c.price);
  const pct = c.pct === '' || c.pct == null ? null : Number(c.pct);
  const cost = c.cost === '' || c.cost == null ? (item.costPrice || null) : Number(c.cost);
  const ok = [price, pct, cost].every(v => v != null && Number.isFinite(v));
  if (!ok) return null;
  const keep = price * pct / 100, profit = keep - cost;
  return {keep, profit, margin: price > 0 ? profit / price * 100 : null};
}
function customCalcHtml(item) {
  const res = customCalcResult(item), money = v => formatMoney(v);
  if (!res) return '<span class="muted">Enter a price and a percentage to see the result.</span>';
  return `You keep <b>${money(res.keep)}</b> per unit, profit <b class="${res.profit < 0 ? 'calc-neg' : ''}">${money(res.profit)}</b> per unit${res.margin == null ? '' : ` (${formatPercent(res.margin)} of the price)`}.`;
}
function renderCustomCalc(item) {
  const c = customCalcState[item.product.id] || {};
  const cost = c.cost != null && c.cost !== '' ? c.cost : (item.costPrice || '');
  const inp = (k, label, val, step) => `<label class="calc-fee"><span>${label}</span><input type="number" min="0" step="${step}" inputmode="decimal" data-custom="${k}" value="${val == null ? '' : val}" placeholder="0"></label>`;
  return `<div class="calc-custom"><h4>Try your own price: (price per unit × percentage) − cost price</h4>
    <div class="calc-fees">${inp('price', 'Price per unit RM', c.price, '0.01')}${inp('pct', 'Percentage %', c.pct, '0.1')}${inp('cost', 'Cost price RM', cost, '0.01')}</div>
    <div class="calc-custom-out" id="calc-custom-out">${customCalcHtml(item)}</div></div>`;
}
function renderProfitCalc(item) {
  const r = channelProfit(item), has = Boolean(item.costPrice), fees = readFeeAssumption();
  const money = v => v == null ? 'n/a' : formatMoney(v);
  const cls = v => v != null && v < 0 ? 'calc-neg' : '';
  const label = (name, c) => `${name}${c.feePct ? ` <span class="muted">(fee ${formatNumber(c.feePct, 1)}%)</span>` : ''}`;
  const unitLine = (name, c) => {
    const price = c.units > 0 ? c.revenue / c.units : null, keepPct = 100 - (c.feePct || 0);
    const keep = price == null ? null : price * keepPct / 100, perUnit = keep == null || !has ? null : keep - item.costPrice;
    return `<tr><td>${label(name, c)}</td><td class="num">${money(price)}</td><td class="num">${formatNumber(keepPct, 1)}%</td><td class="num">${money(keep)}</td><td class="num">${has ? money(item.costPrice) : 'n/a'}</td><td class="num ${cls(perUnit)}">${money(perUnit)}</td><td class="num">${formatNumber(c.units)}</td><td class="num ${cls(c.profit)}">${money(c.profit)}</td></tr>`;
  };
  const line = (name, c, k) => `<tr class="${k || ''}"><td>${name}</td><td class="num">${formatNumber(c.units)}</td><td class="num">${formatMoney(c.revenue)}</td><td class="num">${money(c.cost)}</td><td class="num">${c.fee ? '−' + formatMoney(c.fee) : '0.00'}</td><td class="num ${cls(c.profit)}">${money(c.profit)}</td><td class="num">${c.margin == null ? 'n/a' : formatPercent(c.margin)}</td></tr>`;
  const box = (kind, k, text, value) => `<label class="calc-fee"><span>${text}</span><input type="number" min="0" max="100" step="0.1" inputmode="decimal" data-calc-${kind}="${k}" value="${value === 0 ? '' : value}" placeholder="0"><span>%</span></label>`;
  const feeRow = (k, name) => `<div class="calc-fees"><b>${name}</b>${box('fee', k, 'Fee %', fees[k])}${box('keep', k, 'Kept %', Math.round((100 - fees[k]) * 100) / 100)}</div>`;
  return `<aside class="calc-panel" aria-label="Profit calculation"><h3>Profit calculation</h3>
    <p class="muted calc-help">Type the fee % or the kept % (they add up to 100). It is the same Shopee fee assumption as the Action Centre, saved in this browser.</p>
    ${feeRow('my', 'Shopee MY')}${feeRow('sg', 'Shopee SG')}
    ${renderCustomCalc(item)}
    <h4>Per unit: (selling price × kept %) − cost price</h4>
    <table class="ba-table calc-table"><thead><tr><th>Channel</th><th>Selling price</th><th>Kept %</th><th>You keep</th><th>Cost</th><th>Profit / unit</th><th>Units</th><th>Profit</th></tr></thead><tbody>
      ${unitLine('Clinic', r.clinic)}${unitLine('Shopee MY', r.my)}${unitLine('Shopee SG', r.sg)}
    </tbody></table>
    <h4>Total</h4>
    <table class="ba-table calc-table"><thead><tr><th>Channel</th><th>Units</th><th>Revenue</th><th>Cost</th><th>Fee</th><th>Profit</th><th>Margin</th></tr></thead><tbody>
      ${line('Clinic', r.clinic)}${line('Shopee MY', r.my)}${line('Shopee SG', r.sg)}${line('Total', r.total, 'calc-total')}
    </tbody></table>
    <p class="muted">Latest cost ${has ? formatMoney(item.costPrice) : 'unavailable'}. Selling price is the average price actually received. Staff, rent and other expenses are not included.</p></aside>`;
}
function bindProfitCalc(overlay, item) {
  overlay.querySelectorAll('[data-custom]').forEach(input => input.addEventListener('input', () => {
    const c = customCalcState[item.product.id] = customCalcState[item.product.id] || {};
    c[input.dataset.custom] = input.value;
    const out = overlay.querySelector('#calc-custom-out'); if (out) out.innerHTML = customCalcHtml(item);
  }));
  const clamp = v => { const n = Number(v); return Number.isFinite(n) ? Math.min(Math.max(n, 0), 100) : 0; };
  overlay.querySelectorAll('[data-calc-fee],[data-calc-keep]').forEach(input => input.addEventListener('change', () => {
    const f = readFeeAssumption(), isFee = input.hasAttribute('data-calc-fee'), k = input.dataset.calcFee || input.dataset.calcKeep;
    f[k] = isFee ? clamp(input.value) : 100 - clamp(input.value === '' ? 100 : input.value);
    saveFeeAssumption(f);
    const panel = overlay.querySelector('.calc-panel');
    if (panel) { panel.outerHTML = renderProfitCalc(item); bindProfitCalc(overlay, item); }
  }));
}
function openProductDetail(index) {
  const item = state.analysedProducts[index];
  if (!item) return;
  const p = item.product;
  const units = [p.s || 0, p.my?.units || 0, p.sg?.units || 0];
  const revenue = [item.clinicSales || 0, item.malaysiaSales || 0, item.singaporeSales || 0];
  const totalRevenue = revenue.reduce((a,b) => a+b,0);
  const estimatedCost = item.totalUnitsSold * (item.costPrice || 0);
  const profit = totalRevenue - estimatedCost;
  const margin = totalRevenue > 0 ? profit / totalRevenue * 100 : null;
  const maxUnits = Math.max(...units, 1);
  const maxRevenue = Math.max(...revenue, 1);
  const channels = ['Clinic','Shopee MY','Shopee SG'];
  const colors = ['#0e5a52','#1f5fa8','#8a6d1f'];
  const unitBars = units.map((v,i) => detailBar(channels[i],v,maxUnits,colors[i])).join('');
  const revenueBars = revenue.map((v,i) => detailBar(channels[i],v,maxRevenue,colors[i])).join('');
  const badges = getProductAlerts(item).map(key => makeTag(CARD_INFO[key].label, BADGE[key][0], BADGE[key][1])).join(' ') || makeTag('No stock alerts','#e0f1e7','#1b6340');
  const warningHtml = item.warnings.length ? item.warnings.map(w => `<p>⚑ ${escapeHtml(w)}</p>`).join('') : '<p>No data warnings for this product.</p>';
  const batchRows = (p.b || []).map(b => `<tr><td>${escapeHtml(formatDate(b[0]) || 'Unknown')}</td><td class="num">${formatNumber(b[1] || 0)}</td></tr>`).join('');
  const overlay = document.createElement('div');
  overlay.className = 'detail-overlay';
  overlay.id = 'product-detail-overlay';
  overlay.innerHTML = `
    <section class="detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
      <div class="detail-head">
        <div><div class="muted">PRODUCT ANALYTICS · ${escapeHtml(state.monthData.meta.label)}</div>
          <h2 id="detail-title" style="font-size:22px;margin:6px 0">${escapeHtml(p.n)}</h2>
          <div class="muted">ID ${escapeHtml(p.id || 'Unavailable')} · ${escapeHtml(p.c || 'Uncategorized')}</div></div>
        <button class="detail-close" data-action="close-detail" aria-label="Close product analytics">✕ Close</button>
      </div>
      <div class="detail-body">
        <div class="detail-split"><div class="detail-split-cards">
        <div class="detail-grid">
          <div class="ba-card"><h3>Current stock</h3><div class="value num">${formatNumber(p.q || 0)} units</div><p>Shared across all channels</p></div>
          <div class="ba-card"><h3>Stock value</h3><div class="value num">${formatRoundedMoney(item.stockValue)}</div><p>At latest product cost</p></div>
          <div class="ba-card"><h3>Units sold</h3><div class="value num">${formatNumber(item.totalUnitsSold)}</div><p>Current reporting month</p></div>
          <div class="ba-card"><h3>Estimated revenue</h3><div class="value num">${formatRoundedMoney(totalRevenue)}</div><p>Clinic estimated; Shopee matched orders</p></div>
          <div class="ba-card"><h3>Estimated gross profit</h3><div class="value num">${item.costPrice ? formatRoundedMoney(profit) : 'n/a'}</div><p>Before platform fees and expenses</p></div>
          <div class="ba-card"><h3>Estimated gross margin</h3><div class="value num">${item.costPrice ? formatPercent(margin) : 'n/a'}</div><p>Revenue minus estimated product cost</p></div>
          <div class="ba-card"><h3>Stock cover</h3><div class="value num">${item.stockCoverMonths == null ? 'No sales' : formatNumber(item.stockCoverMonths,1)+' months'}</div><p>Current stock ÷ monthly units sold</p></div>
          <div class="ba-card"><h3>Earliest expiry</h3><div class="value" style="font-size:18px">${escapeHtml(formatDate(p.x) || 'Unavailable')}</div><p>Based on recorded stock batches</p></div>
        </div>
        </div>
        ${renderProfitCalc(item)}</div>
        <div class="detail-section detail-charts">
          <div class="detail-chart"><h3>Units sold by channel</h3>${unitBars}</div>
          <div class="detail-chart"><h3>Revenue by channel (RM)</h3>${revenueBars}</div>
        </div>
        <div class="detail-section"><h3>Pricing &amp; gross margin</h3>
          <div class="scroll"><table class="ba-table"><thead><tr><th>Channel</th><th>Selling price</th><th>Gross margin</th></tr></thead><tbody>
            <tr><td>Clinic</td><td>${formatMoney(item.clinicPrice)}</td><td>${formatPercent(item.clinicMargin)}</td></tr>
            <tr><td>Shopee MY</td><td>${p.my ? formatMoney(item.malaysiaPrice) : 'Not listed'}</td><td>${p.my ? formatPercent(item.malaysiaMargin) : 'n/a'}</td></tr>
            <tr><td>Shopee SG</td><td>${p.sg ? formatMoney(item.singaporePrice) + (formatSgd(item.singaporePrice) ? ` <span class="muted">· ${formatSgd(item.singaporePrice)}</span>` : '') : 'Not listed'}</td><td>${p.sg ? formatPercent(item.singaporeMargin) : 'n/a'}</td></tr>
          </tbody></table></div><p class="muted">Latest unit cost: ${formatMoney(item.costPrice)}. Singapore price is shown in RM and in S$ (converted at SGD 1 = RM ${singaporeRate() ?? 'n/a'}).</p>
        </div>
        <div class="detail-section"><h3>Stock alerts</h3><div style="display:flex;gap:8px;flex-wrap:wrap">${badges}</div>
          <h3 style="margin-top:18px">Data quality</h3>${warningHtml}</div>
        <div class="detail-section"><h3>Expiry batches</h3>
          ${batchRows ? `<table class="ba-table"><thead><tr><th>Expiry date</th><th>Units</th></tr></thead><tbody>${batchRows}</tbody></table>` : '<p class="muted">No batch details available.</p>'}
        </div>
        <p class="muted">These charts show the selected month only, not a historical sales trend. Estimates exclude platform fees and operating expenses.</p>
      </div>
    </section>`;
  (document.body.dataset.page === 'product' ? document.getElementById('product-report') : document.body).appendChild(overlay);
  bindProfitCalc(overlay, item);
  document.body.classList.add('detail-open');
  if (document.body.dataset.page === 'product') {
    overlay.querySelector('.detail-close').textContent = '← Inventory';
    overlay.querySelector('.detail-close').setAttribute('title','Return to inventory');
  } else overlay.querySelector('.detail-close').focus();
}
function closeProductDetail() {
  document.getElementById('product-detail-overlay')?.remove();
  document.body.classList.remove('detail-open');
}
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.body.dataset.page !== 'product') closeProductDetail();
});
document.addEventListener('click', event => {
  if (event.target.id === 'product-detail-overlay' && document.body.dataset.page !== 'product') closeProductDetail();
});

// -----------------------------------------------------------------------
// 11. BUTTON CLICKS
// -----------------------------------------------------------------------
// "Event delegation": listen for all buttons in one place.
// data-action tells us WHAT was clicked; data-value tells us WHICH option.
document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;

  const action = button.getAttribute('data-action');
  const value = button.getAttribute('data-value');

  if (action === 'close-detail') { if (document.body.dataset.page === 'product') location.href='index.html'; else closeProductDetail(); return; }
  if (action === 'product') { location.href='product.html?item='+encodeURIComponent(value); return; }
  if (action === 'top-sort') {
    const same = state.topSort.key === value;
    state.topSort = { key: value, direction: same && state.topSort.direction === 'desc' ? 'asc' : 'desc' };
    renderDashboard();
    return;
  }

  if (action === 'date-mode') {
    state.dateMode = value;
    state.dateMessage = '';
    if (value === 'range') { state.reportProducts = []; renderDashboard(); }
    else applyReportDates().catch(e=>showError(e.message));
    return;
  }
  if (action === 'apply-dates') {
    state.dateFrom = document.getElementById('report-from')?.value || '';
    state.dateTo = document.getElementById('report-to')?.value || '';
    applyReportDates().catch(e=>showError(e.message)); return;
  }
  if (action === 'live-month') { loadSupabaseMonth(value).catch(error => showError('Could not load Supabase data: ' + error.message)); return; }
  if (action === 'month') {
    loadMonth(value).catch(error => showError('Could not load data: ' + error.message));
    return;
  }

  if (action === 'view') state.view = value;
  if (action === 'category') state.category = value;
  if (action === 'card') state.selectedCard = value;
  if (action === 'warnings') state.showWarningsOnly = !state.showWarningsOnly;
  if (action === 'more') state.displayLimit += 50;
  if (action === 'allrows') state.displayLimit = 1000000;

  if (action === 'csv') {
    exportCsv();
    return;
  }

  if (action === 'sort' && TABLE_COLUMNS.some(column => column.key === value)) {
    if (state.sortKey === value) {
      state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
      state.sortKey = value;
      state.sortDirection = 'asc';
    }
  }
  if (action === 'sort-direction') {
    state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
  }

  // Reset pagination when switching views, categories or summary cards.
  if (action !== 'more' && action !== 'allrows' && action !== 'sort') {
    state.displayLimit = 50;
  }

  renderDashboard();
});

// Run the dashboard once the page has loaded this script.
document.addEventListener('change', event => {
  if (event.target.id === 'inventory-sort-select') {
    if (TABLE_COLUMNS.some(column => column.key === event.target.value)) {
      state.sortKey = event.target.value;
      state.sortDirection = 'asc';
      renderDashboard();
    }
    return;
  }
  if (event.target.id === 'report-month') { loadMonth(event.target.value).catch(e=>showError(e.message)); return; }
  if (event.target.id === 'live-month-channel') { state.liveChannel=event.target.value; renderLiveMonth(); return; }
  if (event.target.id === 'live-month-category') { state.liveCategory=event.target.value; renderLiveMonth(); return; }

  if (event.target.id === 'product-choice') location.href = 'product.html?item=' + encodeURIComponent(event.target.value);
});
document.addEventListener('input',event=>{
  if (event.target.id !== 'live-month-search') return;
  const input=event.target;
  const cursor=input.selectionStart;
  state.liveSearch=input.value;
  renderLiveMonth();
  const next=document.getElementById('live-month-search');
  if (next) { next.focus(); next.setSelectionRange(cursor,cursor); }
});
startDashboard();

// When the viewport crosses the mobile breakpoint, rebuild columns.
let inventoryCompact = window.innerWidth <= 740;
window.addEventListener('resize', () => {
  const nextCompact = window.innerWidth <= 740;
  if (nextCompact !== inventoryCompact) {
    inventoryCompact = nextCompact;
    renderDashboard();
  }
});
