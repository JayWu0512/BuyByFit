import { scrapeProduct, searchHomeDepot } from "./scrape.js";

const MAX_BATCH = 20; // stays under the free-plan subrequest limit with retries
const DELAY_MS = 400; // spacing between requests in a batch

const json = (data, status = 200) =>
  new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" },
  });

const CSV_COLS = ["id", "source", "source_id", "url", "title", "brand", "category", "price", "currency",
  "width_cm", "depth_cm", "height_cm", "rating", "review_count", "image_urls", "description", "scraped_at"];

function toCsv(products) {
  const cell = (v) => {
    const s = Array.isArray(v) ? v.join(" | ") : v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [CSV_COLS.join(","), ...products.map((p) => CSV_COLS.map((c) => cell(p[c])).join(","))].join("\n");
}

function authorized(request, env) {
  const expected = env.API_PASSWORD;
  if (!expected) return false;
  const url = new URL(request.url);
  const header = request.headers.get("x-api-key");
  const basic = request.headers.get("authorization");
  let basicPass = null;
  if (basic?.startsWith("Basic ")) {
    try { basicPass = atob(basic.slice(6)).split(":").slice(1).join(":"); } catch (_) {}
  }
  return [header, basicPass, url.searchParams.get("key")].includes(expected);
}

const HELP = {
  name: "BuyByFit product scraper API",
  auth: "Send the password as header 'x-api-key', as ?key=, or via HTTP Basic auth (any username).",
  endpoints: {
    "GET /product?id=<9-digit Home Depot id>": "Scrape one Home Depot product",
    "GET /product?url=<product url>": "Scrape any retailer page that has schema.org Product data",
    "GET /search?q=<query>&page=1": "List Home Depot product ids/urls for a search",
    "POST /batch {ids:[], urls:[], format:'json'|'csv'}": `Scrape up to ${MAX_BATCH} products`,
    "GET /collect?q=<query>&limit=10&format=csv": "Search, then scrape the top results in one call",
  },
};

async function runBatch(items) {
  const results = [];
  for (const [i, item] of items.entries()) {
    if (i) await new Promise((r) => setTimeout(r, DELAY_MS));
    results.push(await scrapeProduct(item));
  }
  return {
    products: results.filter((r) => r.ok).map((r) => r.product),
    errors: results.filter((r) => !r.ok),
  };
}

function respond(out, format) {
  if (format === "csv") {
    return new Response(toCsv(out.products), {
      headers: { "content-type": "text/csv; charset=utf-8", "access-control-allow-origin": "*" },
    });
  }
  return json({ count: out.products.length, ...out });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "x-api-key, content-type, authorization", "access-control-allow-methods": "GET, POST" } });
    }
    if (url.pathname === "/" || url.pathname === "/health") return json({ ok: true, ...HELP });
    if (!authorized(request, env)) {
      return new Response(JSON.stringify({ error: "unauthorized" }), {
        status: 401,
        headers: { "content-type": "application/json", "www-authenticate": 'Basic realm="BuyByFit"' },
      });
    }

    try {
      if (url.pathname === "/product") {
        const id = url.searchParams.get("id");
        const target = url.searchParams.get("url");
        if (!id && !target) return json({ error: "pass ?id= or ?url=" }, 400);
        if (id && !/^\d{9}$/.test(id)) return json({ error: "id must be a 9-digit Home Depot id" }, 400);
        const r = await scrapeProduct({ id, url: target });
        return json(r, r.ok ? 200 : 502);
      }

      if (url.pathname === "/search") {
        const q = url.searchParams.get("q");
        if (!q) return json({ error: "pass ?q=" }, 400);
        const r = await searchHomeDepot(q, Number(url.searchParams.get("page") || 1));
        return json(r, r.ok ? 200 : 502);
      }

      if (url.pathname === "/batch" && request.method === "POST") {
        const body = await request.json().catch(() => ({}));
        const items = [
          ...(body.ids || []).map((id) => ({ id: String(id) })),
          ...(body.urls || []).map((u) => ({ url: u })),
        ].slice(0, MAX_BATCH);
        if (!items.length) return json({ error: "send {ids:[...]} or {urls:[...]}" }, 400);
        return respond(await runBatch(items), body.format);
      }

      if (url.pathname === "/collect") {
        const q = url.searchParams.get("q");
        if (!q) return json({ error: "pass ?q=" }, 400);
        const limit = Math.min(Number(url.searchParams.get("limit") || 10), MAX_BATCH - 1);
        const s = await searchHomeDepot(q, Number(url.searchParams.get("page") || 1));
        if (!s.ok) return json(s, 502);
        const out = await runBatch(s.results.slice(0, limit).map((r) => ({ url: r.url })));
        return respond(out, url.searchParams.get("format"));
      }

      return json({ error: "not found", ...HELP }, 404);
    } catch (err) {
      return json({ error: "internal_error", message: String(err?.message || err) }, 500);
    }
  },
};
