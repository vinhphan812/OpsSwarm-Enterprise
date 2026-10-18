// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import { createMemoryTwin, patchProduct, type MemoryTwin } from "@/core/api/sources/memorySource";
import { notify } from "@/core/notify";
import { createMemoryReviewer } from "@/core/twin/memorySimulation";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import { GUARD_VERDICT, REVIEW_DECISION, SIMULATION_STATUS } from "@/enums/simulation.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { useGuardStore } from "@/state/guard.store";
import { usePanelStore } from "@/state/panel.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { ReviewResult, Simulation } from "@/types/simulation.type";

vi.mock("@/core/notify", () => ({ notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));

const live = demoStoreState();

function open(simulation: Simulation = demoSimulation(live)) {
  useTwinStore.setState({ ...useTwinStore.getInitialState(), live, simulation }, true);
  useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
  return simulation;
}

const accept = () => screen.getByRole("button", { name: /Accept/ });
const reject = () => screen.getByRole("button", { name: /Reject/ });
const actions = () => screen.queryByRole("group", { name: "Review this proposal" });

/** Presses a button and lets the review's promise settle. */
async function press(button: HTMLElement) {
  await act(async () => {
    fireEvent.click(button);
  });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => {
  cleanup();
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
  useGuardStore.getState().clear();
});

describe("Accept and Reject on the simulation banner", () => {
  it("are offered only for an evaluated run, and only with a reviewer", () => {
    open();
    const { rerender } = render(<SimulationBanner />);
    expect(actions()).toBeNull();

    rerender(<SimulationBanner reviewer={vi.fn()} />);
    expect(actions()).not.toBeNull();

    act(() => useTwinStore.getState().setSimulation({ ...demoSimulation(live), status: SIMULATION_STATUS.Pending }));
    expect(actions()).toBeNull();
  });

  it("Accept sends the run to the reviewer and leaves the twin state to the feeds", async () => {
    const simulation = open();
    const result: ReviewResult = {
      simulation_id: simulation.simulation_id,
      decision: REVIEW_DECISION.Approve,
      status: SIMULATION_STATUS.Committed,
      verdict: GUARD_VERDICT.Allow,
      reason_code: null,
      live_context_version: "store-001:v2",
      detail_code: null,
      guard: null,
    };
    const reviewer = vi.fn<SimulationReviewer>(async () => result);
    render(<SimulationBanner reviewer={reviewer} />);

    await press(accept());
    expect(reviewer).toHaveBeenCalledWith(simulation, REVIEW_DECISION.Approve);
    expect(notify.success).toHaveBeenCalledWith(
      `${simulation.simulation_id} accepted`,
      "Committed. Live is now store-001:v2.",
    );
    // Live and the run change only through their feeds: the banner waits for the run to close.
    expect(useTwinStore.getState().live).toBe(live);
    expect(useTwinStore.getState().simulation).toBe(simulation);
    expect(actions()).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Reviewed, waiting for Live");
    // An approval leaves no proposal to play back: Live changes through its feed.
    expect(useTwinStore.getState().leftProposal).toBeNull();
  });

  it("disables both buttons while a review is on its way", async () => {
    open();
    let answer: (result: ReviewResult) => void = () => {};
    const reviewer = vi.fn<SimulationReviewer>(() => new Promise((resolve) => (answer = resolve)));
    render(<SimulationBanner reviewer={reviewer} />);

    await press(reject());
    expect(accept()).toHaveProperty("disabled", true);
    expect(reject()).toHaveProperty("disabled", true);
    await press(accept());
    expect(reviewer).toHaveBeenCalledTimes(1);

    await act(async () =>
      answer({
        simulation_id: "sim-demo-001",
        decision: REVIEW_DECISION.Reject,
        status: SIMULATION_STATUS.Rejected,
        verdict: null,
        reason_code: null,
        live_context_version: null,
        detail_code: null,
        guard: null,
      }),
    );
    expect(notify.info).toHaveBeenCalledWith("sim-demo-001 rejected", "The store did not change.");
    // The rejected proposal was on screen, so the scene plays its changes back to Live.
    expect(useTwinStore.getState().leftProposal?.state).toBe(useTwinStore.getState().simulation?.state);
  });

  it("says why the guard refused, and keeps the buttons for a later review", async () => {
    const simulation = open();
    const refused = (verdict: ReviewResult["verdict"], reason_code: string | null): ReviewResult => ({
      simulation_id: simulation.simulation_id,
      decision: REVIEW_DECISION.Approve,
      status: SIMULATION_STATUS.Evaluated,
      verdict,
      reason_code,
      live_context_version: null,
      detail_code: null,
      guard: null,
    });
    const reviewer = vi
      .fn<SimulationReviewer>()
      .mockResolvedValueOnce(refused(GUARD_VERDICT.RefreshRequired, "live_moved"))
      .mockResolvedValueOnce(refused(GUARD_VERDICT.Deny, "over_capacity"))
      .mockRejectedValueOnce(new Error("Request failed (404)."));
    render(<SimulationBanner reviewer={reviewer} />);

    await press(accept());
    expect(notify.warning).toHaveBeenCalledWith(
      `${simulation.simulation_id} needs a new simulation`,
      `Live has changed since ${simulation.base_context_version}, so the guard refused this proposal. Nothing was committed.`,
    );
    await press(accept());
    expect(notify.warning).toHaveBeenLastCalledWith(`The guard denied ${simulation.simulation_id}`, "over_capacity");
    await press(accept());
    expect(notify.error).toHaveBeenCalledWith("Could not send the review", expect.any(Error));
    expect(actions()).not.toBeNull();
  });

  it("says when a rejection was refused because the proposal changed, and keeps the buttons", async () => {
    const simulation = open();
    const reviewer = vi.fn<SimulationReviewer>(async () => ({
      simulation_id: simulation.simulation_id,
      decision: REVIEW_DECISION.Reject,
      status: SIMULATION_STATUS.Evaluated,
      verdict: null,
      reason_code: "proposal_changed",
      live_context_version: null,
      detail_code: null,
      guard: null,
    }));
    render(<SimulationBanner reviewer={reviewer} />);

    await press(reject());
    expect(notify.info).not.toHaveBeenCalled();
    expect(notify.warning).toHaveBeenCalledWith(
      `${simulation.simulation_id} was not rejected`,
      "The proposal changed after you reviewed it. Nothing was changed; review the new one.",
    );
    expect(actions()).not.toBeNull();
  });

  it("offers the buttons again for a proposal replaced under the same run id", async () => {
    const simulation = open();
    const reviewer = vi.fn<SimulationReviewer>(async () => ({
      simulation_id: simulation.simulation_id,
      decision: REVIEW_DECISION.Reject,
      status: SIMULATION_STATUS.Rejected,
      verdict: null,
      reason_code: null,
      live_context_version: null,
      detail_code: null,
      guard: null,
    }));
    render(<SimulationBanner reviewer={reviewer} />);

    await press(reject());
    expect(actions()).toBeNull();
    act(() =>
      useTwinStore
        .getState()
        .setSimulation({ ...simulation, state: { ...simulation.state, context_version: `${simulation.state.context_version}-r2` } }),
    );
    expect(actions()).not.toBeNull();
  });
});

describe("the simulation banner beside the Agent Activity panel", () => {
  afterEach(() => usePanelStore.getState().setOpen(true));

  it("stops short of the open panel, so the panel never covers Accept, Reject or Compare plans", () => {
    open();
    usePanelStore.getState().setOpen(true);
    const { rerender } = render(<SimulationBanner reviewer={vi.fn()} />);
    const banner = screen.getByRole("status", { name: "Simulation view" });
    expect(banner.dataset.panel).toBe("open");
    expect(banner.style.maxWidth).toBe(`min(600px, calc(100% - ${PANEL_WIDTH + 56}px))`);

    act(() => usePanelStore.getState().setOpen(false));
    rerender(<SimulationBanner reviewer={vi.fn()} />);
    expect(banner.dataset.panel).toBeUndefined();
    expect(banner.style.maxWidth).toBe("min(600px, calc(100% - 32px))");
  });
});

describe("Accept on the memory twin (?twin=memory|demo)", () => {
  let twin: MemoryTwin;

  beforeEach(() => {
    twin = createMemoryTwin(live);
  });

  it("commits the proposal through the live feed and closes the run", async () => {
    const pushed: string[] = [];
    twin.source.subscribe((state) => pushed.push(state.context_version));
    open();
    render(<SimulationBanner reviewer={createMemoryReviewer(twin)} />);

    await press(accept());
    expect(pushed).toHaveLength(1);
    expect(useTwinStore.getState().simulation).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("is refused once Live has moved on, and nothing is committed", async () => {
    open();
    twin.update((state) => patchProduct(state, "P002", { shelf_quantity: 9 }));
    const moved = twin.current();
    render(<SimulationBanner reviewer={createMemoryReviewer(twin)} />);

    await press(accept());
    expect(twin.current()).toEqual(moved);
    expect(notify.warning).toHaveBeenCalledTimes(1);
    expect(useTwinStore.getState().simulation).not.toBeNull();
  });
});
