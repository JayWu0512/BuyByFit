import { forwardJson, JOB_ID, ROOM_ID, roomError } from "@/lib/server/room-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** POST /api/v1/rooms/{roomId}/visualizations/{jobId}/feedback  {verdict, issues, note}  ->  201 {ok} */
export async function POST(request: Request, { params }: { params: Promise<{ roomId: string; jobId: string }> }) {
  const { roomId, jobId } = await params;
  if (!ROOM_ID.test(roomId) || !JOB_ID.test(jobId)) return roomError("Unknown visualization.", 404);
  const body = await request.text();
  if (body.length > 4_000) return roomError("Feedback is too long.", 400);
  return forwardJson(
    `/api/v1/rooms/${roomId}/visualizations/${jobId}/feedback`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body },
    10_000,
  );
}
