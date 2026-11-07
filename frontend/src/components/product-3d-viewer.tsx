"use client";

import Script from "next/script";
import { useEffect, useRef, useState } from "react";

interface Product3DViewerProps {
  src: string;
  poster: string;
  alt: string;
  /** Real size in cm, shown under the viewer. */
  widthCm: number;
  depthCm: number;
  heightCm: number;
}

/**
 * The product's real 3D model (Google <model-viewer>): rotate/zoom in the page, and "View in your room"
 * places it at true size through the phone camera (WebXR / Scene Viewer on Android, Quick Look on iPhone).
 * Loads only when asked, because original catalogue models can be several MB.
 */
export function Product3DViewer({ src, poster, alt, widthCm, depthCm, heightCm }: Product3DViewerProps) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const viewer = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = viewer.current;
    if (!open || !el) return;
    const onLoad = () => setStatus("ready");
    const onError = () => setStatus("error");
    el.addEventListener("load", onLoad);
    el.addEventListener("error", onError);
    return () => {
      el.removeEventListener("load", onLoad);
      el.removeEventListener("error", onError);
    };
  }, [open]);

  return (
    <section className="product-3d" aria-label="3D model">
      {open ? (
        <>
          <Script
            src="https://cdn.jsdelivr.net/npm/@google/model-viewer@4.0.0/dist/model-viewer.min.js"
            strategy="afterInteractive"
            type="module"
          />
          <model-viewer
            alt={alt}
            ar
            ar-modes="webxr scene-viewer quick-look"
            ar-placement="floor"
            ar-scale="fixed"
            camera-controls
            class="product-3d-canvas"
            interaction-prompt="none"
            poster={poster}
            ref={viewer}
            shadow-intensity="1"
            src={src}
            touch-action="pan-y"
          >
            <button className="button button-dark product-3d-ar" slot="ar-button" type="button">
              View in your room
            </button>
          </model-viewer>
          <p className="product-3d-note" aria-live="polite">
            {status === "error"
              ? "The 3D model couldn’t be loaded."
              : status === "ready"
                ? `Drag to turn · real size ${Math.round(widthCm)} × ${Math.round(depthCm)} × ${Math.round(heightCm)} cm`
                : "Loading the 3D model…"}
          </p>
        </>
      ) : (
        <button className="button product-3d-open" onClick={() => setOpen(true)} type="button">
          View in 3D
        </button>
      )}
    </section>
  );
}
