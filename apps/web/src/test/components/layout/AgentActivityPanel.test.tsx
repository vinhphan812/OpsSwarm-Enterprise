// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { usePanelStore } from "@/state/panel.store";
import { AgentActivityOpenButton, AgentActivityPanel } from "@/components/layout/AgentActivityPanel";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

beforeEach(() => {
  usePanelStore.setState({ open: true });
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
