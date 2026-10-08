import { describe, expect, it } from "vitest";
import { PRODUCT_FIELDS, parseStoreState } from "@/core/api/validate";
import { toSceneStore } from "@/scene/layout";
import { sampleStoreState } from "@/test/sampleState";
import { mockStoreState } from "@/mocks";
import apiSchemas from "../../../../api/retailtwin_api/schemas.py?raw";

/** Field names of a pydantic model in apps/api, in declaration order. */
function apiModelFields(model: string): string[] {
  const body = apiSchemas.split(`class ${model}(BaseModel):`)[1]?.split(/\nclass /)[0] ?? "";
  return [...body.matchAll(/^    (\w+): /gm)].map((match) => match[1]);
}

describe("store-001 mock JSON", () => {
  it("is the store with empty shelves", () => {
    expect(parseStoreState(mockStoreState).issues).toEqual([]);
    expect(mockStoreState.products).toEqual([]);
  });
});

describe("GET /store contract", () => {
  it("requires the fields apps/api serves", () => {
    expect([...PRODUCT_FIELDS]).toEqual(apiModelFields("ProductInventory"));
    expect(apiModelFields("StoreResponse")).toEqual(["store_id", "context_version", "version", "products"]);
  });

  it("accepts the API fixture and places it on the layout", () => {
    const { state, issues } = parseStoreState(sampleStoreState());
    expect(issues).toEqual([]);
    expect(toSceneStore(state).issues).toEqual([]);
  });
});
