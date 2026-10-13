// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { AgentActivityOpenButton, AgentActivityPanel } from "@/components/layout/AgentActivityPanel";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

beforeEach(() => {
  usePanelStore.setState({ open: true });
  useRunStore.getState().reset();
  useUiStore.getState().select(null);
});

afterEach(cleanup);

function renderPanel() {
  return render(
    <>
      <AgentActivityOpenButton />
      <AgentActivityPanel />
    </>,
  );
}

test("closes the panel and opens it again from the floating button", async () => {
  renderPanel();
  expect(screen.queryByRole("button", { name: "Open the Agent Activity panel" })).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "Close the Agent Activity panel" }));
  await waitFor(() => expect(screen.queryByTestId("agent-activity")).toBeNull());

  fireEvent.click(await screen.findByRole("button", { name: "Open the Agent Activity panel" }));
  expect(screen.getByTestId("agent-activity")).toBeTruthy();
});

test("has a fixed width and no resize handle", () => {
  renderPanel();
  expect(screen.getByTestId("agent-activity").style.width).toBe(`${PANEL_WIDTH}px`);
  expect(screen.queryByRole("separator")).toBeNull();
});

test("selects the product of a timeline entry, so the scene highlights and focuses it", () => {
  useRunStore.getState().append({
    id: "a1",
    ts: "2026-10-09T08:00:00Z",
    stage: "DETECT",
    summary: "P001 is out of stock on A01-S01.",
    sku: "P001",
  });
  renderPanel();
  const sku = screen.getByRole("button", { name: "Show P001 in the store" });
  expect(sku.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(sku);
  expect(selectedProductId(useUiStore.getState())).toBe("P001");
  expect(sku.getAttribute("aria-pressed")).toBe("true");
});

test("turns Follow agent off and on again", () => {
  useUiStore.getState().setFollowAgent(true);
  renderPanel();
  const follow = screen.getByRole("switch", { name: "Follow agent" }) as HTMLInputElement;
  expect(follow.checked).toBe(true);

  fireEvent.click(follow);
  expect(useUiStore.getState().followAgent).toBe(false);
  fireEvent.click(follow);
  expect(useUiStore.getState().followAgent).toBe(true);
});
