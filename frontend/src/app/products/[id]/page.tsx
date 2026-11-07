import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";

import { FurnitureCard } from "@/components/furniture-card";
import { Product3DViewer } from "@/components/product-3d-viewer";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { formatDimensions, formatLabel, getFurnitureById, getRelatedFurniture, toClassToken } from "@/lib/catalog";
import { furnitureProducts } from "@/lib/mock-furniture";
import { getCatalogProduct, getRelatedCatalogProducts } from "@/lib/server/supabase";

interface ProductPageProps {
  params: Promise<{ id: string }>;
}

// Fictional demo products are pre-rendered; real catalogue products (ids like "abo:B07…") render on
// demand from Supabase and are cached for an hour.
export const dynamicParams = true;
export const revalidate = 3600;

export function generateStaticParams() {
  return furnitureProducts.map((product) => ({ id: product.id }));
}

export default async function ProductPage({ params }: ProductPageProps) {
  const id = decodeURIComponent((await params).id);
  const demoProduct = getFurnitureById(id);
  const product = demoProduct ?? (await getCatalogProduct(id));

  if (!product) notFound();

  const related = demoProduct ? getRelatedFurniture(product) : await getRelatedCatalogProducts(product);

  return (
    <main>
      <div className="page-shell">
        <SiteHeader />
      </div>
      <div className="page-shell product-shell">
        <section className="product-detail" aria-labelledby="product-title">
          <div className={`product-detail-media stage-${toClassToken(product.category)}${product.imageFit === "contain" ? " stage-cutout" : ""}`}>
            <Image
              alt={product.imageAlt}
              fill
              priority
              sizes="(max-width: 860px) 100vw, 58vw"
              src={product.imageUrl}
              style={{ objectFit: product.imageFit ?? "cover", objectPosition: product.imagePosition ?? "center" }}
            />
          </div>
          <div className="product-detail-copy">
            <h1 className={product.name.length > 40 ? "product-title-long" : undefined} id="product-title">{product.name}</h1>
            <p className="product-detail-brand">{formatLabel(product.category)} · {product.brand} · {product.retailer}</p>
            {product.description ? <p className="product-description">{product.description}</p> : null}

            <dl className="product-specs">
              {product.styles.length > 0 && (
                <div>
                  <dt>Style</dt>
                  <dd>{product.styles.map(formatLabel).join(" · ")}</dd>
                </div>
              )}
              {product.material && (
                <div>
                  <dt>Material</dt>
                  <dd>{product.material}</dd>
                </div>
              )}
              <div>
                <dt>Dimensions</dt>
                <dd>{formatDimensions(product)}</dd>
              </div>
            </dl>

            {product.arModelUrl || product.model3dUrl ? (
              <Product3DViewer
                alt={`3D model of ${product.name}`}
                depthCm={product.depthCm}
                heightCm={product.heightCm}
                poster={product.imageUrl}
                src={(product.arModelUrl ?? product.model3dUrl) as string}
                widthCm={product.widthCm}
              />
            ) : null}

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

        {related.length > 0 && (
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
        )}
      </div>
      <div className="page-shell">
        <SiteFooter />
      </div>
    </main>
  );
}
