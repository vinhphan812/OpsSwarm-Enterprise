// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { ACTIVITY_VIEW } from "@/enums/agent.enum";
import { demoAgentRun } from "@/fixtures/demo/agentRun";
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
  useUiStore.getState().setActivityView(ACTIVITY_VIEW.Runs);
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

function stepStatuses(card: HTMLElement) {
  return within(card)
    .getAllByRole("listitem")
    .filter((item) => item.classList.contains("run-step"))
    .map((item) => item.getAttribute("data-status"));
}

test("shows the demo run as one card with all eight stages done", () => {
  demoAgentRun().forEach((entry) => useRunStore.getState().append(entry));
  renderPanel();
  const cards = screen.getAllByTestId("agent-run");
  expect(cards).toHaveLength(1);
  expect(stepStatuses(cards[0])).toEqual(Array(8).fill("done"));
  expect(within(cards[0]).getByText("Reached VERIFY")).toBeTruthy();
  expect(within(cards[0]).getByText("Restocking P003 +12 on A01-S21.")).toBeTruthy();
});

test("highlights the stage a run is on and leaves later stages pending", () => {
  demoAgentRun()
    .slice(0, 6)
    .forEach((entry) => useRunStore.getState().append(entry));
  renderPanel();
  const card = screen.getByTestId("agent-run");
  expect(stepStatuses(card)).toEqual(["done", "done", "done", "done", "done", "active", "pending", "pending"]);
  expect(within(card).getByText("At GUARD")).toBeTruthy();
  const current = card.querySelector('[aria-current="step"]');
  expect(current?.textContent).toContain("GUARD");
});

test("lists entries of no run below the cards", () => {
  demoAgentRun()
    .slice(0, 2)
    .forEach((entry) => useRunStore.getState().append(entry));
  useRunStore.getState().append({ id: "loose", ts: "2026-10-16T08:00:00Z", stage: "OBSERVE", summary: "Heartbeat." });
  renderPanel();
  const loose = screen.getByRole("list", { name: "Not part of a run" });
  expect(within(loose).getByText("Heartbeat.")).toBeTruthy();
  expect(within(screen.getByTestId("agent-run")).queryByText("Heartbeat.")).toBeNull();
});

test("switches to the raw log and back", async () => {
  demoAgentRun().forEach((entry) => useRunStore.getState().append(entry));
  renderPanel();
  fireEvent.click(screen.getByRole("button", { name: "Log" }));
  await waitFor(() => expect(screen.queryByTestId("agent-run")).toBeNull());
  const log = screen.getByRole("list", { name: "Agent activity timeline" });
  expect(within(log).getAllByRole("listitem")).toHaveLength(8);

  fireEvent.click(screen.getByRole("button", { name: "Runs" }));
  expect(await screen.findAllByTestId("agent-run")).toHaveLength(1);
  expect(screen.queryByRole("list", { name: "Agent activity timeline" })).toBeNull();
});
