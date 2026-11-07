import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const REQUEST_TIMEOUT_MS = 12_000;

function errorResponse(message: string, status: number) {
  return NextResponse.json({ error: { message, status } }, { status });
}

function backendSearchUrl() {
  const baseUrl = process.env.RECOMMENDATION_API_URL?.trim().replace(/\/$/, "");
  return baseUrl ? `${baseUrl}/api/v1/searches` : null;
}

/**
 * Same-origin browser endpoint for room-brief searches.
 *
 * The Python recommendation service stays behind this route: configure its
 * public deployment URL as RECOMMENDATION_API_URL in local/Vercel server env.
 */
export async function POST(request: Request) {
  const targetUrl = backendSearchUrl();
  if (!targetUrl) {
    return errorResponse("The recommendation service is not configured for this environment.", 503);
  }

  let requestBody: unknown;
  try {
    requestBody = await request.json();
  } catch {
    return errorResponse("Request body must be valid JSON.", 400);
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(targetUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
      cache: "no-store",
      signal: controller.signal,
    });
    const responseBody = await response.text();

    return new NextResponse(responseBody, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      return errorResponse("The recommendation service took too long to respond. Please try again.", 504);
    }
    return errorResponse("The recommendation service could not be reached. Please try again.", 502);
  } finally {
    clearTimeout(timeout);
  }
}
