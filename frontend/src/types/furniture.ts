// Suggested defaults for curated UI (e.g. starter filter chips). Not an
// exhaustive list -- the real catalog's category/style values are open-ended,
// so FurnitureProduct below accepts any string rather than enforcing these.
export const categories = [
  "Sofa",
  "Chair",
  "Table",
  "Bed",
  "Storage",
  "Lighting",
  "Other",
] as const;

export const styles = [
  "Scandinavian",
  "Japandi",
  "Modern",
  "Boho",
  "Industrial",
] as const;

export type FurnitureCategory = (typeof categories)[number];
export type FurnitureStyle = (typeof styles)[number];

export interface FurnitureProduct {
  id: string;
  name: string;
  category: string;
  styles: string[];
  // Nullable because live search results (real catalog) often lack pricing --
  // the ABO dataset backing it has no retail price for most items.
  price: number | null;
  currency: string | null;
  brand: string;
  retailer: string;
  description: string;
  material: string;
  widthCm: number;
  depthCm: number;
  heightCm: number;
  imageUrl: string;
  imageAlt: string;
  retailerUrl?: string;
  displayOrder: number;
  imagePosition?: string;
  // Set only on live search results (ranked by the recommendation service);
  // absent on the static mock catalogue.
  matchScore?: number;
}

export type CatalogSort = "recommended" | "price-asc" | "price-desc" | "name-asc";

export interface CatalogFilters {
  query: string;
  selectedStyles: string[];
  category: string;
  maxWidth: string;
  maxDepth: string;
  maxHeight: string;
  minPrice: string;
  maxPrice: string;
  sort: CatalogSort;
}
