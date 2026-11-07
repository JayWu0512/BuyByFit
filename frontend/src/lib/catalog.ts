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
      (minPrice === undefined || (product.price !== null && product.price >= minPrice)) &&
      (maxPrice === undefined || (product.price !== null && product.price <= maxPrice))
    );
  });

  return [...filtered].sort((a, b) => {
    if (filters.sort === "price-asc") return comparePrice(a, b, "asc");
    if (filters.sort === "price-desc") return comparePrice(a, b, "desc");
    if (filters.sort === "name-asc") return a.name.localeCompare(b.name);
    return a.displayOrder - b.displayOrder;
  });
}

/** Null prices (common on live search results) always sort last, regardless of direction. */
export function comparePrice(a: FurnitureProduct, b: FurnitureProduct, direction: "asc" | "desc") {
  if (a.price === null && b.price === null) return 0;
  if (a.price === null) return 1;
  if (b.price === null) return -1;
  return direction === "asc" ? a.price - b.price : b.price - a.price;
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
