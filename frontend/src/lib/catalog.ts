import { furnitureProducts } from "@/lib/mock-furniture";
import { FurnitureProduct } from "@/types/furniture";

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
