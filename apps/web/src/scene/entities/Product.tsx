import { Html } from "@react-three/drei";
import { useTranslation } from "react-i18next";
import { useUiStore } from "@/state/ui.store";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { entityProps } from "./entity";
import type { ProductFixture } from "@/scene/types";
import { TAG_LIFT } from "@/constants/scene.constant";

/**
 * Entity marker for a product, placed at its slot. The packaging itself is drawn
 * by Stock, which instances every product in the store together. The marker carries
 * the twin's stock figures in `userData`, and shows them as a tag while selected.
 */
export function Product({ product }: { product: ProductFixture }) {
  const selected = useUiStore((state) => state.selectedEntityId === product.productId);
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
    >
      {selected ? <ProductTag product={product} /> : null}
    </group>
  );
}

function ProductTag({ product }: { product: ProductFixture }) {
  // Translated here: Html renders its children in a separate React root.
  const { t } = useTranslation();
  const figures = t("scene.productTag", {
    facings: product.facings,
    shelf: product.shelfQuantity,
    backroom: product.backroomQuantity,
  });
  return (
    <Html position={[0, TAG_LIFT, 0]} center distanceFactor={8} style={{ pointerEvents: "none" }}>
      <div className="hover-label">
        <span className="hover-label__title">{product.productId}</span>
        <span className="hover-label__id">{figures}</span>
      </div>
    </Html>
  );
}
