// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { AiImpactDialog } from "@/components/twin/AiImpactDialog";
import { AiImpactToast } from "@/components/twin/AiImpactToast";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import { createMemoryTwin } from "@/core/api/sources/memorySource";
import { notify } from "@/core/notify";
import { createMemoryReviewer } from "@/core/twin/memorySimulation";
import { IMPACT_TOAST_MS } from "@/constants/app.constant";
import { ACTIVITY_VIEW } from "@/enums/agent.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoAgentRun } from "@/fixtures/demo/agentRun";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useImpactStore } from "@/state/impact.store";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

vi.mock("@/core/notify", () => ({ notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));
vi.mock("@/components/status/StoreStatus", () => ({ StoreStatus: () => null }));

MotionGlobalConfig.skipAnimations = true;

const live = demoStoreState();

/** Opens the demo run with its candidates on a memory twin, showing `candidateId` (null: its own proposal). */
function openDemo(candidateId: string | null) {
  const twin = createMemoryTwin(live);
  useTwinStore.setState({ ...useTwinStore.getInitialState(), live, simulation: demoSimulation(live) }, true);
  useTwinStore.getState().setCandidates(demoCandidates(live));
  useTwinStore.getState().selectCandidate(candidateId);
  useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
  return twin;
}

async function accept() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
  });
}

function playRun(count = 8) {
  act(() => demoAgentRun().slice(0, count).forEach((entry) => useRunStore.getState().append(entry)));
}

function renderAll(twin: ReturnType<typeof createMemoryTwin>) {
  return render(
    <>
      <SimulationBanner reviewer={createMemoryReviewer(twin)} />
      <AiImpactToast />
      <AiImpactDialog />
      <AgentActivityPanel />
    </>,
  );
}

const impactCard = () => screen.queryByTestId("ai-impact");
const toast = () => screen.queryByTestId("ai-impact-toast");
/** The demo run's card. */
const runCard = () => screen.getByTestId("agent-run");
/** The step `stage` of the demo run's card. */
const runStep = (stage: string) =>
  [...runCard().querySelectorAll<HTMLElement>(".run-step")].find(
    (step) => step.querySelector(".run-step-name")?.firstChild?.textContent === stage,
  )!;
const runChanges = () => within(runCard()).queryByRole("region", { name: "AI changes" });

beforeEach(() => {
  usePanelStore.setState({ open: true });
  useRunStore.getState().reset();
  useImpactStore.setState(useImpactStore.getInitialState(), true);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
  useUiStore.getState().setActivityView(ACTIVITY_VIEW.Runs);
});

describe("Projected impact", () => {
  it("shows the fixture baseline/simulated numbers once the run of an accepted candidate reaches VERIFY", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    expect(useImpactStore.getState().last?.candidate_id).toBe("cand-b");

    playRun(7);
    expect(impactCard()).toBeNull();
    expect(toast()).toBeNull();

    playRun();
    const card = impactCard()!;
    expect(within(card).getByText("Plan cand-b")).toBeTruthy();
    const stockout = within(card).getByText("Stockout risk").closest("li")!;
    expect(stockout.textContent).toContain("0.40→0.15");
    expect(within(stockout).getByLabelText("-0.25, better")).toBeTruthy();
    const cost = within(card).getByText("Movement cost").closest("li")!;
    expect(within(cost).getByLabelText("+0.12, worse")).toBeTruthy();
    expect(within(card).queryByText(/\$/)).toBeNull();
    expect(within(card).getByText("Projected impact")).toBeTruthy();
    expect(within(card).queryByText(/AI Impact|Before|After/)).toBeNull();
    expect(within(card).getByText(/Not measured in the store/)).toBeTruthy();
    expect(within(card).getByText("Verifier: inconclusive")).toBeTruthy();
    expect(within(toast()!).getByText("Verifier: inconclusive")).toBeTruthy();
  });

  it("shows the verifier's status as served, apart from the projection", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    const run = demoAgentRun();
    act(() => {
      run.slice(0, 7).forEach((entry) => useRunStore.getState().append(entry));
      useRunStore.getState().append({ ...run[7], status: "REGRESSION" });
    });
    expect(within(impactCard()!).getByText("Verifier: regression")).toBeTruthy();
  });

  it("says so when the VERIFY entry serves no status", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    const run = demoAgentRun();
    act(() => {
      run.slice(0, 7).forEach((entry) => useRunStore.getState().append(entry));
      useRunStore.getState().append({ ...run[7], status: undefined });
    });
    expect(within(impactCard()!).getByText("Verifier: no status served")).toBeTruthy();
  });

  it("shows no impact card for a run the guard sent back with REFRESH_REQUIRED", async () => {
    const twin = openDemo("cand-b");
    twin.update((state) => ({ ...state, context_version: `${state.context_version}-moved` }));
    renderAll(twin);
    await accept();
    expect(notify.warning).toHaveBeenCalledWith(expect.stringContaining("needs a new simulation"), expect.anything());
    playRun();
    expect(useImpactStore.getState().last).toBeNull();
    expect(impactCard()).toBeNull();
    expect(toast()).toBeNull();
  });

  it("shows no impact card when the accepted proposal is not a candidate", async () => {
    const twin = openDemo(null);
    renderAll(twin);
    await accept();
    playRun();
    expect(impactCard()).toBeNull();
  });

  it("shows the toast once, for a while, and keeps the card in the panel", async () => {
    const twin = openDemo("cand-a");
    renderAll(twin);
    await accept();
    vi.useFakeTimers();
    playRun();
    expect(toast()).not.toBeNull();
    act(() => vi.advanceTimersByTime(IMPACT_TOAST_MS));
    vi.useRealTimers();
    await waitFor(() => expect(toast()).toBeNull());
    expect(impactCard()).not.toBeNull();

    act(() => useRunStore.getState().append({ ...demoAgentRun()[7], id: "again" }));
    expect(toast()).toBeNull();
  });

  it("dismisses the toast", async () => {
    const twin = openDemo("cand-a");
    renderAll(twin);
    await accept();
    playRun();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss the projected impact" }));
    await waitFor(() => expect(toast()).toBeNull());
  });

  it("links to the comparison of the run's candidates, with the accepted one marked", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    playRun();
    fireEvent.click(within(impactCard()!).getByRole("button", { name: "Compare plans" }));
    const dialog = await screen.findByRole("dialog");
    const headers = within(dialog).getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headers).toEqual(["KPI", "Current", "cand-a", "cand-bAccepted", "cand-c"]);
  });
});

describe("In the AI Run card", () => {
  it("puts the projected impact under the run's VERIFY step, and only there", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    playRun();
    expect(screen.getAllByTestId("ai-impact")).toHaveLength(1);
    expect(runStep("VERIFY").contains(impactCard())).toBe(true);
  });

  it("shows the projected impact above the log in the log view, which has no run card", async () => {
    const twin = openDemo("cand-b");
    renderAll(twin);
    await accept();
    playRun();
    act(() => useUiStore.getState().setActivityView(ACTIVITY_VIEW.Log));
    await waitFor(() => expect(screen.queryByTestId("agent-run")).toBeNull());
    expect(screen.getAllByTestId("ai-impact")).toHaveLength(1);
    expect(within(impactCard()!).getByText("Verifier: inconclusive")).toBeTruthy();
  });

  it("lists the executed AI CHANGES under ACT: Live before against the committed proposal", async () => {
    const twin = openDemo(null);
    renderAll(twin);
    await accept();
    playRun(7);
    const list = runChanges()!;
    expect(runStep("ACT").contains(list)).toBe(true);
    expect(within(list).getByText("5 changes")).toBeTruthy();
    const moved = within(within(list).getByRole("list", { name: "Moved" }))
      .getAllByRole("button")
      .map((row) => row.textContent);
    expect(moved).toEqual(["P005A03-S22 → B01-S22", "P007B02-S20 → B02-S22", "P008C01-S21 → A02-S22"]);
  });

  it("keeps the list once the run has closed and Live has moved on", async () => {
    const twin = openDemo(null);
    renderAll(twin);
    await accept();
    playRun();
    act(() => useTwinStore.setState({ simulation: null, candidates: [] }));
    expect(within(runChanges()!).getByText("5 changes")).toBeTruthy();
  });

  it("lists no AI CHANGES before an approval is committed", () => {
    openDemo(null);
    renderAll(createMemoryTwin(live));
    playRun();
    expect(runChanges()).toBeNull();
  });

  it("lists no AI CHANGES for a run the guard sent back with REFRESH_REQUIRED", async () => {
    const twin = openDemo(null);
    twin.update((state) => ({ ...state, context_version: `${state.context_version}-moved` }));
    renderAll(twin);
    await accept();
    playRun();
    expect(useImpactStore.getState().executed).toBeNull();
    expect(runChanges()).toBeNull();
  });
});
