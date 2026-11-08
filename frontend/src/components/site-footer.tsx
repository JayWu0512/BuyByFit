import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-identity">
        <div className="footer-wordmark">
          BuyByFit
        </div>
        <p className="footer-message">
          <span>Reimagine your room.</span>
          <span>Shop the look you love.</span>
        </p>
      </div>
      <div className="footer-meta">
        <div className="footer-links">
          <Link href="/discover">Discover furniture</Link>
          <Link href="/#about">How it works</Link>
          <a href="mailto:jaywu05120512@gmail.com,diwaspuri@gmail.com,isaacvergaram@hotmail.com,teme.tewolde@gmail.com?subject=BuyByFit%20inquiry">
            Contact us
          </a>
        </div>
      </div>
    </footer>
  );
}
