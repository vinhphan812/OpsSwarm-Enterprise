import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type { ProductIssue } from "@/core/api/validate";
import { INSPECTION_KIND } from "@/enums/twin.enum";
import { sceneOf } from "@/scene/layout";

/**
 * Every product of the live state the scene cannot show as it is: broken records, then
 * unplaceable ones, which are not drawn, and overflowing ones, drawn up to their slot.
 */
export function twinIssues(live: StoreResponse | null, contractIssues: ProductIssue[]): ProductIssue[] {
  return live ? [...contractIssues, ...sceneOf(live).issues] : contractIssues;
}

/** An issue whose product is still drawn: more facings than its slot holds. */
export const isOverflow = (issue: ProductIssue) => issue.code === "facingsOverCapacity";

export type ProductInspection =
  | { kind: typeof INSPECTION_KIND.Loading }
  | { kind: typeof INSPECTION_KIND.Missing }
  | { kind: typeof INSPECTION_KIND.Invalid; issue: ProductIssue }
  /** `overflow` is set while the product has more facings than its slot holds. */
  | { kind: typeof INSPECTION_KIND.Ok; product: ProductInventory; overflow?: ProductIssue };

/** What the twin currently says about one product. */
export function inspectProduct(
  sku: string,
  live: StoreResponse | null,
  issues: ProductIssue[],
): ProductInspection {
  if (!live) return { kind: INSPECTION_KIND.Loading };
  const own = issues.filter((item) => item.sku === sku);
  const issue = own.find((item) => !isOverflow(item));
  if (issue) return { kind: INSPECTION_KIND.Invalid, issue };
  const product = live.products.find((item) => item.sku === sku);
  if (!product) return { kind: INSPECTION_KIND.Missing };
  const overflow = own.find(isOverflow);
  return overflow ? { kind: INSPECTION_KIND.Ok, product, overflow } : { kind: INSPECTION_KIND.Ok, product };
}
