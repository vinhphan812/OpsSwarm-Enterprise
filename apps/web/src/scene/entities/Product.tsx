import { ENTITY_TYPE } from "@/enums/scene.enum";
import { entityProps } from "./entity";
import type { ProductFixture } from "@/scene/types";

/**
 * Entity marker for a product, placed at its slot. The packaging itself is drawn
 * by Stock, which instances every product in the store together. The marker carries
 * the twin's stock figures in `userData`.
 */
export function Product({ product }: { product: ProductFixture }) {
  const { name, userData } = entityProps(product.productId, ENTITY_TYPE.Product);

  return (
    <group
      name={name}
      userData={{
        ...userData,
        facings: product.facings,
        shelfQuantity: product.shelfQuantity,
        backroomQuantity: product.backroomQuantity,
        version: product.version,
      }}
    />
  );
}
