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
      (minPrice === undefined || product.price >= minPrice) &&
      (maxPrice === undefined || product.price <= maxPrice)
    );
  });

  return [...filtered].sort((a, b) => {
    if (filters.sort === "price-asc") return a.price - b.price;
    if (filters.sort === "price-desc") return b.price - a.price;
    if (filters.sort === "name-asc") return a.name.localeCompare(b.name);
    return a.displayOrder - b.displayOrder;
  });
}

export function formatCurrency(price: number, currency: FurnitureProduct["currency"] = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(price);
}

export function formatDimensions(product: Pick<FurnitureProduct, "widthCm" | "depthCm" | "heightCm">) {
  return `${product.widthCm}W × ${product.depthCm}D × ${product.heightCm}H cm`;
}
