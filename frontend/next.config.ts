import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    formats: ["image/avif", "image/webp"],
    // amazon-berkeley-objects.s3.amazonaws.com serves live product images
    // from the recommendation service; next/image blocks unlisted hosts.
    remotePatterns: [
      {
        protocol: "https",
        hostname: "amazon-berkeley-objects.s3.amazonaws.com",
      },
    ],
  },
};

export default nextConfig;
