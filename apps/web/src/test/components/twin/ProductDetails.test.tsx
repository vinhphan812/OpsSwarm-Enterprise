// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { ProductDetailsDialog } from "@/components/twin/ProductDetailsDialog";
import { PromotionsPanel } from "@/components/promotions/PromotionsPanel";
import { ANOMALY_KIND, ANOMALY_SEVERITY } from "@/enums/anomaly.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { LENS } from "@/enums/ui.enum";
import { useAnomalyStore } from "@/state/anomaly.store";
import { usePanelStore } from "@/state/panel.store";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { stockedStoreState } from "@/test/stockedState";
import { patchProduct } from "@/core/api/sources/memorySource";

vi.mock("@/hooks/checkout.hook", () => ({ useCheckoutSummary: () => null, useCheckoutTransactions: () => [] }));
// apps/api serves no promotions yet; the dialog reads them through usePromotions.
vi.mock("@/hooks/commerce.hook", async () => {
  const { PROMOTION_KIND, PROMOTION_STATUS } = await import("@/enums/commerce.enum");
  const promotion = (id: string, name: string, skus: string[]) => ({
    id,
    name,
    status: PROMOTION_STATUS.Active,
    kind: PROMOTION_KIND.PercentOff,
    value: 0.15,
    starts_at: "2026-10-06T00:00:00Z",
    ends_at: "2026-10-13T00:00:00Z",
    skus,
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
  });
  const summary = {
    store_id: "store-001",
    revenue: 0,
    incremental_revenue: 0,
    discount_cost: 0,
    promotions: [promotion("promo-1", "Pasta night bundle", ["P004", "P007"]), promotion("promo-2", "Breakfast week", ["P001"])],
  };
  return { usePromotions: () => summary };
});

MotionGlobalConfig.skipAnimations = true;

const state = stockedStoreState();
const p004 = state.products.find((product) => product.sku === "P004")!;

beforeEach(() => {
  useTwinStore.setState({ live: state, issues: [], status: TWIN_STATUS.Ready });
  useAnomalyStore.setState({ anomalies: [] });
  useUiStore.setState({ lens: LENS.Operations, detailsSku: null, focusedPromotionId: null });
  useUiStore.getState().select(null);
  usePanelStore.setState({ open: false });
});

afterEach(cleanup);

function renderPage() {
  return render(
    <>
      <EntityInspector />
      <ProductDetailsDialog />
    </>,
  );
}

describe("product details dialog", () => {
  it("opens from the product card with the twin figures, anomalies, and promotions of the product", async () => {
    useUiStore.getState().select("P004");
    useAnomalyStore.getState().raise({
      anomaly_id: "anm-P004",
      store_id: p004.store_id,
      sku: "P004",
      shelf_id: p004.shelf_id,
      slot_id: p004.slot_id,
      kind: ANOMALY_KIND.LowStock,
      severity: ANOMALY_SEVERITY.Medium,
      detected_at: "2026-10-09T08:00:00Z",
      context_version: state.context_version,
      correlation_id: "run-1",
    });
    renderPage();
    fireEvent.click(within(screen.getByLabelText("Product P004")).getByRole("button", { name: "Details" }));

    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Product P004");
    expect(dialog.textContent).toContain(`Shelf ${p004.shelf_id} · slot ${p004.slot_id}`);
    const stock = within(dialog).getByRole("region", { name: "In the Digital Twin" });
    expect(stock.textContent).toContain(`${p004.shelf_quantity}of ${p004.facings} facings`);
    expect(stock.textContent).toContain(String(p004.backroom_quantity));
    const anomalies = within(dialog).getByRole("list", { name: "Open anomalies" });
    expect(anomalies.textContent).toContain("Low stock");
    expect(anomalies.textContent).toContain("medium");
    const promotions = within(dialog).getByRole("region", { name: "Promotions" });
    expect(promotions.textContent).toContain("Pasta night bundle");
    expect(promotions.textContent).not.toContain("Breakfast week");
  });

  it("opens from a shelf's product list, and shows the product in the store", async () => {
    useUiStore.getState().select(p004.shelf_id, ENTITY_TYPE.Shelf);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Details of P004" }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Show in the store" }));
    expect(selectedProductId(useUiStore.getState())).toBe("P004");
    await waitFor(() => expect(useUiStore.getState().detailsSku).toBeNull());
  });

  it("opens the Promotions lens on a promotion of the product, with the product selected", async () => {
    useUiStore.getState().showDetails("P004");
    renderPage();
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "View Pasta night bundle in Promotions" }));
    expect(useUiStore.getState()).toMatchObject({ lens: LENS.Promotions, focusedPromotionId: "promo-1", detailsSku: null });
    expect(selectedProductId(useUiStore.getState())).toBe("P004");
    expect(usePanelStore.getState().open).toBe(true);
  });

  it("says when a product is in no promotion", async () => {
    useUiStore.getState().showDetails("P002");
    renderPage();
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Not in any promotion.");
    expect(dialog.textContent).toContain("No open anomalies.");
    expect(within(dialog).queryByRole("button", { name: /in Promotions$/ })).toBeNull();
  });

  it("shows a recent restock's deltas, a one-sided one's flag, and the units the facings cannot hold", async () => {
    useUiStore.getState().showDetails("P001");
    renderPage();
    // P001 starts with 8 on the shelf and 42 in the backroom.
    act(() => useTwinStore.getState().setLive(patchProduct(state, "P001", { shelf_quantity: 12, backroom_quantity: 38 })));
    const dialog = await screen.findByRole("dialog");
    expect(dialog.textContent).toContain("Shelf +4");
    expect(dialog.textContent).toContain("Backroom -4");
    expect(dialog.textContent).not.toContain("Inconsistent transfer");
    expect(dialog.textContent).not.toContain("not shown");

    act(() => useTwinStore.getState().setLive(patchProduct(state, "P001", { shelf_quantity: 500, backroom_quantity: 38 })));
    expect(dialog.textContent).toContain("Inconsistent transfer");
    expect(dialog.textContent).toMatch(/\+\d+ not shown/);
  });
});

describe("promotions lens", () => {
  it("flashes the promotion it was opened on, and shows every status so the card is there", async () => {
    render(<PromotionsPanel />);
    fireEvent.click(screen.getByRole("radio", { name: "Draft" }));
    await waitFor(() => expect(document.getElementById("promotion-promo-1")).toBeNull());

    act(() => useUiStore.getState().focusPromotion("promo-1"));
    await waitFor(() => expect(document.getElementById("promotion-promo-1")?.hasAttribute("data-focused")).toBe(true));
    expect(screen.getByRole("radio", { name: "All" }).getAttribute("aria-checked")).toBe("true");
    expect(useUiStore.getState().focusedPromotionId).toBeNull();
    expect(document.getElementById("promotion-promo-2")?.hasAttribute("data-focused")).toBe(false);
  });
});
