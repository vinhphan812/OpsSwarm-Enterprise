// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CandidatePanel } from "@/components/twin/CandidatePanel";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { shownSimulation, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { VIEW_MODE } from "@/enums/ui.enum";
import { BASELINE_CANDIDATE_ID } from "@/enums/simulation.enum";

vi.mock("@/core/notify", () => ({ notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));

const live = demoStoreState();

/** Opens the demo simulation with its candidates on `live`, in the Simulation view. */
function open() {
  const simulation = demoSimulation(live);
  const candidates = demoCandidates(live);
  useTwinStore.setState({ ...useTwinStore.getInitialState(), live }, true);
  useTwinStore.getState().setSimulation(simulation);
  useTwinStore.getState().setCandidates(candidates);
  useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
  return { simulation, candidates };
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  useUiStore.setState(useUiStore.getInitialState(), true);
  useTwinStore.setState(useTwinStore.getInitialState(), true);
});

/** The column button of a plan, by its label: the demo serves cand-a, cand-b, cand-c as Plan A, B, C. */
const column = (plan: string) => screen.getByRole("button", { name: new RegExp(`^${plan}$`) });
/** The cells of the row headed `label`, as text. */
const row = (label: string) =>
  Array.from(screen.getByRole("rowheader", { name: label }).parentElement!.querySelectorAll("td")).map((cell) => cell.textContent);

describe("CandidatePanel", () => {
  it("renders nothing when no simulation is open", () => {
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when the run has no candidates", () => {
    open();
    act(() => useTwinStore.getState().setCandidates([]));
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the comparison and the A/B/C selector before any candidate is selected", () => {
    open();
    render(<CandidatePanel />);
    expect(screen.getByRole("region", { name: "Compare candidates" })).toBeTruthy();
    for (const plan of ["Plan A", "Plan B", "Plan C"]) expect(column(plan).getAttribute("aria-pressed")).toBe("false");
    expect(screen.getByText("Pick a plan to show it in 3D")).toBeTruthy();
  });

  it("offers the baseline as the Current column, never as a candidate to select", () => {
    open();
    render(<CandidatePanel />);
    expect(screen.getByRole("columnheader", { name: "Current" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /baseline/i })).toBeNull();
  });

  it("shows the exact served values, Current first, with the difference under each", () => {
    open();
    render(<CandidatePanel />);
    // Current, cand-a, cand-b, cand-c
    expect(row("Actions")).toEqual(["0", "5", "2", "3"]);
    expect(row("Stockout risk")).toEqual(["0.40", "0.10-0.30", "0.15-0.25", "0.400.00"]);
    expect(row("Service level")).toEqual(["0.35", "0.80+0.45", "0.75+0.40", "0.350.00"]);
    expect(row("Movement cost")).toEqual(["0.00", "0.30+0.30", "0.12+0.12", "0.15+0.15"]);
    expect(row("Business score")).toEqual(["-0.05", "0.85+0.90", "0.88+0.93", "-0.15-0.10"]);
    expect(screen.getByText("Scored by simulation-kpi-v1")).toBeTruthy();
  });

  it("colours a difference by the KPI's direction: lower stockout risk is better", () => {
    open();
    render(<CandidatePanel />);
    expect(screen.getByLabelText("-0.30 vs Current, better").dataset.trend).toBe("better");
    expect(screen.getAllByLabelText("+0.30 vs Current, worse")[0]!.dataset.trend).toBe("worse");
  });

  it("leads with the business score, the number the plans are ranked by", () => {
    open();
    render(<CandidatePanel />);
    expect(screen.getAllByRole("rowheader").map((cell) => cell.textContent)[0]).toBe("Business score");
  });

  it("stars the plan the agent recommends, with its served rationale under the table", () => {
    open();
    render(<CandidatePanel />);
    const badge = screen.getByText("AI recommends");
    expect(badge.closest("th")!.textContent).toContain("Plan B");
    expect(screen.getByText("Why AI chose Plan B:").parentElement!.textContent).toMatch(/far less movement/);
    expect(screen.queryByText("Top score")).toBeNull();
  });

  it("hides the rationale line when none is served, and never writes one itself", () => {
    const { candidates } = open();
    act(() => useTwinStore.getState().setCandidates(candidates.map((item) => ({ ...item, rationale: null }))));
    render(<CandidatePanel />);
    expect(screen.getByText("AI recommends")).toBeTruthy();
    expect(screen.queryByText(/Why AI chose/)).toBeNull();
  });

  it("with no recommendation served, stars nothing and marks the highest served business score", () => {
    const { candidates } = open();
    act(() => useTwinStore.getState().setCandidates(candidates.map((item) => ({ ...item, recommended: false }))));
    render(<CandidatePanel />);
    expect(screen.queryByText("AI recommends")).toBeNull();
    expect(screen.getByText("Top score").closest("th")!.textContent).toContain("Plan B");
  });

  it("selects a candidate from its column, and the Simulation view shows that candidate's state", () => {
    const { candidates } = open();
    render(<CandidatePanel />);
    act(() => fireEvent.click(column("Plan C")));
    expect(useTwinStore.getState().selectedCandidateId).toBe("cand-c");
    const shown = shownSimulation(useTwinStore.getState(), VIEW_MODE.Simulation)!;
    const cand = candidates.find((item) => item.candidate_id === "cand-c")!;
    expect(shown.state).toBe(cand.state);
    expect(shown.actions).toBe(cand.proposed_actions);
    expect(column("Plan C").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText("Showing Plan C in 3D")).toBeTruthy();

    act(() => fireEvent.click(column("Plan A")));
    expect(useTwinStore.getState().selectedCandidateId).toBe("cand-a");
    expect(column("Plan C").getAttribute("aria-pressed")).toBe("false");
  });

  it("goes back to the simulation's own proposal, and keeps the comparison", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    act(() => fireEvent.click(screen.getByRole("button", { name: /original/i })));
    expect(useTwinStore.getState().selectedCandidateId).toBeNull();
    expect(screen.getByRole("region", { name: "Compare candidates" })).toBeTruthy();
  });

  it("shows the selected candidate's provenance in a collapsible section", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    render(<CandidatePanel />);
    expect(screen.queryByText(/movement-only plan/i)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /provenance/i }));
    expect(screen.getByText(/movement-only plan/i)).toBeTruthy();
  });

  it("says so when no baseline is served, and shows no Current column or differences", () => {
    const { candidates } = open();
    act(() => useTwinStore.getState().setCandidates(candidates.filter((item) => item.candidate_id !== BASELINE_CANDIDATE_ID)));
    render(<CandidatePanel />);
    expect(screen.getByText(/No baseline served/)).toBeTruthy();
    expect(screen.queryByRole("columnheader", { name: "Current" })).toBeNull();
    expect(row("Stockout risk")).toEqual(["0.10", "0.15", "0.40"]);
  });

  it("marks a candidate the evaluator has not scored", () => {
    const { candidates } = open();
    act(() =>
      useTwinStore
        .getState()
        .setCandidates(candidates.map((item) => (item.candidate_id === "cand-c" ? { ...item, kpis: [] } : item))),
    );
    render(<CandidatePanel />);
    expect(row("Business score")[3]).toBe("Not scored");
  });

  it("says when nothing is scored at all", () => {
    const { candidates } = open();
    act(() => useTwinStore.getState().setCandidates(candidates.map((item) => ({ ...item, kpis: [] }))));
    render(<CandidatePanel />);
    expect(screen.getByText("No KPI scores available yet")).toBeTruthy();
    expect(screen.queryByText("Top score")).toBeNull();
  });

  it("shows a KPI name it has no label for as served", () => {
    const { candidates } = open();
    const extra = { name: "basket_size", value: 1.5, unit: "share", source: "simulation-kpi-v2" };
    act(() =>
      useTwinStore
        .getState()
        .setCandidates(candidates.map((item) => (item.candidate_id === "cand-a" ? { ...item, kpis: [...item.kpis, extra] } : item))),
    );
    render(<CandidatePanel />);
    expect(row("basket_size")).toEqual(["—", "1.50", "—", "—"]);
  });

  it("says the values are the last served when a refresh failed", () => {
    open();
    act(() => useTwinStore.getState().setSimulationReadFailed(true));
    render(<CandidatePanel />);
    expect(screen.getByRole("alert").textContent).toMatch(/Couldn't refresh the candidates/);
    act(() => useTwinStore.getState().setSimulationReadFailed(false));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders nothing in the Live view", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    useUiStore.getState().setViewMode(VIEW_MODE.Live);
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });
});

describe("candidate panel isolation from live state", () => {
  it("never writes to live state when switching candidates", () => {
    open();
    const liveBefore = structuredClone(useTwinStore.getState().live);
    const liveVersionBefore = liveBefore!.context_version;

    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    act(() => useTwinStore.getState().selectCandidate(null));

    expect(useTwinStore.getState().live).toEqual(liveBefore);
    expect(useTwinStore.getState().live?.context_version).toBe(liveVersionBefore);
  });

  it("never copies simulation state into live state", () => {
    open();
    const liveBefore = useTwinStore.getState().live;
    const simulationStateBefore = useTwinStore.getState().simulation?.state;

    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    // The live pointer must not change
    expect(useTwinStore.getState().live).toBe(liveBefore);
    // Live state must not be the simulation state
    expect(useTwinStore.getState().live).not.toBe(simulationStateBefore);
  });

  it("does not modify live issues when candidates change", () => {
    open();
    const issuesBefore = [...useTwinStore.getState().issues];

    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    act(() => useTwinStore.getState().selectCandidate(null));

    expect(useTwinStore.getState().issues).toEqual(issuesBefore);
  });
});
