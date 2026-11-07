import { forwardJson, JOB_ID, roomError } from "@/lib/server/room-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** GET /api/v1/visualizations/{jobId}  ->  {status, stage, info, result | error} */
export async function GET(_request: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  if (!JOB_ID.test(jobId)) return roomError("Unknown visualization.", 404);
  return forwardJson(`/api/v1/visualizations/${jobId}`, { method: "GET" }, 10_000);
}
