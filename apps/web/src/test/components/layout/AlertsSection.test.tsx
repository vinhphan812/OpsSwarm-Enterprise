// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { ANOMALY_SEVERITY, ANOMALY_TYPE } from "@/enums/anomaly.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { TWIN_STATUS } from "@/enums/twin.enum";
import { DEMO_RUN_ID, demoAgentRun } from "@/fixtures/demo/agentRun";
import { anomalyFor, demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { VIEW_MODE } from "@/enums/ui.enum";
import { useAnomalyStore } from "@/state/anomaly.store";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";

vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

const state = demoStoreState();
const product = (sku: string) => state.products.find((item) => item.sku === sku)!;
/** The demo's "publish demand spike": a demand surge raised on P005 with no prompt. */
const surgeOnP005 = () =>
  anomalyFor(product("P005"), ANOMALY_TYPE.DemandSurge, ANOMALY_SEVERITY.Medium, state.context_version);
const p003 = () => demoAnomalies(state).anomalies.find((anomaly) => anomaly.sku === "P003")!;

const alertList = () => screen.getByRole("list", { name: "Open alerts and opportunities" });
const alertButton = (name: RegExp) => within(alertList()).getByRole("button", { name });

beforeEach(() => {
  usePanelStore.setState({ open: true });
  useRunStore.getState().reset();
  useAnomalyStore.setState({ anomalies: [], readError: null });
  useTwinStore.setState({ live: state, issues: [], status: TWIN_STATUS.Ready, simulation: null, candidates: [], selectedCandidateId: null });
  useUiStore.getState().select(null);
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
});

afterEach(cleanup);

describe("Alerts & opportunities", () => {
  test("says so when nothing is open", () => {
    render(<AgentActivityPanel />);
    expect(screen.getByText("No open alerts or opportunities.")).toBeTruthy();
  });

  test("shows a demand surge as an opportunity on its SKU as soon as it is raised", () => {
    render(<AgentActivityPanel />);
    act(() => useAnomalyStore.getState().raise(surgeOnP005()));

    const item = alertButton(/Opportunity: Demand for P005 is above forecast/);
    expect(within(item).getByText("P005 · shelf A03")).toBeTruthy();
    expect(within(item).getByText("Agent: Detected")).toBeTruthy();
    expect(item.getAttribute("data-severity")).toBe("medium");
  });

  test("lists the worst first and marks every other kind as an alert", () => {
    useAnomalyStore.getState().setAll(demoAnomalies(state));
    render(<AgentActivityPanel />);
    const items = within(alertList()).getAllByRole("button");
    expect(items).toHaveLength(demoAnomalies(state).anomalies.length);
    expect(items[0].getAttribute("data-severity")).toBe("critical");
    expect(items.at(-1)!.getAttribute("data-severity")).toBe("low");
    expect(items.filter((item) => item.getAttribute("data-category") === "opportunity")).toHaveLength(1);
  });

  test("moves through the lifecycle as the correlated agent run goes on, and leaves once resolved", () => {
    useAnomalyStore.getState().raise(p003());
    render(<AgentActivityPanel />);
    const item = () => alertButton(/Alert: P003 is out of stock/);
    expect(within(item()).getByText("Agent: Detected")).toBeTruthy();

    const run = demoAgentRun(DEMO_RUN_ID);
    const stepOf = { INVESTIGATE: "Investigating", PLAN: "Planning", GUARD: "Guarding", ACT: "Acting", VERIFY: "Verifying" };
    for (const entry of run) {
      act(() => useRunStore.getState().append(entry));
      const step = stepOf[entry.stage as keyof typeof stepOf];
      if (step) expect(within(item()).getByText(`Agent: ${step}`)).toBeTruthy();
    }

    act(() => useAnomalyStore.getState().resolve(p003().anomaly_id));
    expect(screen.queryByRole("button", { name: /Alert: P003 is out of stock/ })).toBeNull();
  });

  test("ignores agent runs of other anomalies", () => {
    useAnomalyStore.getState().raise(surgeOnP005());
    demoAgentRun(DEMO_RUN_ID).forEach((entry) => useRunStore.getState().append(entry));
    render(<AgentActivityPanel />);
    expect(within(alertButton(/Demand for P005/)).getByText("Agent: Detected")).toBeTruthy();
  });

  test("picking an alert selects its product, flies to it, and narrows the timeline to its run", async () => {
    useAnomalyStore.getState().raise(p003());
    demoAgentRun(DEMO_RUN_ID).forEach((entry) => useRunStore.getState().append(entry));
    useRunStore.getState().append({ id: "other", ts: new Date().toISOString(), stage: "OBSERVE", summary: "Another run.", correlation_id: "x" });
    render(<AgentActivityPanel />);
    const runIds = () => screen.getAllByTestId("agent-run").map((card) => card.getAttribute("data-run"));
    expect(runIds()).toEqual(["x", DEMO_RUN_ID]);
    const seq = useUiStore.getState().focusSeq;

    const item = alertButton(/P003 is out of stock/);
    fireEvent.click(item);
    const ui = useUiStore.getState();
    expect(selectedProductId(ui)).toBe("P003");
    expect(ui.selectedEntityType).toBe(ENTITY_TYPE.Product);
    expect(ui.focusSeq).toBe(seq + 1);
    expect(item.getAttribute("aria-pressed")).toBe("true");
    await waitFor(() => expect(runIds()).toEqual([DEMO_RUN_ID]));
    expect(screen.queryByText("Another run.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Show every run" }));
    await waitFor(() => expect(runIds()).toEqual(["x", DEMO_RUN_ID]));
    expect(selectedProductId(useUiStore.getState())).toBe("P003");
  });

  test("a later selection of the user's own clears the timeline filter", () => {
    useAnomalyStore.getState().raise(p003());
    render(<AgentActivityPanel />);
    fireEvent.click(alertButton(/P003 is out of stock/));
    expect(screen.getByText("The agent has not started on this yet.")).toBeTruthy();

    act(() => useUiStore.getState().select("P005"));
    expect(screen.queryByRole("button", { name: "Show every run" })).toBeNull();
    expect(useUiStore.getState().focusedCorrelationId).toBeNull();
  });

  test("a failed read says so and keeps the last list, until a read succeeds", () => {
    useAnomalyStore.getState().setAll(demoAnomalies(state));
    render(<AgentActivityPanel />);
    const count = within(alertList()).getAllByRole("button").length;

    act(() => useAnomalyStore.getState().fail("GET /anomalies returned 503."));
    expect(
      screen.getByRole("status").textContent,
    ).toBe("Could not read the alerts; showing the last list received, which may be out of date. GET /anomalies returned 503.");
    expect(within(alertList()).getAllByRole("button")).toHaveLength(count);

    act(() => useAnomalyStore.getState().setAll(demoAnomalies(state)));
    expect(screen.queryByRole("status")).toBeNull();
  });

  test("a failed first read says so instead of claiming nothing is open", () => {
    useAnomalyStore.getState().fail("GET /anomalies returned 503.");
    render(<AgentActivityPanel />);
    expect(screen.getByRole("status").textContent).toBe("Could not read the alerts. GET /anomalies returned 503.");
    expect(screen.queryByText("No open alerts or opportunities.")).toBeNull();
  });

  test("an alert about a whole shelf focuses that shelf", () => {
    useAnomalyStore.getState().setAll(demoAnomalies(state));
    render(<AgentActivityPanel />);
    const item = alertButton(/Shelf A02 breaks its planogram/);
    expect(within(item).getByText("Shelf A02")).toBeTruthy();
    fireEvent.click(item);
    expect(useUiStore.getState()).toMatchObject({ selectedEntityId: "A02", selectedEntityType: ENTITY_TYPE.Shelf });
  });

  test("shows an anomaly as apps/api serves it today: detector title and description, no run to follow", () => {
    useAnomalyStore.getState().raise({
      anomaly_id: "anm-api-1",
      anomaly_type: ANOMALY_TYPE.Stockout,
      severity: ANOMALY_SEVERITY.Critical,
      store_id: state.store_id,
      sku: "P003",
      shelf_id: "A01",
      title: "Stockout detected for P003",
      description: "Shelf count reached 0 at 08:00.",
      detected_at: "2026-10-09T08:00:00Z",
      event_ids: ["evt-1"],
      metadata: {},
    });
    demoAgentRun(DEMO_RUN_ID).forEach((entry) => useRunStore.getState().append(entry));
    render(<AgentActivityPanel />);
    const item = alertButton(/Alert: Stockout detected for P003/);
    expect(within(item).getByText("Shelf count reached 0 at 08:00.")).toBeTruthy();
    expect(within(item).getByText("Agent: Detected")).toBeTruthy();

    fireEvent.click(item);
    expect(selectedProductId(useUiStore.getState())).toBe("P003");
    expect(useUiStore.getState().focusedCorrelationId).toBeNull();
    expect(screen.queryByRole("button", { name: "Show every run" })).toBeNull();
  });

  test("lists nothing in the Simulation view, since anomalies describe Live", () => {
    useAnomalyStore.getState().setAll(demoAnomalies(state));
    useTwinStore.getState().setSimulation(demoSimulation(state));
    render(<AgentActivityPanel />);
    expect(screen.getByRole("list", { name: "Open alerts and opportunities" })).toBeTruthy();

    act(() => useUiStore.getState().setViewMode(VIEW_MODE.Simulation));
    expect(screen.queryByRole("list", { name: "Open alerts and opportunities" })).toBeNull();
    expect(screen.getByText("Alerts describe the Live store. Switch to Live to see them.")).toBeTruthy();
  });

  test("an alert on a SKU missing from the twin cannot be picked, and says so", () => {
    useTwinStore.setState({ live: { ...state, products: state.products.filter((item) => item.sku !== "P005") } });
    useAnomalyStore.getState().raise(surgeOnP005());
    render(<AgentActivityPanel />);
    const item = alertButton(/Demand for P005/) as HTMLButtonElement;
    expect(item.disabled).toBe(true);
    expect(within(item).getByText("Not in the Digital Twin, cannot be shown")).toBeTruthy();
    fireEvent.click(item);
    expect(selectedProductId(useUiStore.getState())).toBeNull();
  });
});
