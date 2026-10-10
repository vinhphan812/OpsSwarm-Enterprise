// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { stockedStoreState } from "@/test/stockedState";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { format } from "@/core/utils/format";
import { SAMPLE_CHECKOUTS, SAMPLE_SALES } from "@/test/checkoutSample";

// The app has no checkout data until apps/api serves it; tests stand in the expected shape.
vi.mock("@/hooks/checkout.hook", async () => {
  const { SAMPLE_CHECKOUTS, SAMPLE_SALES } = await import("@/test/checkoutSample");
  return {
    useCheckoutSummary: (id: string) => SAMPLE_CHECKOUTS[id] ?? null,
    useCheckoutTransactions: (id: string, enabled: boolean) => (enabled && id === "CK01" ? SAMPLE_SALES : []),
  };
});

beforeEach(() => {
  useTwinStore.setState({ live: stockedStoreState(), issues: [], status: TWIN_STATUS.Ready });
  useUiStore.getState().select(null);
});

afterEach(cleanup);

test("shows nothing while nothing is selected", () => {
  const { container } = render(<EntityInspector />);
  expect(container.textContent).toBe("");
});

test("shows a shelf's stock from the twin, and selects a product from its list", () => {
  useUiStore.getState().select("A01", ENTITY_TYPE.Shelf);
  render(<EntityInspector />);
  const card = screen.getByLabelText("Essentials A01");
  expect(card.textContent).toContain("3 / 72");
  expect(card.textContent).toContain("Out");

  fireEvent.click(screen.getByRole("button", { name: "Select P002" }));
  expect(selectedProductId(useUiStore.getState())).toBe("P002");
  expect(screen.getByLabelText("Product P002").textContent).toContain("A01 / A01-S20");
});

test("shows a checkout's figures", () => {
  useUiStore.getState().select("CK01", ENTITY_TYPE.Equipment);
  render(<EntityInspector />);
  const card = screen.getByLabelText("Checkout CK01");
  expect(card.textContent).toContain("Linh Tran (EMP-014)");
  expect(card.textContent).toContain(format.moneyExact(SAMPLE_CHECKOUTS.CK01.revenue_today));
  expect(card.textContent).toContain("Open");
});

test("closes and clears the selection", () => {
  useUiStore.getState().select("GDC01", ENTITY_TYPE.Equipment);
  render(<EntityInspector />);
  expect(screen.getByLabelText("Fresh food GDC01")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(useUiStore.getState().selectedEntityId).toBeNull();
});

test("opens today's payments of a checkout, filtered by method or a search", async () => {
  useUiStore.getState().select("CK01", ENTITY_TYPE.Equipment);
  render(<EntityInspector />);
  fireEvent.click(screen.getByRole("button", { name: "View payments" }));

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Payments at CK01")).toBeTruthy();
  const rows = () => within(dialog).getAllByRole("row", { name: /^Show what CK01-\d+ bought$/ });
  expect(rows()).toHaveLength(SAMPLE_SALES.length);
  expect(dialog.textContent).toContain(format.moneyExact(SAMPLE_CHECKOUTS.CK01.revenue_today));

  fireEvent.click(within(dialog).getByRole("radio", { name: "Cash" }));
  const cash = rows();
  expect(cash.length).toBeGreaterThan(0);
  expect(cash.every((row) => row.textContent?.includes("Cash"))).toBe(true);

  fireEvent.click(within(dialog).getByRole("radio", { name: "All" }));
  fireEvent.change(within(dialog).getByRole("searchbox", { name: "Search transaction or cashier" }), {
    target: { value: "CK01-0001" },
  });
  expect(rows()).toHaveLength(1);

  // A sale opens its receipt; its lines add up to the sale.
  const sale = SAMPLE_SALES.find((item) => item.transaction_id === "CK01-0001")!;
  fireEvent.click(rows()[0]);
  expect(rows()[0].getAttribute("aria-expanded")).toBe("true");
  const receipt = within(dialog).getByRole("table", { name: "Receipt CK01-0001" });
  for (const line of sale.lines) expect(receipt.textContent).toContain(line.sku);
  expect(receipt.textContent).toContain(format.moneyExact(sale.total));

  // A SKU on the receipt selects the product in the 3D view and closes the dialog.
  const first = sale.lines[0].sku;
  fireEvent.click(within(receipt).getByRole("button", { name: `Show ${first} in the store` }));
  expect(selectedProductId(useUiStore.getState())).toBe(first);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

