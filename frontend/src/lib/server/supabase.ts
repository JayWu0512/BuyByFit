/**
 * Server-only access to the BuyByFit catalogue in Supabase, over its REST API (PostgREST).
 *
 * - Search: embed the brief (embed.ts), call the `match_products` SQL function via /rest/v1/rpc.
 *   That function applies the room-fit filter inside the database, so a tight room still returns a
 *   full page, and products with unknown dimensions never pass a size filter.
 * - Product pages: /rest/v1/products?id=eq.<id>.
 *
 * Uses the publishable (anon) key. Row-level security allows reads only, so the key can't change data.
 * It's still read from server-only env vars so the browser never talks to Supabase directly.
 */
import type { ApiProductCard } from "@/lib/api";
import { cleanProductText, toFurnitureProduct } from "@/lib/api";
import type { FurnitureProduct } from "@/types/furniture";

import { parseBrief, type BriefHints } from "./brief";
import { EMBEDDING_MODEL, EMBEDDING_VERSION, embedQuery } from "./embed";

const PRODUCT_COLUMNS = [
  "id", "title", "brand", "product_type", "style", "material", "color", "price", "currency", "description",
  "image_urls", "url", "model_3d_url", "ar_model_url", "width_cm", "depth_cm", "height_cm", "caption", "vibe_tags",
  "est_price_low", "est_price_high", "est_price_basis",
].join(",");
const PAGE_SIZE = 24;

interface ProductRow {
  id: string;
  title: string;
  brand: string | null;
  product_type: string | null;
  style: string | null;
  material: string | null;
  color: string | null;
  price: number | null;
  currency: string | null;
  description: string | null;
  image_urls: string[] | null;
  url: string | null;
  model_3d_url: string | null;
  ar_model_url: string | null;
  width_cm: number | null;
  depth_cm: number | null;
  height_cm: number | null;
  caption: string | null;
  vibe_tags: string[] | null;
  est_price_low: number | string | null;
  est_price_high: number | string | null;
  est_price_basis: string | null;
}

interface MatchRow {
  id: string;
  similarity: number;
}

export interface SearchFilters {
  categories?: unknown;
  colors?: unknown;
  min_price?: unknown;
  max_price?: unknown;
  max_width_cm?: unknown;
  max_depth_cm?: unknown;
}

function config() {
  const url = process.env.SUPABASE_URL?.trim().replace(/\/$/, "");
  const key = process.env.SUPABASE_ANON_KEY?.trim();
  return url && key ? { url, key } : null;
}

export function supabaseConfigured() {
  return config() !== null;
}

async function rest<T>(path: string, init: RequestInit & { revalidate?: number } = {}): Promise<T> {
  const cfg = config();
  if (!cfg) throw new Error("Supabase is not configured");
  const { revalidate, ...rest } = init;
  const response = await fetch(`${cfg.url}/rest/v1/${path}`, {
    ...rest,
    headers: { apikey: cfg.key, Authorization: `Bearer ${cfg.key}`, "Content-Type": "application/json", ...rest.headers },
    ...(revalidate ? { next: { revalidate } } : { cache: "no-store" }),
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Supabase ${response.status}: ${body.slice(0, 200)}`);
  }
  return (await response.json()) as T;
}

const inList = (ids: string[]) => `in.(${ids.map((id) => `"${id.replace(/"/g, '\\"')}"`).join(",")})`;

/** ar_model_url is stored relative ("/models/x.glb") because the AR demo serves the files. Only expose it with a host. */
function arUrl(value: string | null) {
  if (!value) return null;
  if (/^https?:\/\//.test(value)) return value;
  const base = process.env.AR_ASSET_BASE_URL?.trim().replace(/\/$/, "");
  return base ? `${base}${value.startsWith("/") ? "" : "/"}${value}` : null;
}

function toCard(row: ProductRow, similarity: number | null, reason: string): ApiProductCard {
  const images = (row.image_urls ?? []).filter((u) => typeof u === "string" && u.trim());
  const tags = row.vibe_tags?.length ? row.vibe_tags : row.style ? [row.style] : [];
  return {
    id: row.id,
    name: row.title,
    brand: row.brand,
    category: row.product_type?.toLowerCase() ?? null,
    price: row.price === null ? null : Number(row.price),
    currency: row.currency,
    price_estimate:
      row.price === null && row.est_price_low !== null && row.est_price_high !== null
        ? { low: Number(row.est_price_low), high: Number(row.est_price_high), basis: row.est_price_basis }
        : null,
    image_url: images[0] ?? null,
    image_urls: images,
    product_url: row.url,
    description: cleanProductText(row.description) || null,
    material: row.material,
    color: row.color,
    caption: row.caption,
    model_3d_url: row.model_3d_url,
    ar_model_url: arUrl(row.ar_model_url),
    dimensions_cm: { width: row.width_cm, depth: row.depth_cm, height: row.height_cm },
    style_tags: tags,
    match_score: similarity === null ? 0 : Math.max(0, Math.min(99, Math.round(similarity * 100))),
    match_reason: reason,
  };
}

const asNumber = (v: unknown) => {
  const n = typeof v === "number" ? v : Number(v);
  return v !== null && v !== "" && v !== undefined && Number.isFinite(n) && n >= 0 ? n : null;
};
const asList = (v: unknown) =>
  (Array.isArray(v) ? v : typeof v === "string" ? [v] : []).map((x) => String(x).trim()).filter(Boolean);

function reasonFor(h: BriefHints, w: number | null, d: number | null, widened: boolean) {
  const parts = [`Matches “${h.vibe}”`];
  if (w && d) parts.push(`fits within ${Math.round(w)} × ${Math.round(d)} cm`);
  else if (w) parts.push(`under ${Math.round(w)} cm wide`);
  else if (d) parts.push(`under ${Math.round(d)} cm deep`);
  if (widened && h.typeLabel) parts.push(`no ${h.typeLabel} fits, so similar pieces that do`);
  return parts.join(" · ");
}

/** Same response shape as the FastAPI service and the local fallback (API_CONTRACT.md). */
export async function searchCatalog(styleDescription: string, filters: SearchFilters = {}) {
  const hints = parseBrief(styleDescription);
  const maxW = asNumber(filters.max_width_cm) ?? hints.maxWidthCm;
  const maxD = asNumber(filters.max_depth_cm) ?? hints.maxDepthCm;
  const maxH = hints.maxHeightCm;
  const categories = asList(filters.categories).map((c) => c.toUpperCase());
  const types = categories.length ? categories : hints.types;
  const minPrice = asNumber(filters.min_price);
  const maxPrice = asNumber(filters.max_price);
  const colors = asList(filters.colors).map((c) => c.toLowerCase());

  const vector = await embedQuery(hints.vibe || styleDescription);
  const literal = `[${vector.map((x) => x.toFixed(6)).join(",")}]`;
  const match = (t: string[] | null) =>
    rest<MatchRow[]>("rpc/match_products", {
      method: "POST",
      body: JSON.stringify({
        query_embedding: literal, max_width_cm: maxW, max_depth_cm: maxD, max_height_cm: maxH,
        types: t, match_count: PAGE_SIZE * 2, model: EMBEDDING_MODEL, version: EMBEDDING_VERSION,
      }),
    });

  let matches = await match(types);
  let widened = false;
  if (!matches.length && types) {
    matches = await match(null);
    widened = true;
  }

  const rows = matches.length
    ? await rest<ProductRow[]>(`products?select=${PRODUCT_COLUMNS}&id=${encodeURIComponent(inList(matches.map((m) => m.id)))}`)
    : [];
  const byId = new Map(rows.map((r) => [r.id, r]));
  const reason = reasonFor(hints, maxW, maxD, widened);
  const products = matches
    .map((m) => ({ row: byId.get(m.id), sim: m.similarity }))
    .filter((x): x is { row: ProductRow; sim: number } => Boolean(x.row))
    .filter(({ row }) => {
      // real price if there is one, otherwise the middle of the estimate
      const price =
        row.price !== null ? Number(row.price)
        : row.est_price_low !== null && row.est_price_high !== null ? (Number(row.est_price_low) + Number(row.est_price_high)) / 2
        : null;
      return (
        (price === null || ((minPrice === null || price >= minPrice) && (maxPrice === null || price <= maxPrice))) &&
        (!colors.length || colors.some((c) => (row.color ?? "").toLowerCase().includes(c)))
      );
    })
    .slice(0, PAGE_SIZE)
    .map(({ row, sim }) => toCard(row, sim, reason));

  const searchId = `search_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
  return {
    search: {
      id: searchId,
      created_at: new Date().toISOString(),
      filters: { ...filters, max_width_cm: maxW, max_depth_cm: maxD, categories: types ?? [] },
      style_description: styleDescription,
      parsed: hints,
    },
    results: {
      search_id: searchId,
      products,
      pagination: { page: 1, per_page: PAGE_SIZE, total: products.length, total_pages: 1 },
    },
  };
}

/** A real catalogue product for /products/[id], or null if it isn't in Supabase (or Supabase isn't set up). */
export async function getCatalogProduct(id: string): Promise<FurnitureProduct | null> {
  if (!supabaseConfigured()) return null;
  try {
    const rows = await rest<ProductRow[]>(`products?select=${PRODUCT_COLUMNS}&id=eq.${encodeURIComponent(id)}&limit=1`, { revalidate: 3600 });
    return rows[0] ? toFurnitureProduct(toCard(rows[0], null, ""), 0) : null;
  } catch {
    return null;
  }
}

/** A few other products of the same kind, for "Nearby in the catalogue". */
export async function getRelatedCatalogProducts(product: FurnitureProduct, limit = 3): Promise<FurnitureProduct[]> {
  if (!supabaseConfigured()) return [];
  try {
    const type = product.category.toUpperCase();
    const rows = await rest<ProductRow[]>(
      `products?select=${PRODUCT_COLUMNS}&product_type=eq.${encodeURIComponent(type)}&id=neq.${encodeURIComponent(product.id)}` +
        `&image_urls=not.is.null&order=id&limit=${limit}`,
      { revalidate: 3600 },
    );
    return rows.map((r, i) => toFurnitureProduct(toCard(r, null, ""), i));
  } catch {
    return [];
  }
}
