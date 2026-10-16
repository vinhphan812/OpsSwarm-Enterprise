// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import { createMemoryTwin } from "@/core/api/sources/memorySource";
import { reviewOnTwin } from "@/core/twin/memorySimulation";
import { changedSkus, diffStates } from "@/core/twin/stateDiff";
import { BASELINE_CANDIDATE_ID, GUARD_VERDICT, KPI_NAME, REVIEW_DECISION, REVIEW_REASON, SIMULATION_STATUS } from "@/enums/simulation.enum";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { slotMarksOf } from "@/scene/entities/stock/SlotMarks";
import { toSceneStore } from "@/scene/layout";
import { activeState, selectedCandidate, shownSimulation, useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

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

const shown = () => activeState(useTwinStore.getState(), useUiStore.getState().viewMode);
const candidate = (id: string) => demoCandidates(live).find((item) => item.candidate_id === id)!;
const slotOf = (sku: string) => live.products.find((product) => product.sku === sku)!.slot_id;

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  useUiStore.setState(useUiStore.getInitialState(), true);
});

describe("demo candidates", () => {
  const proposals = () => demoCandidates(live).filter((item) => item.candidate_id !== BASELINE_CANDIDATE_ID);

  it("are 2–3 different proposals of the demo simulation, each with a version of its own", () => {
    const candidates = proposals();
    expect(candidates.length).toBeGreaterThanOrEqual(2);
    expect(candidates.length).toBeLessThanOrEqual(3);
    expect(new Set(candidates.map((item) => item.simulation_id))).toEqual(new Set(["sim-demo-001"]));
    expect(new Set(candidates.map((item) => item.state.context_version)).size).toBe(candidates.length);
    const changes = candidates.map((item) => changedSkus(diffStates(live, item.state)).join());
    expect(new Set(changes).size).toBe(candidates.length);
    expect(live).toEqual(demoStoreState());
  });

  it("include a baseline with no actions on the base state", () => {
    const baseline = demoCandidates(live).find((item) => item.candidate_id === BASELINE_CANDIDATE_ID)!;
    expect(baseline.proposed_actions).toEqual([]);
    expect(changedSkus(diffStates(live, baseline.state))).toEqual([]);
  });

  it("score every candidate on the simulation-kpi-v1 fields, with the evaluator's business score formula", () => {
    for (const item of demoCandidates(live)) {
      const value = Object.fromEntries(item.kpis.map((kpi) => [kpi.name, kpi.value]));
      expect(Object.keys(value).sort()).toEqual(Object.values(KPI_NAME).sort());
      const score = value.revenue_benefit + 0 * value.margin_benefit + value.service_level - value.stockout_risk - value.movement_cost;
      expect(value.business_score).toBeCloseTo(score, 10);
      expect(item.evaluator_version).toBe("simulation-kpi-v1");
    }
  });
});

describe("selected candidate", () => {
  beforeEach(() => useTwinStore.setState(useTwinStore.getInitialState(), true));

  it("drives the Simulation view, and falls back to the simulation's own proposal", () => {
    const { simulation, candidates } = open();
    const byId = (id: string) => candidates.find((item) => item.candidate_id === id)!;
    expect(shown()).toBe(simulation.state);

    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    expect(shown()).toBe(byId("cand-b").state);
    expect(shownSimulation(useTwinStore.getState(), VIEW_MODE.Simulation)).toMatchObject({
      simulation_id: simulation.simulation_id,
      actions: byId("cand-b").proposed_actions,
    });
    // One object per selection, so selectors stay stable.
    expect(shownSimulation(useTwinStore.getState(), VIEW_MODE.Simulation)).toBe(
      shownSimulation(useTwinStore.getState(), VIEW_MODE.Simulation),
    );

    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    expect(shown()).toBe(byId("cand-c").state);
    act(() => useTwinStore.getState().selectCandidate(null));
    expect(shown()).toBe(simulation.state);
  });

  it("leaves Live as it was while candidates are switched, and Live shows Live", () => {
    open();
    const before = structuredClone(live);
    for (const id of ["cand-a", "cand-b", "cand-c"]) act(() => useTwinStore.getState().selectCandidate(id));
    useUiStore.getState().setViewMode(VIEW_MODE.Live);
    expect(shown()).toBe(live);
    expect(useTwinStore.getState().live).toBe(live);
    expect(live).toEqual(before);
  });

  it("replays the change cues on every switch", () => {
    open();
    useTwinStore.setState({ simulationChangedAt: 1 });
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    expect(useTwinStore.getState().simulationChangedAt).toBeGreaterThan(1);
  });

  it("survives new candidates while it is among them, and is dropped with its run", () => {
    const { simulation } = open();
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    useTwinStore.getState().setCandidates(demoCandidates(live));
    expect(useTwinStore.getState().selectedCandidateId).toBe("cand-b");
    useTwinStore.getState().setCandidates([candidate("cand-a")]);
    expect(useTwinStore.getState().selectedCandidateId).toBeNull();

    useTwinStore.getState().setCandidates(demoCandidates(live));
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    useTwinStore.getState().setSimulation({ ...simulation });
    expect(useTwinStore.getState().selectedCandidateId).toBe("cand-b");
    useTwinStore.getState().setSimulation({ ...simulation, simulation_id: "sim-other" });
    expect(useTwinStore.getState().candidates).toEqual([]);
    expect(selectedCandidate(useTwinStore.getState())).toBeNull();
  });
});

describe("changed-entity highlight", () => {
  it("outlines every slot the selected proposal changes, a move's source slot included", () => {
    const outlined = (id: string) => {
      const proposal = candidate(id).state;
      const diff = diffStates(live, proposal);
      return slotMarksOf(toSceneStore(proposal).store, null, diff).proposed.map((box) => box.slotId).sort();
    };
    // Restock P003, re-face P004.
    expect(outlined("cand-b")).toEqual([slotOf("P003"), slotOf("P004")].sort());
    // Moves only: both ends of each move.
    expect(outlined("cand-c")).toEqual(
      ["B02-S20", "B02-S22", "C01-S21", "A02-S22", "A03-S22", "B01-S22"].sort(),
    );
    expect(slotMarksOf(toSceneStore(live).store, null, null).proposed).toEqual([]);
  });
});

describe("changes list on the banner", () => {
  beforeEach(() => useTwinStore.setState(useTwinStore.getInitialState(), true));

  it("counts the selected proposal's changed products and focuses one on click", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    render(<SimulationBanner />);
    expect(screen.getByText("2 changes")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "P004, Facings 3 → 4. Show it in 3D" }));
    expect(useUiStore.getState()).toMatchObject({ selectedEntityId: "P004", selectedEntityType: ENTITY_TYPE.Product });

    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    expect(screen.getByText("3 changes")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^P004/ })).toBeNull();
  });

  it("shows nothing in the Live view", () => {
    open();
    useUiStore.getState().setViewMode(VIEW_MODE.Live);
    const { container } = render(<SimulationBanner />);
    expect(container.innerHTML).toBe("");
  });
});

describe("reviewing a candidate on the memory twin", () => {
  beforeEach(() => useTwinStore.setState(useTwinStore.getInitialState(), true));

  it("commits the candidate on screen, and refuses a review of one no longer shown", () => {
    const twin = createMemoryTwin(live);
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    const reviewed = shownSimulation(useTwinStore.getState(), VIEW_MODE.Simulation)!;

    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    expect(reviewOnTwin(twin, reviewed, REVIEW_DECISION.Approve)).toMatchObject({
      status: SIMULATION_STATUS.Evaluated,
      reason_code: REVIEW_REASON.ProposalChanged,
    });

    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    expect(reviewOnTwin(twin, reviewed, REVIEW_DECISION.Approve)).toMatchObject({
      status: SIMULATION_STATUS.Committed,
      verdict: GUARD_VERDICT.Allow,
    });
    expect(twin.current().products).toEqual(
      candidate("cand-b").state.products.map((product) => expect.objectContaining({ ...product, version: expect.any(Number) })),
    );
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(useTwinStore.getState().candidates).toEqual([]);
  });
});
