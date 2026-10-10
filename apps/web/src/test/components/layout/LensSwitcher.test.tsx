// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { LENS } from "@/enums/ui.enum";
import { usePanelStore } from "@/state/panel.store";
import { useUiStore } from "@/state/ui.store";
import { AgentActivityOpenButton, AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { LensSwitcher } from "@/components/layout/LensSwitcher";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));
vi.mock("@/core/notify", () => ({
  errorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
  notify: { error: vi.fn(), warning: vi.fn(), info: vi.fn(), success: vi.fn() },
}));

/** apps/api does not serve the revenue and promotions routes yet. */
const fetchMock = vi.fn(async (_url: RequestInfo | URL) => new Response("{}", { status: 404 }));
const requested = () => fetchMock.mock.calls.map(([url]) => new URL(String(url)).pathname + new URL(String(url)).search);

MotionGlobalConfig.skipAnimations = true;

beforeEach(() => {
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  usePanelStore.setState({ open: true });
  useUiStore.setState({ lens: LENS.Operations });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function renderShell() {
  return render(
    <>
      <LensSwitcher />
      <AgentActivityOpenButton />
      <AgentActivityPanel />
    </>,
  );
}

test("opening revenue reads GET /revenue for the period, and shows zeros until it lands", async () => {
  renderShell();
  fireEvent.click(screen.getByRole("radio", { name: "Revenue" }));

  expect(await screen.findByRole("heading", { name: "Revenue", level: 1 })).toBeTruthy();
  expect(screen.getByRole("radio", { name: "Today" }).getAttribute("aria-checked")).toBe("true");
  expect(screen.getByText("No sales in this period yet.")).toBeTruthy();
  await waitFor(() => expect(requested()).toContain("/revenue?period=today"));

  fireEvent.click(screen.getByRole("radio", { name: "7 days" }));
  expect(screen.getByRole("heading", { name: "Revenue by day" })).toBeTruthy();
  await waitFor(() => expect(requested()).toContain("/revenue?period=7d"));
});

test("opening promotions reads GET /promotions, and says when there are none", async () => {
  renderShell();
  fireEvent.click(screen.getByRole("radio", { name: "Promotions" }));

  expect(await screen.findByText("No promotions yet.")).toBeTruthy();
  await waitFor(() => expect(requested()).toContain("/promotions"));
  const filter = screen.getByRole("radiogroup", { name: "Filter by status" });
  fireEvent.click(within(filter).getByRole("radio", { name: /In review/ }));
  expect(await screen.findByText("No promotions with this status.")).toBeTruthy();
});

test("arrow keys move the lens, and picking one reopens a closed panel", async () => {
  renderShell();
  fireEvent.click(screen.getByRole("button", { name: "Close the Agent Activity panel" }));
  expect(await screen.findByRole("button", { name: "Open the Agent Activity panel" })).toBeTruthy();

  fireEvent.keyDown(screen.getByRole("radio", { name: "Operations" }), { key: "ArrowLeft" });
  expect(useUiStore.getState().lens).toBe(LENS.Promotions);
  expect(usePanelStore.getState().open).toBe(true);
  expect(await screen.findByRole("heading", { name: "Promotions", level: 1 })).toBeTruthy();
});
