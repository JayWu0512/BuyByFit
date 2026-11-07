import { furnitureProducts } from "@/lib/mock-furniture";
import { CatalogFilters, FurnitureProduct } from "@/types/furniture";

export const emptyFilters: CatalogFilters = {
  query: "",
  selectedStyles: [],
  category: "",
  maxWidth: "",
  maxDepth: "",
  maxHeight: "",
  minPrice: "",
  maxPrice: "",
  sort: "recommended",
};

const parseOptionalNumber = (value: string) => {
  const number = Number(value);
  return value.trim() !== "" && Number.isFinite(number) && number >= 0 ? number : undefined;
};

export function getFurnitureById(id: string) {
  return furnitureProducts.find((product) => product.id === id);
}

export function getRelatedFurniture(product: FurnitureProduct, limit = 3) {
  return furnitureProducts
    .filter((candidate) => candidate.id !== product.id)
    .sort((a, b) => {
      const aScore = Number(a.category === product.category) + a.styles.filter((style) => product.styles.includes(style)).length;
      const bScore = Number(b.category === product.category) + b.styles.filter((style) => product.styles.includes(style)).length;
      return bScore - aScore || a.displayOrder - b.displayOrder;
    })
    .slice(0, limit);
}

export function filterAndSortFurniture(
  products: FurnitureProduct[] = furnitureProducts,
  filters: CatalogFilters,
) {
  const maxWidth = parseOptionalNumber(filters.maxWidth);
  const maxDepth = parseOptionalNumber(filters.maxDepth);
  const maxHeight = parseOptionalNumber(filters.maxHeight);
  const minPrice = parseOptionalNumber(filters.minPrice);
  const maxPrice = parseOptionalNumber(filters.maxPrice);
  const query = filters.query.trim().toLowerCase();

  const filtered = products.filter((product) => {
    const searchable = [
      product.name,
      product.category,
      product.brand,
      product.retailer,
      product.description,
      product.material,
      ...product.styles,
    ]
      .join(" ")
      .toLowerCase();

    return (
      (!query || searchable.includes(query)) &&
      (!filters.category || product.category === filters.category) &&
      (filters.selectedStyles.length === 0 || filters.selectedStyles.some((style) => product.styles.includes(style))) &&
      (maxWidth === undefined || product.widthCm <= maxWidth) &&
      (maxDepth === undefined || product.depthCm <= maxDepth) &&
      (maxHeight === undefined || product.heightCm <= maxHeight) &&
      (minPrice === undefined || (effectivePrice(product) ?? -1) >= minPrice) &&
      (maxPrice === undefined || (effectivePrice(product) ?? Infinity) <= maxPrice)
    );
  });

  return [...filtered].sort((a, b) => {
    if (filters.sort === "price-asc") return comparePrice(a, b, "asc");
    if (filters.sort === "price-desc") return comparePrice(a, b, "desc");
    if (filters.sort === "name-asc") return a.name.localeCompare(b.name);
    return a.displayOrder - b.displayOrder;
  });
}

/** Real price if known, otherwise the middle of the estimated range, otherwise null. Used for sorting and filtering. */
export function effectivePrice(product: Pick<FurnitureProduct, "price" | "priceEstimate">): number | null {
  if (product.price !== null) return product.price;
  if (product.priceEstimate) return (product.priceEstimate.low + product.priceEstimate.high) / 2;
  return null;
}

/** Products with no price and no estimate always sort last, regardless of direction. */
export function comparePrice(a: FurnitureProduct, b: FurnitureProduct, direction: "asc" | "desc") {
  const pa = effectivePrice(a);
  const pb = effectivePrice(b);
  if (pa === null && pb === null) return 0;
  if (pa === null) return 1;
  if (pb === null) return -1;
  return direction === "asc" ? pa - pb : pb - pa;
}

/** What to print for a product's price: real price, a labelled estimate, or "Price unavailable". */
export function priceLabel(product: Pick<FurnitureProduct, "price" | "currency" | "priceEstimate">) {
  const currency = product.currency ?? "USD";
  if (product.price !== null) return { text: formatCurrency(product.price, currency), kind: "real" as const };
  if (product.priceEstimate) {
    const { low, high } = product.priceEstimate;
    return { text: `Est. ${formatCurrency(low, currency)}–${formatCurrency(high, currency).replace(/^[^\d]+/, "")}`, kind: "estimate" as const };
  }
  return { text: "Price unavailable", kind: "none" as const };
}

export function formatCurrency(price: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(price);
}

export function formatDimensions(product: Pick<FurnitureProduct, "widthCm" | "depthCm" | "heightCm">) {
  return `${product.widthCm}W × ${product.depthCm}D × ${product.heightCm}H cm`;
}

/** Turns a raw catalog value (e.g. "home_furniture_and_decor") into a display label. No-op on already-formatted strings like "Sofa". */
export function formatLabel(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Sanitizes a raw catalog value into a safe single CSS class token. */
export function toClassToken(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-");
}
