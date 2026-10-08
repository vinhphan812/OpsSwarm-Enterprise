import { useMemo } from "react";
import { groupBy } from "@/core/utils/collections";
import type { ProductFixture, SlotFixture } from "@/scene/types";
import { Product } from "./Product";
import { Slot } from "./Slot";

type SlotProductsProps = {
  slots: SlotFixture[];
  /** Products of this fixture only. */
  products: ProductFixture[];
};

/** Every slot of a fixture with the products placed in it. */
export function SlotProducts({ slots, products }: SlotProductsProps) {
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
}
