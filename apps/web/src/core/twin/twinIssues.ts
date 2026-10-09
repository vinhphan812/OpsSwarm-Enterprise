import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type { ProductIssue } from "@/core/api/validate";
import { INSPECTION_KIND } from "@/enums/twin.enum";
import { sceneOf } from "@/scene/layout";

/** Every product of the live state that is not drawn: broken records, then unplaceable ones. */
export function twinIssues(live: StoreResponse | null, contractIssues: ProductIssue[]): ProductIssue[] {
  return live ? [...contractIssues, ...sceneOf(live).issues] : contractIssues;
}

export type ProductInspection =
  | { kind: typeof INSPECTION_KIND.Loading }
  | { kind: typeof INSPECTION_KIND.Missing }
  | { kind: typeof INSPECTION_KIND.Invalid; issue: ProductIssue }
  | { kind: typeof INSPECTION_KIND.Ok; product: ProductInventory };

/** What the twin currently says about one product. */
export function inspectProduct(
  sku: string,
  live: StoreResponse | null,
  issues: ProductIssue[],
): ProductInspection {
  if (!live) return { kind: INSPECTION_KIND.Loading };
  const issue = issues.find((item) => item.sku === sku);
  if (issue) return { kind: INSPECTION_KIND.Invalid, issue };
  const product = live.products.find((item) => item.sku === sku);
  return product ? { kind: INSPECTION_KIND.Ok, product } : { kind: INSPECTION_KIND.Missing };
}
