// JSX typing for Google's <model-viewer> web component (loaded from a CDN in Product3DViewer).
import type { DetailedHTMLProps, HTMLAttributes } from "react";

type ModelViewerAttributes = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  src?: string;
  poster?: string;
  alt?: string;
  ar?: boolean;
  "ar-modes"?: string;
  "ar-placement"?: string;
  "ar-scale"?: string;
  "camera-controls"?: boolean;
  "shadow-intensity"?: string;
  "interaction-prompt"?: string;
  "touch-action"?: string;
  class?: string;
};

declare module "react" {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      "model-viewer": ModelViewerAttributes;
    }
  }
}
