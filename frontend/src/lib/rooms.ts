import { FurnitureProduct } from "@/types/furniture";

// Browser side of room visualization. Everything goes through same-origin /api/v1 routes, which forward to
// the Python service (see src/lib/server/room-api.ts and backend/app/api/v1/rooms.py).

export interface RoomScene {
  room_id: string;
  photo_url: string;
  scene: { pitch_deg: number; source: "sensors" | "defaults"; room_cm?: { width: number; depth: number } };
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
  /** Missing on results saved in the tab before feedback existed. */
  job_id?: string;
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
  /** Our fine-tuned design reviewer's verdict on the render; null when the reviewer is off or failed. */
  review?: DesignReview | null;
  timings_s: Record<string, number>;
}

export interface DesignReview {
  overall: number;
  scores: Partial<Record<string, number>>;
  issues: string[];
  fixes: string[];
  verdict: string;
}

export type VisualizationStage = "queued" | "design" | "place" | "render" | "verify" | "review" | "done";

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

export async function createRoom(
  photo: Blob,
  pitchDeg: number | null,
  roomWidthCm: number | null,
  roomDepthCm: number | null,
): Promise<RoomScene> {
  const form = new FormData();
  form.append("photo", photo, "room.jpg");
  if (pitchDeg !== null) form.append("pitch_deg", String(Math.round(pitchDeg * 10) / 10));
  if (roomWidthCm !== null && roomDepthCm !== null) {
    form.append("room_width_cm", String(roomWidthCm));
    form.append("room_depth_cm", String(roomDepthCm));
  }
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

/** What a person can flag on a restyle. Ids match `Issue` in backend/app/api/v1/rooms.py. */
export const FEEDBACK_ISSUES = [
  { id: "removed_existing", label: "Removed something I have" },
  { id: "missing_piece", label: "Missing something I asked for" },
  { id: "floating", label: "Furniture floating" },
  { id: "wrong_size", label: "Wrong size" },
  { id: "wrong_product", label: "Doesn't look like the product" },
  { id: "wrong_orientation", label: "Facing the wrong way" },
  { id: "blocks_path", label: "Blocks a door or walkway" },
  { id: "room_changed", label: "Changed my walls or windows" },
  { id: "artifacts", label: "Glitches or leftover boxes" },
  { id: "off_brief", label: "Not the style I asked for" },
  { id: "unrealistic", label: "Looks fake" },
] as const;

export type FeedbackIssue = (typeof FEEDBACK_ISSUES)[number]["id"];

export interface VisualizationFeedback {
  verdict: "good" | "bad";
  issues: FeedbackIssue[];
  note: string;
}

export async function sendFeedback(roomId: string, jobId: string, feedback: VisualizationFeedback) {
  const response = await fetch(`/api/v1/rooms/${roomId}/visualizations/${jobId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(feedback),
  });
  return asJson<{ ok: true }>(response);
}

export async function getVisualization(jobId: string): Promise<VisualizationJob> {
  return asJson<VisualizationJob>(await fetch(`/api/v1/visualizations/${jobId}`, { cache: "no-store" }));
}
