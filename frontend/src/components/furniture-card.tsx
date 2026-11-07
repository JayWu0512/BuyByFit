import Image from "next/image";
import Link from "next/link";

import { formatDimensions, formatLabel, toClassToken } from "@/lib/catalog";
import { FurnitureProduct } from "@/types/furniture";

interface FurnitureCardProps {
  product: FurnitureProduct;
  priority?: boolean;
  headingLevel?: 2 | 3;
  /** "detail" opens /products/[id] (demo and Supabase catalogue products); "retailer" links out directly. */
  linkTo?: "detail" | "retailer";
}

export function FurnitureCard({ product, priority = false, headingLevel = 3, linkTo = "detail" }: FurnitureCardProps) {
  const ProductHeading = headingLevel === 2 ? "h2" : "h3";
  const useRetailerLink = linkTo === "retailer";
  const href = useRetailerLink ? product.retailerUrl : `/products/${product.id}`;

  const stage = (
    <div className={`product-image-stage stage-${toClassToken(product.category)}${product.imageFit === "contain" ? " stage-cutout" : ""}`}>
      <Image
        src={product.imageUrl}
        alt={product.imageAlt}
        fill
        priority={priority}
        sizes="(max-width: 620px) 100vw, (max-width: 980px) 50vw, (max-width: 1280px) 33vw, 25vw"
        style={{ objectFit: product.imageFit ?? "cover", objectPosition: product.imagePosition ?? "center" }}
      />
      {product.arModelUrl || product.model3dUrl ? <span className="product-3d-badge">3D</span> : null}
    </div>
  );

  return (
    <article className="furniture-card">
      {href ? (
        useRetailerLink ? (
          <a className="product-image-link" href={href} target="_blank" rel="noopener noreferrer" aria-label={`View ${product.name} at retailer`}>
            {stage}
          </a>
        ) : (
          <Link className="product-image-link" href={href} aria-label={`View ${product.name}`}>
            {stage}
          </Link>
        )
      ) : (
        stage
      )}
      <div className="product-card-details">
        <div className="product-card-heading">
          <div>
            <p className="product-category">{formatLabel(product.category)}</p>
            <ProductHeading>
              {href ? (
                useRetailerLink ? (
                  <a href={href} target="_blank" rel="noopener noreferrer">
                    {product.name}
                  </a>
                ) : (
                  <Link href={href}>{product.name}</Link>
                )
              ) : (
                product.name
              )}
            </ProductHeading>
          </div>
        </div>
        <p className="product-brand">{product.brand}</p>
        {product.description ? <p className="product-card-description">{product.description}</p> : null}
        <p className="product-dimensions">{formatDimensions(product)}</p>
        {typeof product.matchScore === "number" ? (
          <p className="product-match-score">{Math.round(product.matchScore)}% match</p>
        ) : null}
      </div>
    </article>
  );
}
