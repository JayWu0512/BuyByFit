import { forwardJson, ROOM_ID, roomError } from "@/lib/server/room-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/v1/rooms/{roomId}/visualizations  {brief, products}  ->  202 {job_id} */
export async function POST(request: Request, { params }: { params: Promise<{ roomId: string }> }) {
  const { roomId } = await params;
  if (!ROOM_ID.test(roomId)) return roomError("Unknown room.", 404);
  const body = await request.text();
  if (body.length > 200_000) return roomError("Too many products.", 400);
  return forwardJson(
    `/api/v1/rooms/${roomId}/visualizations`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body },
    15_000,
  );
}
