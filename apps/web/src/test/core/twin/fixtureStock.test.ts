import { describe, expect, it } from "vitest";
import { patchProduct } from "@/core/api/sources/memorySource";
import { findFixture, fixtureStock, stockState } from "@/core/twin/fixtureStock";
import { STOCK_STATE } from "@/enums/stock.enum";
import { stockedStoreState } from "@/test/stockedState";

describe("fixtureStock", () => {
  it("sums up what the twin has on a shelf, in slot order", () => {
    const stock = fixtureStock("A01", stockedStoreState())!;
    expect(stock.products.map((product) => product.productId)).toEqual(["P001", "P002", "P003"]);
    expect(stock.slotCount).toBe(72);
    expect(stock.unitsOnShelf).toBe(8 + 10 + 0);
    expect(stock.unitsInBackroom).toBe(42 + 10 + 18);
    expect(stock.outCount).toBe(1);
    expect(stock.lowCount).toBe(0);
  });

  it("works for display equipment, and is empty for a fixture with no products", () => {
    expect(fixtureStock("OC01", stockedStoreState())).toMatchObject({ outCount: 1, unitsOnShelf: 0 });
    expect(fixtureStock("C03", stockedStoreState())).toMatchObject({ products: [], unitsOnShelf: 0 });
    expect(fixtureStock("NOPE", stockedStoreState())).toBeNull();
  });

  it("follows the twin and leaves out products the scene cannot place", () => {
    const moved = patchProduct(stockedStoreState(), "P002", { slot_id: "A01-S99" });
    expect(fixtureStock("A01", moved)!.products.map((product) => product.productId)).toEqual(["P001", "P003"]);
  });

  it("calls a slot out when empty and low when short of its facings", () => {
    expect(stockState({ facings: 2, shelfQuantity: 0 })).toBe(STOCK_STATE.Out);
    expect(stockState({ facings: 3, shelfQuantity: 2 })).toBe(STOCK_STATE.Low);
    expect(stockState({ facings: 3, shelfQuantity: 3 })).toBe(STOCK_STATE.Ok);
  });

  it("finds shelves and equipment of the layout", () => {
    expect(findFixture("A01")?.shelf?.shelfId).toBe("A01");
    expect(findFixture("CK01")?.equipment?.kind).toBe("checkout");
    expect(findFixture("P001")).toBeNull();
  });
});
