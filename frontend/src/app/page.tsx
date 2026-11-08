import Image from "next/image";
import Link from "next/link";

import { FurnitureCard } from "@/components/furniture-card";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { furnitureProducts } from "@/lib/mock-furniture";

const collection = furnitureProducts.slice(0, 3);

export default function HomePage() {
  return (
    <main>
      <div className="home-hero-band">
        <div className="page-shell home-shell">
          <SiteHeader active="home" />
          <section className="home-hero" aria-labelledby="hero-heading">
            <div className="hero-copy">
              <h1 id="hero-heading">Furniture that fits.</h1>
              <p className="hero-intro">Describe the room in your own words, then discover pieces to consider.</p>
              <Link className="button button-dark hero-button" href="/discover">
                Explore furniture
              </Link>
            </div>
            <div className="hero-media">
              <Image
                alt="Fictional Scandinavian living room with linen seating, warm wood, and soft daylight"
                fill
                priority
                sizes="(max-width: 860px) 100vw, 58vw"
                src="/images/hjem-living-room.jpg"
                style={{ objectFit: "cover", objectPosition: "right center" }}
              />
            </div>
          </section>
        </div>
      </div>

      <section className="home-statement-band" id="about" aria-label="How BuyByFit works">
        <div className="page-shell home-statement">
          <p>Start with the room. Describe what you want to live with, not just what you want to buy.</p>
        </div>
      </section>

      <section className="home-method page-shell" aria-labelledby="method-heading">
        <div className="method-heading">
          <h2 id="method-heading">Consider your whole room</h2>
        </div>
        <div className="method-items">
          <article>
            <p className="method-title">Begin with your own words</p>
            <p>Describe the atmosphere you want, the routines the room holds, and the pieces you are missing.</p>
          </article>
          <article>
            <p className="method-title">Include the real limits</p>
            <p>Tell BuyByFit about dimensions, budget, light, materials, and the things you would rather avoid.</p>
          </article>
          <article>
            <p className="method-title">Review the suggestions</p>
            <p>Explore the returned pieces with their materials, dimensions, and a clear retailer state in one quiet catalogue.</p>
          </article>
        </div>
      </section>

      <section className="home-collection" aria-labelledby="collection-heading">
        <div className="page-shell collection-heading">
          <div>
            <h2 id="collection-heading">Made to be compared</h2>
          </div>
          <Link className="text-link" href="/discover">
            See the full catalogue
          </Link>
        </div>
        <div className="page-shell home-product-grid">
          {collection.map((product, index) => (
            <FurnitureCard key={product.id} product={product} priority={index === 0} />
          ))}
        </div>
      </section>

      <section className="home-closing page-shell" aria-labelledby="closing-heading">
        <div>
          <h2 id="closing-heading">Let the room decide.</h2>
        </div>
        <p>Describe your space, then browse 16 clearly fictional furniture samples while the recommendation model is still in demo mode.</p>
        <Link className="button button-timber" href="/discover">
          Find your fit
        </Link>
      </section>

      <div className="page-shell">
        <SiteFooter />
      </div>
    </main>
  );
}
