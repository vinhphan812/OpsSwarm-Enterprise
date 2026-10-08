import { describe, expect, it } from "vitest";
import { sampleStoreState } from "@/test/sampleState";
import { patchProduct } from "@/core/api/sources/memorySource";
import { InvalidTwinStateError, parseStoreState } from "@/core/api/validate";

const issueFor = (patch: Parameters<typeof patchProduct>[2]) => {
  const { state, issues } = parseStoreState(patchProduct(sampleStoreState(), "P001", patch));
  expect(state.products.some((p) => p.sku === "P001")).toBe(false);
  return issues.find((issue) => issue.sku === "P001");
};

describe("parseStoreState", () => {
  it("accepts the sample store as it is", () => {
    const { state, issues } = parseStoreState(sampleStoreState());
    expect(issues).toEqual([]);
    expect(state).toEqual(sampleStoreState());
  });

  it("rejects a payload that is not a store state", () => {
    expect(() => parseStoreState(null)).toThrow(InvalidTwinStateError);
    expect(() => parseStoreState({ ...sampleStoreState(), version: "" })).toThrow(/version/);
    expect(() => parseStoreState({ ...sampleStoreState(), context_version: undefined })).toThrow(/context_version/);
    expect(() => parseStoreState({ ...sampleStoreState(), products: {} })).toThrow(/products/);
  });

  it("leaves out a broken product, keeps the rest, and says why", () => {
    expect(issueFor({ slot_id: null })).toEqual({ sku: "P001", code: "unassigned" });
    expect(issueFor({ shelf_id: undefined })).toEqual({ sku: "P001", code: "unassigned" });
    expect(issueFor({ store_id: "store-002" })).toMatchObject({
      code: "wrongStore",
      values: { storeId: '"store-002"', expected: "store-001" },
    });
    expect(issueFor({ facings: -1 })).toMatchObject({ code: "invalidCount", values: { field: "facings", value: "-1" } });
    expect(issueFor({ facings: 2.5 })).toMatchObject({ code: "invalidCount", values: { field: "facings" } });
    expect(issueFor({ shelf_quantity: "8" })).toMatchObject({ code: "invalidCount", values: { field: "shelf_quantity" } });
    expect(issueFor({ backroom_quantity: -3 })).toMatchObject({
      code: "invalidCount",
      values: { field: "backroom_quantity" },
    });

    const { state } = parseStoreState(patchProduct(sampleStoreState(), "P001", { facings: -1 }));
    expect(state.products).toHaveLength(sampleStoreState().products.length - 1);
  });

  it("keeps the first of two products with the same id", () => {
    const base = sampleStoreState();
    const { state, issues } = parseStoreState({ ...base, products: [...base.products, base.products[0]] });
    expect(state.products).toHaveLength(base.products.length);
    expect(issues).toEqual([{ sku: "P001", code: "duplicateSku" }]);
  });

  it("reports a product without a sku by its position", () => {
    const base = sampleStoreState();
    const { issues } = parseStoreState({ ...base, products: [{ ...base.products[0], sku: "" }] });
    expect(issues).toEqual([{ sku: "#0", code: "missingSku" }]);
  });
});
