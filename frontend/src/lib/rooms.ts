import { FurnitureProduct } from "@/types/furniture";

// Browser side of room visualization. Everything goes through same-origin /api/v1 routes, which forward to
// the Python service (see src/lib/server/room-api.ts and backend/app/api/v1/rooms.py).

export interface RoomScene {
  room_id: string;
  photo_url: string;
  scene: { pitch_deg: number; source: "sensors" | "defaults" };
}

export interface VisualizedProduct {
  id: string;
  name: string;
  category: string | null;
  image_url: string | null;
  product_url: string | null;
  size_cm: string;
}

export interface VisualizationResult {
  vibe: string;
  photo_url: string;
  render_url: string;
  items: Array<{
    role: string;
    product: VisualizedProduct;
    /** Where the piece is in the render: [ymin, xmin, ymax, xmax] in 0-1000. */
    box_2d: [number, number, number, number];
    placed_at_true_size: boolean;
    alternatives: VisualizedProduct[];
  }>;
  styling: string[];
  timings_s: Record<string, number>;
}

export type VisualizationStage = "queued" | "design" | "place" | "render" | "verify" | "done";

export interface VisualizationJob {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  stage: VisualizationStage;
  info: { guide_url?: string; vibe?: string };
  elapsed_s: number;
  result?: VisualizationResult;
  error?: string;
}

async function asJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => null)) as (T & { error?: { message?: string } }) | null;
  if (!response.ok || !body) throw new Error(body?.error?.message ?? `Request failed (${response.status})`);
  return body;
}

export async function createRoom(photo: Blob, pitchDeg: number | null): Promise<RoomScene> {
  const form = new FormData();
  form.append("photo", photo, "room.jpg");
  if (pitchDeg !== null) form.append("pitch_deg", String(Math.round(pitchDeg * 10) / 10));
  return asJson<RoomScene>(await fetch("/api/v1/rooms", { method: "POST", body: form }));
}

/** Only products with real dimensions can be placed at true size; demo images aren't sent as product photos. */
export function toVisualizationProducts(products: FurnitureProduct[]) {
  return products
    .filter((p) => p.widthCm > 1 && p.depthCm > 0 && p.heightCm > 0)
    .slice(0, 24)
    .map((p) => ({
      id: p.id,
      name: p.name,
      category: p.category || null,
      width_cm: p.widthCm,
      depth_cm: p.depthCm,
      height_cm: p.heightCm,
      image_url: p.imageUrl.startsWith("https://") ? p.imageUrl : null,
      product_url: p.retailerUrl ?? null,
    }));
}

export async function startVisualization(roomId: string, brief: string, products: FurnitureProduct[]) {
  const response = await fetch(`/api/v1/rooms/${roomId}/visualizations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ brief, products: toVisualizationProducts(products) }),
  });
  return asJson<{ job_id: string }>(response);
}

export async function getVisualization(jobId: string): Promise<VisualizationJob> {
  return asJson<VisualizationJob>(await fetch(`/api/v1/visualizations/${jobId}`, { cache: "no-store" }));
}
