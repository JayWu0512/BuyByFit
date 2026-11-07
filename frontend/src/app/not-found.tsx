import Link from "next/link";

export default function NotFound() {
  return (
    <main className="not-found-page">
      <p className="wordmark">BuyByFit</p>
      <h1>This piece is no longer in the catalogue.</h1>
      <p>Try the full furniture selection instead.</p>
      <Link className="button button-dark" href="/discover">
        Back to discover
      </Link>
    </main>
  );
}
