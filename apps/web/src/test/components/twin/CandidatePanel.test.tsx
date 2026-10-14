// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CandidatePanel } from "@/components/twin/CandidatePanel";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { VIEW_MODE } from "@/enums/ui.enum";

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

describe("CandidatePanel", () => {
  it("renders nothing when no simulation is open", () => {
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when no candidate is selected", () => {
    open();
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the selected candidate's id when one is selected", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    expect(screen.getByText("Candidate cand-a")).toBeTruthy();
  });

  it("shows KPI scores when the candidate has them", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    // cand-a has Revenue Impact and Stockout Risk
    expect(screen.getByText("Revenue Impact")).toBeTruthy();
    expect(screen.getByText("12.0%")).toBeTruthy();
  });

  it("formats currency KPI values with dollar sign and two decimal places", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    expect(screen.getByText("$1,240.50")).toBeTruthy();
  });

  it("shows KPI scores for every candidate that has them", () => {
    open();
    // cand-b has Revenue Impact and Stockout Risk in the demo fixture
    act(() => useTwinStore.getState().selectCandidate("cand-b"));
    render(<CandidatePanel />);
    expect(screen.getByText("Revenue Impact")).toBeTruthy();
    expect(screen.getByText("$380.20")).toBeTruthy();
  });

  it("shows the provenance in a collapsible section", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-c"));
    render(<CandidatePanel />);
    expect(screen.getByText("Provenance")).toBeTruthy();
    // Text should be hidden by default (collapsed)
    expect(screen.queryByText(/movement-only plan/i)).toBeNull();
    // Expand it
    fireEvent.click(screen.getByRole("button", { name: /provenance/i }));
    expect(screen.getByText(/movement-only plan/i)).toBeTruthy();
  });

  it("shows all candidate buttons in the selector", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    expect(screen.getByRole("button", { name: /cand-a/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /cand-b/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /cand-c/i })).toBeTruthy();
    expect(screen.getByRole("button", { name: /original/i })).toBeTruthy();
  });

  it("switches the selected candidate when a candidate button is clicked", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    expect(screen.getByText("Candidate cand-a")).toBeTruthy();

    act(() => fireEvent.click(screen.getByRole("button", { name: /cand-b/i })));
    expect(screen.getByText("Candidate cand-b")).toBeTruthy();
  });

  it("switches back to the simulation's own proposal via 'Original' button", () => {
    open();
    act(() => useTwinStore.getState().selectCandidate("cand-a"));
    render(<CandidatePanel />);
    expect(screen.getByText("Candidate cand-a")).toBeTruthy();

    act(() => fireEvent.click(screen.getByRole("button", { name: /original/i })));
    const { container } = render(<CandidatePanel />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing in the Live view even with a candidate selected", () => {
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
