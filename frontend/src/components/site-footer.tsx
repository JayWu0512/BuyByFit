import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-identity">
        <div className="footer-wordmark">
          BuyByFit
        </div>
        <p className="footer-message">A calmer way to compare furniture for the room you actually have.</p>
      </div>
      <div className="footer-meta">
        <div className="footer-links">
          <Link href="/discover">Discover furniture</Link>
          <Link href="/#about">How it works</Link>
        </div>
      </div>
    </footer>
  );
}
