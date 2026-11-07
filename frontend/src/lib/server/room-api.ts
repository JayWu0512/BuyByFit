import { NextResponse } from "next/server";

// Room visualization runs in the Python service (backend/app/api/v1/rooms.py): Gemini on Vertex plus
// true-size placement. The browser only talks to these same-origin routes; they forward server-side, so
// a production browser never learns the backend URL (same pattern as /api/v1/searches).
export function roomApiBase() {
  const base = (process.env.ROOM_API_URL ?? process.env.RECOMMENDATION_API_URL)?.trim().replace(/\/$/, "");
  return base || null;
}

export const ROOM_ID = /^[a-f0-9]{32}$/;
export const JOB_ID = /^[a-f0-9]{12}$/;
export const FILE_NAME = /^[a-z0-9_]{1,40}\.(jpg|png)$/;

export function roomError(message: string, status: number) {
  return NextResponse.json({ error: { message, status } }, { status });
}

export function notConfigured() {
  return roomError("Room visualization needs the BuyByFit Python service: set ROOM_API_URL.", 503);
}

/** Forward to the Python service and pass its JSON answer (and status) straight back. */
export async function forwardJson(path: string, init: RequestInit, timeoutMs: number) {
  const base = roomApiBase();
  if (!base) return notConfigured();
  try {
    const response = await fetch(`${base}${path}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(timeoutMs) });
    const body = await response.json().catch(() => ({ error: { message: "Invalid response from the room service" } }));
    return NextResponse.json(body, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return roomError("The room visualization service is not reachable right now.", 502);
  }
}
