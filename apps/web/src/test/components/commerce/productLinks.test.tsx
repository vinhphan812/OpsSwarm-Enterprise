// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PromotionCard } from "@/components/promotions/PromotionCard";
import { SkuList } from "@/components/revenue/SkuList";
import { PROMOTION_KIND, PROMOTION_STATUS } from "@/enums/commerce.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { stockedStoreState } from "@/test/stockedState";
import type { Promotion } from "@/types/promotion.type";

MotionGlobalConfig.skipAnimations = true;

const state = stockedStoreState();
const p004 = state.products.find((product) => product.sku === "P004")!;

beforeEach(() => {
  useTwinStore.setState({ live: state, issues: [], status: TWIN_STATUS.Ready });
  useUiStore.getState().select(null);
});

afterEach(cleanup);

describe("revenue SKU lists", () => {
  it("select the product of a row", () => {
    render(
      <SkuList
        label="Top sellers"
        skus={[{ sku: "P004", name: "Penne pasta 500 g", revenue: 302.4, units: 160, facings: 3 }]}
      />,
    );
    const row = screen.getByRole("button", { name: "Show P004 Penne pasta 500 g in the store" });
    fireEvent.click(row);
    expect(selectedProductId(useUiStore.getState())).toBe("P004");
    expect(row.getAttribute("aria-pressed")).toBe("true");
  });
});

describe("promotion cards", () => {
  const promotion: Promotion = {
    id: "promo-1",
    name: "Pasta night bundle",
    status: PROMOTION_STATUS.Scheduled,
    kind: PROMOTION_KIND.Bundle,
    value: 0,
    starts_at: "2026-10-12T00:00:00Z",
    ends_at: "2026-10-20T00:00:00Z",
    skus: ["P004", "P999"],
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
  };

  it("list their products with the twin's stock, and select one", () => {
    render(<PromotionCard promotion={promotion} />);
    const products = screen.getByRole("list", { name: "Products in this promotion" });
    const row = within(products).getByRole("button", { name: "Show P004 in the store" });
    expect(row.textContent).toContain(p004.slot_id);
    expect(row.textContent).toContain(`${p004.shelf_quantity}/${p004.facings} on shelf`);

    fireEvent.click(row);
    expect(selectedProductId(useUiStore.getState())).toBe("P004");
  });

  it("show a SKU the twin lacks, but cannot select it", () => {
    render(<PromotionCard promotion={promotion} />);
    const products = screen.getByRole("list", { name: "Products in this promotion" });
    expect(products.textContent).toContain("P999");
    expect(products.textContent).toContain("Not in the store");
    expect(within(products).queryByRole("button", { name: "Show P999 in the store" })).toBeNull();
  });
});
