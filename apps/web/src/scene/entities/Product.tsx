import { ENTITY_TYPE } from "@/enums/scene.enum";
import { entityProps } from "./entity";
import type { ProductFixture } from "@/types/scene.type";

/**
 * Entity marker for a product, placed at its slot. The packaging itself is drawn
 * by Stock, which instances every product in the store together, and lights up the
 * selected product's items. The marker carries the twin's stock figures in `userData`;
 * ProductInspector shows them for the selected product.
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
