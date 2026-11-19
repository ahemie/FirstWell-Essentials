// FirstWell Essentials navigation — ONE place that defines the three sections of the site.
//   1. Dashboard        reports, analytics, uploads
//   2. Price Scraping   competitor prices (Price Watch)
//   3. Inventory Update scan a barcode, count / stock in / stock out
// To add or move a page, edit SECTIONS below. Every page loads this file right after its <nav>.
(function (root) {
  'use strict';
  var SECTIONS = [
    { id: 'dashboard', label: 'Dashboard', pages: [
      { page: 'inventory', href: '/index.html',     label: 'Stock Report' },
      { page: 'analytics', href: '/analytics.html', label: 'Business Analytics' },
      { page: 'product',   href: '/product.html',   label: 'Product Details' },
      { page: 'bi',        href: '/bi.html',        label: 'Live Sales', badge: 'LIVE' },
      { page: 'overview',  href: '/overview.html',  label: 'Action Centre' },
      { page: 'upload',    href: '/upload.html',    label: 'Upload Data' }
    ] },
    { id: 'scraping', label: 'Price Scraping', pages: [
      { page: 'scrap', href: '/scrap.html', label: 'Price Watch' }
    ] },
    { id: 'stock', label: 'Inventory Update', pages: [
      { page: 'stock', href: '/inventory.html', label: 'Scan & Update' },
      { page: 'after', href: '/stock-after-sales.html', label: 'Stock After Sales' }
    ] }
  ];

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }
  function sectionOf(page) {
    for (var i = 0; i < SECTIONS.length; i++) {
      for (var j = 0; j < SECTIONS[i].pages.length; j++) if (SECTIONS[i].pages[j].page === page) return SECTIONS[i];
    }
    return SECTIONS[0];
  }
  function pageLinks(section, page) {
    return section.pages.map(function (p) {
      return '<a href="' + p.href + '" data-nav="' + p.page + '"' + (p.page === page ? ' aria-current="page"' : '') + '>' +
        esc(p.label) + (p.badge ? ' <span class="fs-nav-new">' + esc(p.badge) + '</span>' : '') + '</a>';
    }).join('');
  }
  function sectionBar(current) {
    return '<div class="fs-sections-inner" role="tablist" aria-label="Sections">' + SECTIONS.map(function (s, i) {
      return '<a role="tab" href="' + s.pages[0].href + '" data-section="' + s.id + '"' +
        (s === current ? ' aria-current="page" aria-selected="true"' : ' aria-selected="false"') + '><b>' + (i + 1) + '</b>' + esc(s.label) + '</a>';
    }).join('') + '</div>';
  }

  function render(doc) {
    var nav = doc.querySelector('nav.fs-nav');
    if (!nav) return;
    var page = doc.body.getAttribute('data-page');
    var section = sectionOf(page);
    var bar = doc.createElement('div');
    bar.className = 'fs-sections';
    bar.innerHTML = sectionBar(section);
    nav.parentNode.insertBefore(bar, nav);
    nav.setAttribute('aria-label', section.label + ' pages');
    nav.innerHTML = pageLinks(section, page);
    // a section with a single page has nothing to switch between
    if (section.pages.length < 2) nav.hidden = true;
  }

  var api = { SECTIONS: SECTIONS, sectionOf: sectionOf, pageLinks: pageLinks, sectionBar: sectionBar };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (root && root.document) render(root.document);
})(typeof window !== 'undefined' ? window : null);
