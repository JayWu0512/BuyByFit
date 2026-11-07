import type { Metadata } from "next";

import "@fontsource-variable/literata";
import "./globals.css";

export const metadata: Metadata = {
  title: "BuyByFit — Furniture that fits",
  description: "A furniture discovery demonstration for finding pieces by style, dimensions, and budget.",
  icons: {
    icon: "/brand-mark.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
