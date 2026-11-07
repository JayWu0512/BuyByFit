import { FurnitureProduct } from "@/types/furniture";

// The browser always talks to this Next.js route on its current origin. The
// route proxies to RECOMMENDATION_API_URL server-side, so a production browser
// never attempts to contact the developer's localhost or learns the backend URL.
const SEARCH_ENDPOINT = "/api/v1/searches";

const FALLBACK_IMAGE = "/images/hjem-travertine-table.jpg";

interface ApiDimensions {
  width: number | null;
  depth: number | null;
  height: number | null;
}

export interface ApiProductCard {
  id: string;
  name: string;
  brand: string | null;
  category: string | null;
  price: number | null;
  currency: string | null;
  price_estimate?: { low: number; high: number; basis: string | null } | null;
  image_url: string | null;
  image_urls?: string[];
  product_url: string | null;
  description?: string | null;
  material?: string | null;
  color?: string | null;
  caption?: string | null;
  model_3d_url?: string | null;
  ar_model_url?: string | null;
  dimensions_cm: ApiDimensions;
  style_tags: string[];
  match_score: number;
  match_reason: string;
}

interface ApiSearchResponse {
  search: { id: string };
  results: { products: ApiProductCard[] };
}

interface ApiErrorBody {
  error?: { message?: string };
}

function retailerFromUrl(url: string | null): string {
  if (!url) return "Online retailer";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Online retailer";
  }
}

export function toFurnitureProduct(card: ApiProductCard, index: number): FurnitureProduct {
  return {
    id: card.id,
    name: card.name,
    category: card.category ?? "other",
    styles: card.style_tags ?? [],
    price: card.price,
    currency: card.currency ?? "USD",
    priceEstimate: card.price === null && card.price_estimate ? card.price_estimate : undefined,
    brand: card.brand ?? "Unbranded",
    retailer: retailerFromUrl(card.product_url),
    description: card.description?.trim() ?? "",
    material: card.material?.trim() ?? "",
    widthCm: card.dimensions_cm?.width ?? 0,
    depthCm: card.dimensions_cm?.depth ?? 0,
    heightCm: card.dimensions_cm?.height ?? 0,
    imageUrl: card.image_url ?? FALLBACK_IMAGE,
    imageFit: card.image_url ? "contain" : "cover",
    imageAlt: card.name,
    imageUrls: card.image_urls?.filter((url) => Boolean(url.trim())),
    color: card.color?.trim() ?? undefined,
    caption: card.caption?.trim() ?? undefined,
    model3dUrl: card.model_3d_url?.trim() ?? undefined,
    arModelUrl: card.ar_model_url?.trim() ?? undefined,
    retailerUrl: card.product_url ?? undefined,
    displayOrder: index,
    matchScore: card.match_score,
  };
}

/** Calls POST /api/v1/searches and maps the response into FurnitureProduct cards, best match first. */
export async function searchFurniture(styleDescription: string): Promise<FurnitureProduct[]> {
  const response = await fetch(SEARCH_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filters: {}, style_description: styleDescription }),
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
    throw new Error(body?.error?.message ?? `Search failed (${response.status})`);
  }

  const data = (await response.json()) as ApiSearchResponse;
  return data.results.products.map(toFurnitureProduct);
}
