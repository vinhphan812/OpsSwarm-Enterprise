import { memo, useMemo } from "react";
import { groupBy } from "@/core/utils/collections";
import type { ProductFixture, SlotFixture } from "@/types/scene.type";
import { Product } from "./Product";
import { Slot } from "./Slot";

type SlotProductsProps = {
  slots: SlotFixture[];
  /** Products of this fixture only. */
  products: ProductFixture[];
};

/** Every slot of a fixture with the products placed in it. Memoized: a hover on the fixture leaves it alone. */
export const SlotProducts = memo(function SlotProducts({ slots, products }: SlotProductsProps) {
  const bySlot = useMemo(() => groupBy(products, (product) => product.slotId), [products]);
  return (
    <>
      {slots.map((slot) => (
        <Slot key={slot.slotId} slot={slot}>
          {bySlot.get(slot.slotId)?.map((product) => (
            <Product key={product.productId} product={product} />
          ))}
        </Slot>
      ))}
    </>
  );
});
