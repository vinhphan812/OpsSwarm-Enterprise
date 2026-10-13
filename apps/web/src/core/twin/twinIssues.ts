import type { ProductInventory, StoreResponse } from "@/types/twin.type";
import type { ProductIssue } from "@/core/api/validate";
import type { StateDiff } from "@/core/twin/stateDiff";
import { format } from "@/core/utils/format";
import { INSPECTION_KIND } from "@/enums/twin.enum";
import { sceneOf } from "@/scene/layout";

/**
 * The stock changes of `diff` that are not a matching backroom → shelf transfer: the shelf
 * gained units, or the backroom lost some, and the two deltas do not cancel out. A sale
 * (shelf down only) and a delivery (backroom up only) are not flagged.
 */
export function transferIssues(diff: StateDiff | null): ProductIssue[] {
  return (diff?.quantity ?? [])
    .filter(({ shelfDelta, backroomDelta }) => (shelfDelta > 0 || backroomDelta < 0) && shelfDelta + backroomDelta !== 0)
    .map(({ sku, shelfDelta, backroomDelta }) => ({
      sku,
      code: "inconsistentTransfer",
      values: { shelf: format.delta(shelfDelta), backroom: format.delta(backroomDelta) },
    }));
}

/**
 * Every product of the state on screen the scene cannot show as it is: broken records, then
 * unplaceable ones, which are not drawn, overflowing ones, drawn up to their slot, and
 * inconsistent transfers in `change`, the change that led to it.
 */
export function twinIssues(
  live: StoreResponse | null,
  contractIssues: ProductIssue[],
  change: StateDiff | null = null,
): ProductIssue[] {
  return live ? [...contractIssues, ...sceneOf(live).issues, ...transferIssues(change)] : contractIssues;
}

/** An issue whose product is still drawn: more facings than its slot holds. */
export const isOverflow = (issue: ProductIssue) => issue.code === "facingsOverCapacity";
/** An issue whose product is still drawn: its last stock change was not a matching transfer. */
export const isInconsistentTransfer = (issue: ProductIssue) => issue.code === "inconsistentTransfer";
const isDrawn = (issue: ProductIssue) => isOverflow(issue) || isInconsistentTransfer(issue);

export type ProductInspection =
  | { kind: typeof INSPECTION_KIND.Loading }
  | { kind: typeof INSPECTION_KIND.Missing }
  | { kind: typeof INSPECTION_KIND.Invalid; issue: ProductIssue }
  /**
   * `overflow` is set while the product has more facings than its slot holds; `transfer`
   * while its last stock change was not a matching transfer.
   */
  | { kind: typeof INSPECTION_KIND.Ok; product: ProductInventory; overflow?: ProductIssue; transfer?: ProductIssue };

/** What the twin currently says about one product. */
export function inspectProduct(
  sku: string,
  live: StoreResponse | null,
  issues: ProductIssue[],
): ProductInspection {
  if (!live) return { kind: INSPECTION_KIND.Loading };
  const own = issues.filter((item) => item.sku === sku);
  const issue = own.find((item) => !isDrawn(item));
  if (issue) return { kind: INSPECTION_KIND.Invalid, issue };
  const product = live.products.find((item) => item.sku === sku);
  if (!product) return { kind: INSPECTION_KIND.Missing };
  const overflow = own.find(isOverflow);
  const transfer = own.find(isInconsistentTransfer);
  return {
    kind: INSPECTION_KIND.Ok,
    product,
    ...(overflow ? { overflow } : {}),
    ...(transfer ? { transfer } : {}),
  };
}
