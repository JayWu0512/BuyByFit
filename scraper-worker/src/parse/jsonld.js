// Generic schema.org Product extraction from JSON-LD. Works on many retailers.

export function extractJsonLd(html) {
  const blocks = [];
  for (const m of html.matchAll(/<script[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      blocks.push(JSON.parse(m[1].trim()));
    } catch (_) { /* skip malformed block */ }
  }
  // flatten arrays and @graph
  const nodes = [];
  const walk = (n) => {
    if (!n) return;
    if (Array.isArray(n)) return n.forEach(walk);
    if (typeof n !== "object") return;
    nodes.push(n);
    if (n["@graph"]) walk(n["@graph"]);
  };
  walk(blocks);
  return nodes;
}

const isType = (n, t) => [].concat(n["@type"] || []).some((x) => String(x).toLowerCase() === t.toLowerCase());

function images(img) {
  return [].concat(img || [])
    .map((i) => (typeof i === "string" ? i : i?.url || i?.contentUrl))
    .filter(Boolean);
}

function offer(offers) {
  const o = [].concat(offers || [])[0];
  if (!o) return { price: null, currency: null };
  const price = o.price ?? o.lowPrice ?? o.offers?.[0]?.price ?? null;
  return { price: price != null ? Number(price) : null, currency: o.priceCurrency || null };
}

export function productFromJsonLd(nodes) {
  const p = nodes.find((n) => isType(n, "Product"));
  if (!p) return null;
  const crumbs = nodes.find((n) => isType(n, "BreadcrumbList"));
  const category = crumbs?.itemListElement
    ?.map((e) => e.name || e.item?.name)
    .filter(Boolean) || [];
  const { price, currency } = offer(p.offers);
  const additional = [].concat(p.additionalProperty || []).map((a) => ({ name: a.name, value: String(a.value) }));
  const dimProp = (k) => (p[k] ? [{ name: k, value: `${p[k].value ?? p[k]} ${p[k].unitCode === "CMT" ? "cm" : p[k].unitText || ""}` }] : []);
  return {
    title: p.name || null,
    brand: typeof p.brand === "string" ? p.brand : p.brand?.name || null,
    sku: p.sku || p.productID || p.mpn || null,
    description: p.description || null,
    image_urls: images(p.image),
    price,
    currency,
    rating: p.aggregateRating?.ratingValue != null ? Number(p.aggregateRating.ratingValue) : null,
    review_count: p.aggregateRating?.reviewCount != null ? Number(p.aggregateRating.reviewCount) : null,
    category,
    specs: [...additional, ...dimProp("width"), ...dimProp("depth"), ...dimProp("height")],
  };
}
