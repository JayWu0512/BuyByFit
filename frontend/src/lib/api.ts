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

interface ApiProductCard {
  id: string;
  name: string;
  brand: string | null;
  category: string | null;
  price: number | null;
  currency: string | null;
  image_url: string | null;
  product_url: string | null;
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

function toFurnitureProduct(card: ApiProductCard, index: number): FurnitureProduct {
  return {
    id: card.id,
    name: card.name,
    category: card.category ?? "other",
    styles: card.style_tags ?? [],
    price: card.price,
    currency: card.currency ?? "USD",
    brand: card.brand ?? "Unbranded",
    retailer: retailerFromUrl(card.product_url),
    description: "",
    material: "",
    widthCm: card.dimensions_cm?.width ?? 0,
    depthCm: card.dimensions_cm?.depth ?? 0,
    heightCm: card.dimensions_cm?.height ?? 0,
    imageUrl: card.image_url ?? FALLBACK_IMAGE,
    imageAlt: card.name,
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
