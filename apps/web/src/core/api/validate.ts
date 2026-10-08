import i18n from "@/i18n";
import type { Messages } from "@/i18n/locales/vi";
import type { ProductInventory, StoreResponse } from "@/types/twin.type";

/** Why a product is not drawn: a key under `issue` in the locale files. */
export type IssueCode = keyof Messages["issue"];

/**
 * A product record the scene cannot draw, and why. `sku` is its entity id. The reason
 * is a code with its values, translated where it is shown, so it follows the language.
 */
export type ProductIssue = {
  sku: string;
  code: IssueCode;
  values?: Record<string, string | number>;
};

/** The issue's reason in the current language. */
export function issueReason(issue: ProductIssue): string {
  return i18n.t(`issue.${issue.code}`, issue.values);
}

type InvalidStateReason = Exclude<keyof Messages["invalidState"], "title">;

/** The payload is not a store response at all, so nothing in it can be trusted. */
export class InvalidTwinStateError extends Error {
  constructor(reason: InvalidStateReason, values?: Record<string, string>) {
    super(i18n.t("invalidState.title", { reason: i18n.t(`invalidState.${reason}`, values) }));
    this.name = "InvalidTwinStateError";
  }
}

/** Required product fields of `GET /store`, as `ProductInventory` in apps/api declares them. */
export const PRODUCT_FIELDS = [
  "store_id",
  "sku",
  "shelf_id",
  "slot_id",
  "facings",
  "shelf_quantity",
  "backroom_quantity",
  "version",
] as const satisfies ReadonlyArray<keyof ProductInventory>;

type Fields = Record<string, unknown>;

const isObject = (value: unknown): value is Fields =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;

type Problem = Omit<ProductIssue, "sku">;

/** Why one product record breaks the contract, or null when it is valid. */
function productProblem(raw: Fields, storeId: string): Problem | null {
  if (raw.store_id !== storeId) {
    return { code: "wrongStore", values: { storeId: JSON.stringify(raw.store_id), expected: storeId } };
  }
  if (raw.shelf_id == null || raw.slot_id == null) return { code: "unassigned" };
  if (!isText(raw.shelf_id)) return { code: "invalidShelfId" };
  if (!isText(raw.slot_id)) return { code: "invalidSlotId" };
  for (const field of ["facings", "shelf_quantity", "backroom_quantity", "version"] as const) {
    if (!isCount(raw[field])) return { code: "invalidCount", values: { field, value: String(JSON.stringify(raw[field])) } };
  }
  return null;
}

/**
 * Checks a `GET /store` payload against the contract. A broken envelope throws; a
 * broken product is left out of `state` and reported in `issues`, so one bad record
 * never hides the rest of the store.
 */
export function parseStoreState(raw: unknown): { state: StoreResponse; issues: ProductIssue[] } {
  if (!isObject(raw)) throw new InvalidTwinStateError("notObject");
  for (const field of ["store_id", "context_version", "version"] as const) {
    if (!isText(raw[field])) throw new InvalidTwinStateError("missingField", { field });
  }
  if (!Array.isArray(raw.products)) throw new InvalidTwinStateError("productsNotArray");

  const storeId = raw.store_id as string;
  const products: ProductInventory[] = [];
  const issues: ProductIssue[] = [];
  const seen = new Set<string>();
  raw.products.forEach((item: unknown, index) => {
    if (!isObject(item) || !isText(item.sku)) {
      issues.push({ sku: `#${index}`, code: "missingSku" });
      return;
    }
    const sku = item.sku;
    if (seen.has(sku)) {
      issues.push({ sku, code: "duplicateSku" });
      return;
    }
    seen.add(sku);
    const problem = productProblem(item, storeId);
    if (problem) issues.push({ sku, ...problem });
    else products.push(item as ProductInventory);
  });

  return {
    state: {
      store_id: storeId,
      context_version: raw.context_version as string,
      version: raw.version as string,
      products,
    },
    issues,
  };
}
