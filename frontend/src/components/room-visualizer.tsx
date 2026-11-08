"use client";

/* eslint-disable @next/next/no-img-element -- room photos and renders come from our own proxy routes */

import Link from "next/link";
import { ChangeEvent, useEffect, useRef, useState } from "react";

import {
  createRoom,
  FEEDBACK_ISSUES,
  FeedbackIssue,
  getVisualization,
  sendFeedback,
  startVisualization,
  VisualizationJob,
  VisualizationResult,
} from "@/lib/rooms";
import { FurnitureProduct } from "@/types/furniture";

interface RoomVisualizerProps {
  /** The room brief the user searched with: it also steers the restyle. */
  brief: string;
  /** The search results already on screen: the service picks from these. */
  products: FurnitureProduct[];
}

type Phase = "idle" | "camera" | "uploading" | "working" | "done" | "error";

const stages: Array<{ key: string; label: string }> = [
  { key: "design", label: "Reading your room and choosing pieces" },
  { key: "place", label: "Placing them at their real size" },
  { key: "render", label: "Rendering your room" },
  { key: "verify", label: "Checking sizes and positions" },
  { key: "review", label: "Our expert AI is refining the design" },
];

const POLL_MS = 2500;
const LONG_SIDE = 1280;

type OrientationPermission = { requestPermission?: () => Promise<"granted" | "denied"> };

/** Marker per piece (percent of the image): centred just above the top edge of its box, so it never covers
 *  the piece itself (CSS lifts it above this point). Nudged sideways when two markers would touch. */
function markerPositions(items: VisualizationResult["items"]) {
  const placed: Array<{ item: VisualizationResult["items"][number]; left: number; top: number }> = [];
  for (const item of items) {
    const [y0, x0, y1, x1] = item.box_2d;
    let left = (x0 + x1) / 20;
    const top = Math.max(4, y0 / 10);
    while (placed.some((p) => Math.abs(p.left - left) < 4.5 && Math.abs(p.top - top) < 4.5) && left < 96) left += 4.5;
    placed.push({ item, left, top });
  }
  return placed;
}

// Kept for the browser tab (like the search itself), so opening a product page and coming back shows the same
// picture, or keeps following a restyle that is still rendering.
const roomSessionKey = "buybyfit-room-visualization";

interface SavedRoom {
  brief: string;
  roomId: string;
  jobId?: string;
  result?: VisualizationResult;
}

function loadRoom(brief: string): SavedRoom | null {
  try {
    const saved = JSON.parse(sessionStorage.getItem(roomSessionKey) ?? "null") as SavedRoom | null;
    return saved && saved.brief === brief && typeof saved.roomId === "string" ? saved : null;
  } catch {
    return null;
  }
}

function saveRoom(saved: SavedRoom | null) {
  try {
    if (saved) sessionStorage.setItem(roomSessionKey, JSON.stringify(saved));
    else sessionStorage.removeItem(roomSessionKey);
  } catch {
    // Still works without session storage; the picture just isn't kept across pages.
  }
}

const feedbackKey = (jobId: string) => `buybyfit-feedback-${jobId}`;

/** "How does this look?": a person's verdict on one restyle. These labels train the reviewer model. */
function RestyleFeedback({ roomId, jobId }: { roomId: string; jobId: string }) {
  // Only rendered after a result exists (client side), so reading session storage here is safe.
  const [state, setState] = useState<"ask" | "issues" | "sent">(() => {
    try {
      return sessionStorage.getItem(feedbackKey(jobId)) ? "sent" : "ask";
    } catch {
      return "ask";
    }
  });
  const [sending, setSending] = useState(false);
  const [issues, setIssues] = useState<FeedbackIssue[]>([]);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const submit = async (verdict: "good" | "bad") => {
    setSending(true);
    setError("");
    try {
      await sendFeedback(roomId, jobId, { verdict, issues: verdict === "bad" ? issues : [], note: note.trim() });
      try {
        sessionStorage.setItem(feedbackKey(jobId), verdict);
      } catch {
        // Only stops us from asking twice in this tab.
      }
      setState("sent");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send that.");
    } finally {
      setSending(false);
    }
  };

  const toggle = (id: FeedbackIssue) =>
    setIssues((current) => (current.includes(id) ? current.filter((i) => i !== id) : [...current, id]));

  if (state === "sent") {
    return (
      <p className="rv-feedback-thanks" role="status">
        Thanks, that helps us get these right.
      </p>
    );
  }

  return (
    <div className="rv-feedback">
      {state === "ask" ? (
        <div className="rv-feedback-ask">
          <p>How does this look?</p>
          <button className="button rv-light" disabled={sending} onClick={() => submit("good")} type="button">
            {sending ? "Sending…" : "Looks right"}
          </button>
          <button className="button rv-light" disabled={sending} onClick={() => setState("issues")} type="button">
            Something&apos;s off
          </button>
        </div>
      ) : (
        <fieldset className="rv-feedback-issues" disabled={sending}>
          <legend>What&apos;s off? Pick any that apply.</legend>
          <div className="rv-feedback-chips">
            {FEEDBACK_ISSUES.map((issue) => (
              <button
                aria-pressed={issues.includes(issue.id)}
                className={issues.includes(issue.id) ? "is-on" : undefined}
                key={issue.id}
                onClick={() => toggle(issue.id)}
                type="button"
              >
                {issue.label}
              </button>
            ))}
          </div>
          <label className="rv-feedback-note">
            <span>Anything else? (optional)</span>
            <textarea
              maxLength={500}
              onChange={(event) => setNote(event.target.value)}
              placeholder="e.g. it removed my bed"
              rows={2}
              value={note}
            />
          </label>
          <div className="rv-feedback-actions">
            <button
              className="button button-dark"
              disabled={issues.length === 0 && !note.trim()}
              onClick={() => submit("bad")}
              type="button"
            >
              {sending ? "Sending…" : "Send"}
            </button>
            <button className="text-button" onClick={() => setState("ask")} type="button">
              Cancel
            </button>
          </div>
        </fieldset>
      )}
      {error ? (
        <p className="room-visualizer-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function productHref(id: string) {
  return `/products/${encodeURIComponent(id)}`;
}

/** JPEG of an image or video frame, longest side <= 1280 px (keeps uploads small). */
async function toJpeg(source: CanvasImageSource, width: number, height: number): Promise<Blob> {
  const scale = Math.min(1, LONG_SIDE / Math.max(width, height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(width * scale);
  canvas.height = Math.round(height * scale);
  canvas.getContext("2d")?.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Could not read the photo"))), "image/jpeg", 0.9),
  );
}

export function RoomVisualizer({ brief, products }: RoomVisualizerProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<VisualizationJob | null>(null);
  const [result, setResult] = useState<VisualizationResult | null>(null);
  const [error, setError] = useState("");
  const [tiltLabel, setTiltLabel] = useState("");
  const [split, setSplit] = useState(50);
  const [view, setView] = useState<"before" | "compare" | "after">("after");
  const [active, setActive] = useState<number | null>(null);
  const [showMarkers, setShowMarkers] = useState(true);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [widthCm, setWidthCm] = useState("");
  const [depthCm, setDepthCm] = useState("");
  const stageRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const betaRef = useRef<number | null>(null);
  const cancelledRef = useRef(false);
  const followRunRef = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);

  const placeable = products.filter((p) => p.widthCm > 1 && p.depthCm > 0 && p.heightCm > 0).length;

  useEffect(() => {
    cancelledRef.current = false;
    // Coming back from a product page: show the saved picture, or keep following the restyle.
    const saved = loadRoom(brief);
    if (saved?.result) {
      setRoomId(saved.roomId);
      setResult(saved.result);
      setPhase("done");
    } else if (saved?.jobId) {
      setRoomId(saved.roomId);
      setPhase("working");
      follow(saved.roomId, saved.jobId).catch((err) => {
        saveRoom(null);
        fail(err instanceof Error ? err.message : "The visualization failed.");
      });
    }
    return () => {
      cancelledRef.current = true;
      stopCamera();
    };
    // Runs once per mount; `brief` comes from the restored search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Attach the stream once the <video> exists (it only renders in the camera phase). Doing this in an
  // effect, not a timer, avoids a black preview on iPhone Safari.
  useEffect(() => {
    const video = videoRef.current;
    const stream = streamRef.current;
    if (phase !== "camera" || !video || !stream) return;
    video.srcObject = stream;
    video.play().catch(() => setError("Tap the preview to start the camera."));
  }, [phase]);

  // Stable reference so removeEventListener matches the listener we added.
  const onOrientation = useRef((event: DeviceOrientationEvent) => {
    if (event.beta === null) return;
    betaRef.current = event.beta;
    const down = Math.round(90 - event.beta);
    setTiltLabel(down > 2 ? `Tilted ${down}° down` : down < -2 ? `Tilted ${-down}° up` : "Level");
  }).current;

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    window.removeEventListener("deviceorientation", onOrientation);
  }

  const fail = (message: string) => {
    stopCamera();
    setError(message);
    setPhase("error");
  };

  const openCamera = async () => {
    setError("");
    // iPhone asks for motion permission from a tap; the tilt makes the true-size placement exact.
    try {
      const permission = (DeviceOrientationEvent as unknown as OrientationPermission).requestPermission;
      if (typeof permission === "function") await permission();
    } catch {
      // Optional: without the tilt we fall back to a typical camera angle.
    }
    window.addEventListener("deviceorientation", onOrientation);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1440 } },
      });
      streamRef.current = stream;
      setPhase("camera"); // the effect above attaches the stream to the <video>
    } catch (err) {
      window.removeEventListener("deviceorientation", onOrientation);
      const name = err instanceof DOMException ? err.name : "";
      setError(
        name === "NotAllowedError"
          ? "Camera permission was denied. Allow camera access for this site in your browser settings, or upload a photo."
          : !window.isSecureContext
            ? "The camera needs a secure (https) page. Upload a photo instead."
            : "The camera isn't available here. Upload a photo of your room instead.",
      );
    }
  };

  const takePhoto = async () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      setError("The camera isn't showing a picture yet. Wait a second, or tap the preview, then try again.");
      return;
    }
    setError("");
    const blob = await toJpeg(video, video.videoWidth, video.videoHeight);
    const pitch = betaRef.current === null ? null : Math.max(-60, Math.min(89, 90 - betaRef.current));
    stopCamera();
    await run(blob, pitch);
  };

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      await run(await toJpeg(bitmap, bitmap.width, bitmap.height), null);
    } catch {
      fail("That file couldn't be read as a photo.");
    }
  };

  async function run(photo: Blob, pitch: number | null) {
    setPhase("uploading");
    setResult(null);
    setJob(null);
    const width = widthCm.trim() && Number.isFinite(Number(widthCm)) ? Number(widthCm) : null;
    const depth = depthCm.trim() && Number.isFinite(Number(depthCm)) ? Number(depthCm) : null;
    try {
      const room = await createRoom(photo, pitch, width, depth);
      setRoomId(room.room_id);
      await visualize(room.room_id);
    } catch (err) {
      fail(err instanceof Error ? err.message : "The visualization failed.");
    }
  }

  /** Start a restyle of an uploaded room and follow it until it's done. */
  async function visualize(id: string) {
    const { job_id } = await startVisualization(id, brief, products);
    saveRoom({ brief, roomId: id, jobId: job_id });
    setPhase("working");
    await follow(id, job_id);
  }

  async function follow(id: string, jobId: string) {
    const run = ++followRunRef.current; // only the newest loop keeps polling
    while (!cancelledRef.current && followRunRef.current === run) {
      await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
      // Left the page (the saved job is picked up on return) or a newer loop took over.
      if (cancelledRef.current || followRunRef.current !== run) return;
      const current = await getVisualization(jobId);
      setJob(current);
      if (current.status === "done" && current.result) {
        saveRoom({ brief, roomId: id, result: current.result });
        setResult(current.result);
        setView("after");
        setActive(null);
        setPhase("done");
        return;
      }
      if (current.status === "error") throw new Error(current.error ?? "The visualization failed.");
    }
  }

  /** Same photo, new variation (the design step picks again). */
  const restyleAgain = async () => {
    if (!roomId) return;
    setJob(null);
    try {
      await visualize(roomId);
    } catch (err) {
      fail(err instanceof Error ? err.message : "The visualization failed.");
    }
  };

  const reset = () => {
    stopCamera();
    saveRoom(null);
    setPhase("idle");
    setError("");
    setResult(null);
    setJob(null);
    setRoomId(null);
  };

  // Compare mode: drag the divider (or anywhere on the image) to reveal before / after.
  const dragTo = (clientX: number) => {
    const rect = stageRef.current?.getBoundingClientRect();
    if (!rect) return;
    setSplit(Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)));
  };
  const clip = view === "after" ? 0 : view === "before" ? 100 : split;

  if (placeable === 0) return null;

  const stageIndex = job ? stages.findIndex((s) => s.key === job.stage) : -1;

  return (
    <section className="room-visualizer" aria-labelledby="room-visualizer-heading">
      <div className="room-visualizer-head">
        <h2 id="room-visualizer-heading">See these pieces in your room</h2>
        <p hidden={phase === "done"}>
          Take a photo of your room. We choose pieces from these results that suit your brief, place them at their
          real size, and show your room restyled. It takes about a minute.
        </p>
      </div>

      {phase === "idle" || phase === "error" ? (
        <div className="room-visualizer-actions">
          <div className="room-visualizer-dims">
            <label>
              <span>Room width (cm)</span>
              <input
                inputMode="numeric"
                max={2000}
                min={100}
                onChange={(event) => setWidthCm(event.target.value)}
                placeholder="e.g. 300"
                type="number"
                value={widthCm}
              />
            </label>
            <label>
              <span>Room depth (cm)</span>
              <input
                inputMode="numeric"
                max={2000}
                min={100}
                onChange={(event) => setDepthCm(event.target.value)}
                placeholder="e.g. 400"
                type="number"
                value={depthCm}
              />
            </label>
          </div>
          <p className="room-visualizer-hint">
            Optional: type your room&apos;s real floor size for more accurate placement.
          </p>
          <button className="button button-dark" onClick={openCamera} type="button">
            Take a photo
          </button>
          <button className="button" onClick={() => fileRef.current?.click()} type="button">
            Upload a photo
          </button>
          <input accept="image/*" hidden onChange={onFile} ref={fileRef} type="file" />
          <p className="room-visualizer-hint">Stand back, hold the phone upright, and include plenty of floor.</p>
          {error ? (
            <p className="room-visualizer-error" role="alert">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}

      {phase === "camera" ? (
        <div className="room-visualizer-camera">
          <video
            aria-label="Camera preview"
            autoPlay
            muted
            onClick={() => void videoRef.current?.play()}
            playsInline
            ref={videoRef}
          />
          <p className="room-visualizer-tilt" aria-live="polite">
            {tiltLabel || "Hold the phone upright and include plenty of floor"}
          </p>
          {error ? (
            <p className="room-visualizer-error" role="alert">
              {error}
            </p>
          ) : null}
          <div className="room-visualizer-actions">
            <button className="button button-dark" onClick={takePhoto} type="button">
              Take photo
            </button>
            <button className="text-button" onClick={reset} type="button">
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {phase === "uploading" || phase === "working" ? (
        <div className="room-visualizer-progress" aria-live="polite">
          <ol>
            {stages.map((stage, index) => {
              const state = phase === "uploading" ? "todo" : index < stageIndex ? "done" : index === stageIndex ? "now" : "todo";
              return (
                <li className={`is-${state}`} key={stage.key}>
                  {stage.label}
                </li>
              );
            })}
          </ol>
          <p className="room-visualizer-hint">
            {phase === "uploading" ? "Uploading your photo…" : `${Math.round(job?.elapsed_s ?? 0)} s`}
          </p>
          {job?.info.guide_url ? (
            <figure className="room-visualizer-guide">
              <img alt="Where each piece goes, at its real size" src={job.info.guide_url} />
              <figcaption>Placed at real size. Now rendering your room…</figcaption>
            </figure>
          ) : null}
        </div>
      ) : null}

      {phase === "done" && result ? (
        <div className="rv-result">
          <header className="rv-result-head">
            <div>
              <p className="rv-kicker">Your room, restyled</p>
              <h3>{result.vibe}</h3>
            </div>
            <div className="rv-result-actions">
              <a className="button button-dark" download="buybyfit-room.png" href={result.render_url}>
                Download
              </a>
              <button className="button rv-light" disabled={!roomId} onClick={restyleAgain} type="button">
                Restyle again
              </button>
              <button className="text-button" onClick={reset} type="button">
                Try another photo
              </button>
            </div>
          </header>

          <div className="rv-view-switch" role="group" aria-label="Show">
            {(["before", "compare", "after"] as const).map((option) => (
              <button
                aria-pressed={view === option}
                className={view === option ? "is-on" : undefined}
                key={option}
                onClick={() => {
                  setView(option);
                  if (option === "compare") setSplit(50);
                }}
                type="button"
              >
                {option === "before" ? "Before" : option === "after" ? "After" : "Compare"}
              </button>
            ))}
          </div>
          <button
            aria-pressed={showMarkers}
            className="rv-markers-toggle"
            onClick={() => setShowMarkers((on) => !on)}
            type="button"
          >
            {showMarkers ? "Hide numbers" : "Show numbers"}
          </button>

          <div
            className={`rv-stage${view === "compare" ? " is-compare" : ""}`}
            onPointerDown={(event) => {
              if (view !== "compare") return;
              draggingRef.current = true;
              event.currentTarget.setPointerCapture(event.pointerId);
              dragTo(event.clientX);
            }}
            onPointerMove={(event) => draggingRef.current && dragTo(event.clientX)}
            onPointerUp={() => {
              draggingRef.current = false;
            }}
            ref={stageRef}
          >
            <img alt="Your room, before" draggable={false} src={result.photo_url} />
            <img
              alt={`Your room restyled: ${result.vibe}`}
              className="rv-after"
              draggable={false}
              src={result.render_url}
              style={{ clipPath: `inset(0 0 0 ${clip}%)` }}
            />
            {view === "compare" ? (
              <div className="rv-divider" style={{ left: `${split}%` }} aria-hidden="true">
                <span>‹ ›</span>
              </div>
            ) : null}
            {view !== "before" && showMarkers
              ? markerPositions(result.items).map(({ item, left, top }, index) => {
                  if (view === "compare" && left < split) return null; // marker belongs to the "after" side
                  return (
                    <button
                      aria-label={`${index + 1}: ${item.product.name}`}
                      className={`rv-marker${active === index ? " is-active" : ""}`}
                      key={item.product.id}
                      onClick={(event) => {
                        event.stopPropagation();
                        setActive(index);
                        document.getElementById(`rv-piece-${index}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
                      }}
                      onPointerDown={(event) => event.stopPropagation()}
                      style={{ left: `${left}%`, top: `${top}%` }}
                      type="button"
                    >
                      {index + 1}
                    </button>
                  );
                })
              : null}
          </div>

          {/* The expert AI review is internal quality control (it steers the second render and picks the better
              one); it is deliberately not shown, so the product never critiques its own restyle. */}

          {roomId && result.job_id ? <RestyleFeedback jobId={result.job_id} key={result.job_id} roomId={roomId} /> : null}

          <h4 className="rv-section-title">Pieces in this picture</h4>
          <ol className="rv-pieces">
            {result.items.map((item, index) => {
              const retailer = item.product.product_url?.startsWith("https://") ? item.product.product_url : null;
              return (
                <li
                  className={active === index ? "is-active" : undefined}
                  id={`rv-piece-${index}`}
                  key={item.product.id}
                  onMouseEnter={() => setActive(index)}
                >
                  <span className="rv-number">{index + 1}</span>
                  {item.product.image_url ? <img alt="" src={item.product.image_url} /> : <span className="rv-thumb" />}
                  <div className="rv-piece-body">
                    <p className="room-visualizer-role">{item.role}</p>
                    <Link className="rv-piece-name" href={productHref(item.product.id)}>
                      {item.product.name}
                    </Link>
                    <p className="rv-piece-meta">
                      <span className="rv-size">{item.product.size_cm}</span>
                      <span className={item.placed_at_true_size ? "rv-fit is-real" : "rv-fit"}>
                        {item.placed_at_true_size ? "Placed at real size" : "Approximate in the picture"}
                      </span>
                    </p>
                    <div className="rv-piece-links">
                      <Link href={productHref(item.product.id)}>Details</Link>
                      {retailer ? (
                        <a href={retailer} rel="noopener noreferrer" target="_blank">
                          Retailer ↗
                        </a>
                      ) : null}
                    </div>
                    {item.alternatives.length > 0 ? (
                      <div className="rv-alts">
                        <span>Also fits</span>
                        {item.alternatives.map((alt) => (
                          <Link href={productHref(alt.id)} key={alt.id} title={alt.name}>
                            {alt.image_url ? <img alt={alt.name} src={alt.image_url} /> : alt.name.slice(0, 18)}
                          </Link>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>

          {result.styling.length > 0 ? (
            <div className="rv-styling">
              <h4 className="rv-section-title">Styling ideas</h4>
              <p>In the picture for the look; not products we sell.</p>
              <ul>
                {result.styling.map((idea) => (
                  <li key={idea}>{idea}</li>
                ))}
              </ul>
            </div>
          ) : null}

          <p className="room-visualizer-note">
            AI visualization of your photo. Sizes come from each product&apos;s real dimensions; check the product page
            before you buy. Rendered in {Math.round(result.timings_s.total ?? 0)} s.
          </p>
        </div>
      ) : null}
    </section>
  );
}
