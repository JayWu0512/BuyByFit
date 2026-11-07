import Image from "next/image";
import Link from "next/link";

import { formatCurrency, formatDimensions } from "@/lib/catalog";
import { FurnitureProduct } from "@/types/furniture";

interface FurnitureCardProps {
  product: FurnitureProduct;
  priority?: boolean;
  headingLevel?: 2 | 3;
}

export function FurnitureCard({ product, priority = false, headingLevel = 3 }: FurnitureCardProps) {
  const ProductHeading = headingLevel === 2 ? "h2" : "h3";

  return (
    <article className="furniture-card">
      <Link className="product-image-link" href={`/products/${product.id}`} aria-label={`View ${product.name}`}>
        <div className={`product-image-stage stage-${product.category.toLowerCase()}`}>
          <Image
            src={product.imageUrl}
            alt={product.imageAlt}
            fill
            priority={priority}
            sizes="(max-width: 620px) 100vw, (max-width: 980px) 50vw, (max-width: 1280px) 33vw, 25vw"
            style={{ objectFit: "cover", objectPosition: product.imagePosition ?? "center" }}
          />
        </div>
      </Link>
      <div className="product-card-details">
        <div className="product-card-heading">
          <div>
            <p className="product-category">{product.category}</p>
            <ProductHeading>
              <Link href={`/products/${product.id}`}>{product.name}</Link>
            </ProductHeading>
          </div>
          <p className="product-price">{formatCurrency(product.price, product.currency)}</p>
        </div>
        <p className="product-brand">{product.brand}</p>
        <p className="product-dimensions">{formatDimensions(product)}</p>
      </div>
    </article>
  );
}
