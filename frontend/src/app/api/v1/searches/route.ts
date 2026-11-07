import { NextResponse } from "next/server";

import { furnitureProducts } from "@/lib/mock-furniture";
import { searchCatalog, supabaseConfigured } from "@/lib/server/supabase";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const REQUEST_TIMEOUT_MS = 12_000;

interface SearchFilters {
  categories?: unknown;
  colors?: unknown;
  min_price?: unknown;
  max_price?: unknown;
  max_width_cm?: unknown;
  max_depth_cm?: unknown;
}

interface SearchRequest {
  filters?: SearchFilters;
  style_description?: unknown;
}

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: { message, status } }, { status });
}

function backendSearchUrl() {
  const baseUrl = process.env.RECOMMENDATION_API_URL?.trim().replace(/\/$/, "");
  return baseUrl ? `${baseUrl}/api/v1/searches` : null;
}

function asStringList(value: unknown) {
  const values = Array.isArray(value) ? value : typeof value === "string" ? [value] : [];
  return values.map((item) => String(item).trim().toLowerCase()).filter(Boolean);
}

function asOptionalNumber(value: unknown) {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) && number >= 0 ? number : undefined;
}

function words(value: string) {
  return new Set(value.toLowerCase().match(/[a-z0-9]+/g) ?? []);
}

function productSearchText(product: (typeof furnitureProducts)[number]) {
  return [product.name, product.brand, product.category, product.description, product.material, ...product.styles].join(" ").toLowerCase();
}

function productCard(product: (typeof furnitureProducts)[number], score: number) {
  return {
    id: product.id,
    name: product.name,
    brand: product.brand,
    category: product.category,
    price: product.price,
    currency: product.currency,
    image_url: product.imageUrl,
    image_urls: [product.imageUrl],
    product_url: product.retailerUrl ?? null,
    description: product.description,
    material: product.material,
    color: null,
    caption: null,
    model_3d_url: null,
    ar_model_url: null,
    dimensions_cm: { width: product.widthCm, depth: product.depthCm, height: product.heightCm },
    style_tags: product.styles,
    match_score: score,
    match_reason: "Matches the feeling and practical limits in your room brief.",
  };
}

function localRecommendation(payload: SearchRequest) {
  const description = typeof payload.style_description === "string" ? payload.style_description.trim() : "";
  if (!description) return null;

  const filters = payload.filters ?? {};
  const queryWords = words(description);
  const categories = asStringList(filters.categories);
  const colors = asStringList(filters.colors);
  const minPrice = asOptionalNumber(filters.min_price);
  const maxPrice = asOptionalNumber(filters.max_price);
  const maxWidth = asOptionalNumber(filters.max_width_cm);
  const maxDepth = asOptionalNumber(filters.max_depth_cm);

  const products = furnitureProducts
    .filter((product) => {
      const searchable = productSearchText(product);
      return (
        (categories.length === 0 || categories.includes(product.category.toLowerCase())) &&
        (colors.length === 0 || colors.some((color) => searchable.includes(color))) &&
        (minPrice === undefined || product.price === null || product.price >= minPrice) &&
        (maxPrice === undefined || product.price === null || product.price <= maxPrice) &&
        (maxWidth === undefined || product.widthCm <= maxWidth) &&
        (maxDepth === undefined || product.depthCm <= maxDepth)
      );
    })
    .map((product) => {
      const searchableWords = words(productSearchText(product));
      const matchedWords = [...queryWords].filter((word) => searchableWords.has(word)).length;
      const score = Math.min(99, 54 + matchedWords * 9 + product.styles.filter((style) => queryWords.has(style.toLowerCase())).length * 8);
      return { product, score };
    })
    .sort((a, b) => b.score - a.score || a.product.displayOrder - b.product.displayOrder)
    .map(({ product, score }) => productCard(product, score));

  return {
    search: {
      id: `search_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`,
      created_at: new Date().toISOString(),
      filters,
      style_description: description,
    },
    results: {
      search_id: "local-demo",
      products,
      pagination: { page: 1, per_page: 12, total: products.length, total_pages: 1 },
    },
  };
}

async function proxyToRecommendationService(targetUrl: string, requestBody: SearchRequest) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(targetUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
      cache: "no-store",
      signal: controller.signal,
    });
    const responseBody = await response.text();

    return new NextResponse(responseBody, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return errorResponse("The recommendation service took too long to respond. Please try again.", 504);
    }
    return errorResponse("The recommendation service could not be reached. Please try again.", 502);
  } finally {
    clearTimeout(timeout);
  }
}

/**
 * Same-origin browser endpoint for room-brief searches. Picks the first backend that's configured:
 *
 * 1. RECOMMENDATION_API_URL: proxy to the Python/FastAPI recommendation service.
 * 2. SUPABASE_URL + SUPABASE_ANON_KEY: semantic search on the real catalogue in Supabase, over its
 *    REST API (embeds the brief here, then calls the `match_products` pgvector function).
 * 3. Neither: the local fictional catalogue, so the MVP always works.
 *
 * If Supabase fails, the route falls back to the local catalogue rather than showing an error.
 * The `x-buybyfit-source` header says which path answered.
 */
export async function POST(request: Request) {
  let requestBody: SearchRequest;
  try {
    requestBody = (await request.json()) as SearchRequest;
  } catch {
    return errorResponse("Request body must be valid JSON.", 400);
  }

  const targetUrl = backendSearchUrl();
  if (targetUrl) return proxyToRecommendationService(targetUrl, requestBody);

  const description = typeof requestBody.style_description === "string" ? requestBody.style_description.trim() : "";
  if (!description) return errorResponse("Tell us a little about the room before searching.", 400);

  if (supabaseConfigured()) {
    try {
      const result = await searchCatalog(description, requestBody.filters ?? {});
      return NextResponse.json(result, { status: 201, headers: { "x-buybyfit-source": "supabase" } });
    } catch (error) {
      console.error("Supabase search failed, using the local catalogue:", error);
    }
  }

  const result = localRecommendation(requestBody);
  if (!result) return errorResponse("Tell us a little about the room before searching.", 400);

  return NextResponse.json(result, { status: 201, headers: { "x-buybyfit-source": "local-demo" } });
}
