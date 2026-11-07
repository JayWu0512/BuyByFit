import Link from "next/link";

import { BrandLogo } from "@/components/brand-logo";

interface SiteHeaderProps {
  active?: "home" | "discover";
}

export function SiteHeader({ active }: SiteHeaderProps) {
  return (
    <header className="site-header">
      <Link className="wordmark" href="/" aria-label="BuyByFit home">
        <BrandLogo />
      </Link>
      <nav className="site-nav" aria-label="Primary navigation">
        <Link className={active === "discover" ? "nav-link nav-link-active" : "nav-link"} href="/discover">
          Discover
        </Link>
        <Link className={active === "home" ? "nav-link nav-link-active" : "nav-link"} href="/#about">
          About
        </Link>
      </nav>
    </header>
  );
}
