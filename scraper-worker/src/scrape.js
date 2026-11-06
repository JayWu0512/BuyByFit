import { fetchPage } from "./fetcher.js";
import { extractJsonLd, productFromJsonLd } from "./parse/jsonld.js";
import { isHomeDepot, hdIdFromUrl, hdProductUrl, hdSpecs, hdSearchResults } from "./parse/homedepot.js";
import { dimsFromSpecs, dimsFromText, mergeDims } from "./parse/dimensions.js";

// Pure parsing step (no network) — exported for tests.
export function parseProduct(html, url) {
  const hd = isHomeDepot(url);
  const base = productFromJsonLd(extractJsonLd(html)) || {};
  const specs = [...(base.specs || []), ...(hd ? hdSpecs(html) : [])];
  const dims = mergeDims(dimsFromSpecs(specs), dimsFromText(`${base.title || ""} ${base.description || ""}`));
  const source = hd ? "homedepot" : new URL(url).hostname.replace(/^www\./, "");
  const source_id = (hd ? hdIdFromUrl(url) : null) || base.sku || null;
  return {
    id: source_id ? `${source}:${source_id}` : null,
    source,
    source_id,
    url,
    title: base.title ?? null,
    brand: base.brand ?? null,
    category: base.category || [],
    price: base.price ?? null,
    currency: base.currency ?? null,
    rating: base.rating ?? null,
    review_count: base.review_count ?? null,
    description: base.description ?? null,
    image_urls: base.image_urls || [],
    ...dims,
    specs,
    // Filled later by the vibe step (vision LLM caption + tags)
    caption: null,
    vibe_tags: null,
    scraped_at: new Date().toISOString(),
  };
}

export async function scrapeProduct({ id, url }) {
  const target = url || hdProductUrl(id);
  const page = await fetchPage(target);
  if (page.fetchError) return { ok: false, url: target, status: 0, error: "fetch_failed", detail: page.fetchError };
  if (page.blocked) return { ok: false, url: target, status: page.status, error: "blocked_by_site" };
  if (page.status !== 200) return { ok: false, url: target, status: page.status, error: "http_error" };
  const product = parseProduct(page.html, page.finalUrl || target);
  if (!product.title) return { ok: false, url: target, status: page.status, error: "no_product_data" };
  return { ok: true, product };
}

export async function searchHomeDepot(q, page = 1) {
  const nao = (Math.max(1, page) - 1) * 24;
  const target = `https://www.homedepot.com/s/${encodeURIComponent(q)}${nao ? `?Nao=${nao}` : ""}`;
  const res = await fetchPage(target);
  if (res.fetchError) return { ok: false, url: target, status: 0, error: "fetch_failed", detail: res.fetchError };
  if (res.blocked) return { ok: false, url: target, status: res.status, error: "blocked_by_site" };
  if (res.status !== 200) return { ok: false, url: target, status: res.status, error: "http_error" };
  return { ok: true, url: target, results: hdSearchResults(res.html) };
}
