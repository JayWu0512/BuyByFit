import { forwardJson, roomError } from "@/lib/server/room-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_PHOTO_BYTES = 8 * 1024 * 1024; // the page sends a ~1280 px JPEG, well under this

/** POST /api/v1/rooms  (multipart: photo, optional pitch_deg)  ->  {room_id, scene, photo_url} */
export async function POST(request: Request) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return roomError("Send the photo as multipart form data.", 400);
  }
  const photo = form.get("photo");
  if (!(photo instanceof Blob) || photo.size === 0 || photo.size > MAX_PHOTO_BYTES) {
    return roomError("Add a photo of your room (up to 8 MB).", 400);
  }

  const upstream = new FormData();
  upstream.append("photo", photo, "room.jpg");
  const pitch = Number(form.get("pitch_deg"));
  if (form.get("pitch_deg") !== null && Number.isFinite(pitch)) upstream.append("pitch_deg", String(pitch));

  return forwardJson("/api/v1/rooms", { method: "POST", body: upstream }, 30_000);
}
