// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PANEL_WIDTH, PANEL_WIDTH_STEP } from "@/constants/app.constant";
import { usePanelStore } from "@/state/panel.store";
import { AgentActivityOpenButton, AgentActivityPanel } from "@/components/layout/AgentActivityPanel";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

beforeEach(() => {
  usePanelStore.setState({ open: true, width: PANEL_WIDTH.default });
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

test("resizes with the arrow keys within the allowed range", () => {
  renderPanel();
  const handle = screen.getByRole("separator", { name: "Drag to resize the panel" });

  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(usePanelStore.getState().width).toBe(PANEL_WIDTH.default + PANEL_WIDTH_STEP);

  for (let i = 0; i < 50; i++) fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(usePanelStore.getState().width).toBe(PANEL_WIDTH.max);

  for (let i = 0; i < 50; i++) fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(usePanelStore.getState().width).toBe(PANEL_WIDTH.min);

  fireEvent.doubleClick(handle);
  expect(usePanelStore.getState().width).toBe(PANEL_WIDTH.default);
});
