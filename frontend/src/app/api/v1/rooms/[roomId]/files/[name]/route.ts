import { FILE_NAME, notConfigured, ROOM_ID, roomApiBase, roomError } from "@/lib/server/room-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/v1/rooms/{roomId}/files/{name}  ->  the room photo, placement guide or render (image bytes) */
export async function GET(_request: Request, { params }: { params: Promise<{ roomId: string; name: string }> }) {
  const { roomId, name } = await params;
  if (!ROOM_ID.test(roomId) || !FILE_NAME.test(name)) return roomError("File not found.", 404);
  const base = roomApiBase();
  if (!base) return notConfigured();
  try {
    const response = await fetch(`${base}/api/v1/rooms/${roomId}/files/${name}`, { signal: AbortSignal.timeout(20_000) });
    if (!response.ok) return roomError("File not found.", response.status === 404 ? 404 : 502);
    return new Response(response.body, {
      headers: {
        "Content-Type": name.endsWith(".png") ? "image/png" : "image/jpeg",
        "Cache-Control": "private, max-age=3600",
      },
    });
  } catch {
    return roomError("The room visualization service is not reachable right now.", 502);
  }
}
