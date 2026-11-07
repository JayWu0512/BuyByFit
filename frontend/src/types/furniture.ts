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
  category: FurnitureCategory;
  styles: FurnitureStyle[];
  price: number;
  currency: "USD";
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
}

export type CatalogSort = "recommended" | "price-asc" | "price-desc" | "name-asc";

export interface CatalogFilters {
  query: string;
  selectedStyles: FurnitureStyle[];
  category: FurnitureCategory | "";
  maxWidth: string;
  maxDepth: string;
  maxHeight: string;
  minPrice: string;
  maxPrice: string;
  sort: CatalogSort;
}
