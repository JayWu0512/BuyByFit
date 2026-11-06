// Home Depot specifics: product id from URL, specs embedded in page state, search result links.

export const isHomeDepot = (url) => /(^|\.)homedepot\.com$/i.test(new URL(url).hostname);

export const hdProductUrl = (id) => `https://www.homedepot.com/p/${id}`;

export function hdIdFromUrl(url) {
  return url.match(/\/(\d{9})(?:[/?#]|$)/)?.[1] || null;
}

const unescape = (s) => s.replace(/\\u002F/g, "/").replace(/\\"/g, '"').replace(/\\\\/g, "\\");

// Specs appear in embedded JSON as {"specName":"Product Width (in.)","specValue":"84"} (escaped or not).
export function hdSpecs(html) {
  const specs = [];
  const seen = new Set();
  const re = /\\?"specName\\?"\s*:\s*\\?"([^"\\]+)\\?"\s*,\s*\\?"specValue\\?"\s*:\s*\\?"([^"\\]*)\\?"/g;
  for (const m of html.matchAll(re)) {
    const name = unescape(m[1]).trim();
    if (seen.has(name)) continue;
    seen.add(name);
    specs.push({ name, value: unescape(m[2]).trim() });
  }
  return specs;
}

// Search/category page -> unique product links
export function hdSearchResults(html) {
  const out = [];
  const seen = new Set();
  for (const m of html.matchAll(/href=["'](\/p\/([^"'?#]+?)\/(\d{9}))["'?#]/g)) {
    const id = m[3];
    if (seen.has(id)) continue;
    seen.add(id);
    out.push({ id, url: `https://www.homedepot.com${m[1]}`, slug_title: decodeURIComponent(m[2]).replace(/-/g, " ") });
  }
  return out;
}
