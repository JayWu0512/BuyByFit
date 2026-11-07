import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    formats: ["image/avif", "image/webp"],
    // Real catalogue images (Supabase products): ABO furniture on S3, plush thumbnails on Sketchfab.
    // next/image blocks unlisted hosts.
    remotePatterns: [
      {
        protocol: "https",
        hostname: "amazon-berkeley-objects.s3.amazonaws.com",
      },
      {
        protocol: "https",
        hostname: "media.sketchfab.com",
      },
    ],
  },
  // The search route embeds briefs with transformers.js (ONNX). Keep it out of the bundle and load it
  // from node_modules at runtime.
  serverExternalPackages: ["@huggingface/transformers", "onnxruntime-node"],
  // transformers.js loads onnxruntime-node in a way Next's tracer can't see, so include it explicitly.
  // It ships binaries for every OS (~290 MB); Vercel runs linux-x64, so include only that one (~45 MB)
  // to stay under the 250 MB function limit. (Listing what to include, not excluding the rest, also
  // works when building on Windows, where traced paths use backslashes.)
  outputFileTracingIncludes: {
    "/api/v1/searches": [
      "node_modules/onnxruntime-node/package.json",
      "node_modules/onnxruntime-node/dist/**",
      "node_modules/onnxruntime-node/lib/**",
      "node_modules/onnxruntime-node/bin/napi-v*/linux/x64/**",
    ],
  },
  outputFileTracingExcludes: {
    "/api/v1/searches": ["node_modules/onnxruntime-web/**"],
  },
};

export default nextConfig;
