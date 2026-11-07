import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FurnitureCard } from "@/components/furniture-card";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { formatCurrency, formatDimensions, getFurnitureById, getRelatedFurniture } from "@/lib/catalog";
import { furnitureProducts } from "@/lib/mock-furniture";

interface ProductPageProps {
  params: Promise<{ id: string }>;
}

export function generateStaticParams() {
  return furnitureProducts.map((product) => ({ id: product.id }));
}

export default async function ProductPage({ params }: ProductPageProps) {
  const { id } = await params;
  const product = getFurnitureById(id);

  if (!product) notFound();

  const related = getRelatedFurniture(product);

  return (
    <main>
      <div className="page-shell">
        <SiteHeader />
      </div>
      <div className="page-shell product-shell">
        <section className="product-detail" aria-labelledby="product-title">
          <div className={`product-detail-media stage-${product.category.toLowerCase()}`}>
            <Image
              alt={product.imageAlt}
              fill
              priority
              sizes="(max-width: 860px) 100vw, 58vw"
              src={product.imageUrl}
              style={{ objectFit: "cover", objectPosition: product.imagePosition ?? "center" }}
            />
          </div>
          <div className="product-detail-copy">
            <h1 id="product-title">{product.name}</h1>
            <p className="product-detail-price">{formatCurrency(product.price, product.currency)}</p>
            <p className="product-detail-brand">{product.category} · {product.brand} · {product.retailer}</p>
            <p className="product-description">{product.description}</p>

            <dl className="product-specs">
              <div>
                <dt>Style</dt>
                <dd>{product.styles.join(" · ")}</dd>
              </div>
              <div>
                <dt>Material</dt>
                <dd>{product.material}</dd>
              </div>
              <div>
                <dt>Dimensions</dt>
                <dd>{formatDimensions(product)}</dd>
              </div>
            </dl>

            {product.retailerUrl ? (
              <a className="button button-dark" href={product.retailerUrl} rel="noopener noreferrer" target="_blank">
                Buy it
              </a>
            ) : (
              <button aria-label="Buy it is unavailable for this fictional sample" className="button button-unavailable" disabled type="button">
                Buy it
              </button>
            )}
            <Link className="back-link product-return" href="/discover">
              Back to your search
            </Link>
          </div>
        </section>

        <section className="related-section" aria-labelledby="related-heading">
          <div className="related-heading">
            <h2 id="related-heading">Nearby in the catalogue</h2>
          </div>
          <div className="related-grid">
            {related.map((relatedProduct) => (
              <FurnitureCard key={relatedProduct.id} product={relatedProduct} />
            ))}
          </div>
        </section>
      </div>
      <div className="page-shell">
        <SiteFooter />
      </div>
    </main>
  );
}
