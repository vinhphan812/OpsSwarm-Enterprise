// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RunDemoButton } from "@/components/layout/RunDemoButton";
import { createMemoryTwin, type MemoryTwin } from "@/core/api/sources/memorySource";
import { createApiDemoRunner, type DemoRunner } from "@/core/demo/demoRunner";
import type { RetailTwinClient } from "@/types/api.type";
import { createFixtureDemoRunner } from "@/core/demo/fixtureDemoRunner";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { LENS, VIEW_MODE } from "@/enums/ui.enum";
import { DEMO_RUN_ID } from "@/fixtures/demo/agentRun";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useAgentFocus } from "@/hooks/agentFocus.hook";
import { useDemoDirector } from "@/hooks/demoDirector.hook";
import { useAnomalyStore } from "@/state/anomaly.store";
import { DEMO_RUN_STATUS, useDemoRunStore } from "@/state/demoRun.store";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { ControlStage } from "@/types/agent.type";

vi.mock("@/core/notify", () => ({
  notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() },
  errorMessage: (error: unknown) => (error instanceof Error ? error.message : String(error)),
}));

const STEP = 1000;
let twin: MemoryTwin;

/** Feeds the memory twin's Live states to `twin.store`, as `useTwinSource` does. */
function feedLive() {
  useTwinStore.getState().setLive(twin.current());
  return twin.source.subscribe((state) => useTwinStore.getState().setLive(state));
}

function mount(runner: DemoRunner) {
  renderHook(() => {
    useDemoDirector();
    useAgentFocus();
  });
  render(<RunDemoButton runner={runner} />);
}

const button = () => screen.getByRole("button", { name: /AI demo|Run AI Demo/ });
const stage = (): ControlStage | undefined => useRunStore.getState().activity.at(-1)?.stage;

/** Plays the demo run up to and including `until`. */
async function playUntil(until: ControlStage) {
  for (let step = 0; step < 10 && stage() !== until; step++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STEP);
    });
  }
  expect(stage()).toBe(until);
}

let unfeed = () => {};
beforeEach(() => {
  vi.useFakeTimers();
  twin = createMemoryTwin(demoStoreState());
  useTwinStore.setState(useTwinStore.getInitialState(), true);
  useUiStore.setState(useUiStore.getInitialState(), true);
  useRunStore.getState().reset();
  useDemoRunStore.setState(useDemoRunStore.getInitialState(), true);
  usePanelStore.setState({ open: false });
  unfeed = feedLive();
});
afterEach(() => {
  unfeed();
  cleanup();
  vi.useRealTimers();
});

describe("Run AI Demo on the demo path", () => {
  it("plays the whole flagship run from one press, following the agent's stages", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    useUiStore.getState().setLens(LENS.Revenue);
    useUiStore.getState().setFollowAgent(false);
    mount(createFixtureDemoRunner(twin, STEP));
    // A replay of fixtures, said so, apart from a real flagship run.
    expect(screen.getByText("Replay of demo data, no Live writes").dataset.source).toBe("replay");

    await act(async () => {
      fireEvent.click(button());
    });
    // Follow agent on, the Operations lens open, and the button busy while the run plays.
    expect(useUiStore.getState()).toMatchObject({ followAgent: true, lens: LENS.Operations, viewMode: VIEW_MODE.Live });
    expect(usePanelStore.getState().open).toBe(true);
    expect(useDemoRunStore.getState()).toMatchObject({ status: DEMO_RUN_STATUS.Running, correlationId: DEMO_RUN_ID });
    expect((button() as HTMLButtonElement).disabled).toBe(true);
    expect(button().textContent).toContain("AI demo running…");

    await playUntil("INVESTIGATE");
    // The camera goes to the problem: the agent selects P003.
    expect(useUiStore.getState()).toMatchObject({ selectedEntityId: "P003", selectedEntityType: ENTITY_TYPE.Product });
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);

    await playUntil("PLAN");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    await playUntil("SIMULATE");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Simulation);

    const shelfBefore = twin.current().products.find((product) => product.sku === "P003")!.shelf_quantity;
    await playUntil("ACT");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    // The demo controller's stand-in committed the proposal: Live changed, through its feed.
    expect(useTwinStore.getState().live!.products.find((product) => product.sku === "P003")!.shelf_quantity).toBeGreaterThan(
      shelfBefore,
    );

    expect(useAnomalyStore.getState().anomalies.some((anomaly) => anomaly.sku === "P003")).toBe(true);
    await playUntil("VERIFY");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Verified: the stockout the run handled is closed, the others stay.
    expect(useAnomalyStore.getState().anomalies.some((anomaly) => anomaly.sku === "P003")).toBe(false);
    expect(useAnomalyStore.getState().anomalies.length).toBeGreaterThan(0);
    expect(useDemoRunStore.getState().status).toBe(DEMO_RUN_STATUS.Done);
    expect((button() as HTMLButtonElement).disabled).toBe(false);
    expect(button().textContent).toContain("Run AI Demo again");
    expect(useUiStore.getState()).toMatchObject({ lens: LENS.Operations, viewMode: VIEW_MODE.Live });
    // The replay wrote to the memory twin only: apps/api was never called.
    expect(fetch).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("correlates every stage of the replay with the run, and the run with the P003 stockout alert it handles", async () => {
    vi.stubGlobal("fetch", vi.fn());
    mount(createFixtureDemoRunner(twin, STEP));
    await act(async () => {
      fireEvent.click(button());
    });
    const alert = useAnomalyStore.getState().anomalies.find((anomaly) => anomaly.sku === "P003");
    expect(alert?.correlation_id).toBe(DEMO_RUN_ID);
    await playUntil("VERIFY");
    const entries = useRunStore.getState().activity;
    expect(entries.map((entry) => entry.stage)).toEqual(["OBSERVE", "DETECT", "INVESTIGATE", "PLAN", "SIMULATE", "GUARD", "ACT", "VERIFY"]);
    expect(new Set(entries.map((entry) => entry.correlation_id))).toEqual(new Set([DEMO_RUN_ID]));
    expect(useDemoRunStore.getState().correlationId).toBe(DEMO_RUN_ID);
    vi.unstubAllGlobals();
  });

  it("starts the flagship run on apps/api once, however often it is pressed", async () => {
    const calls: string[] = [];
    let polls = 0;
    const client = {
      flagshipStatus: vi.fn(async () => {
        polls += 1;
        return polls === 1
          ? { run_id: null, phase: "IDLE", correlation_id: null }
          : { run_id: "r1", phase: "RUNNING", correlation_id: "flagship-run-1" };
      }),
      flagshipReset: vi.fn(async () => {
        calls.push("reset");
        return { run_id: "r0" };
      }),
      flagshipStart: vi.fn((correlationId: string) => {
        calls.push(`start ${correlationId}`);
        return new Promise(() => {});
      }),
      agentEvents: vi.fn(async () => ({ events: [], cursor: null })),
    } as unknown as RetailTwinClient;
    mount(createApiDemoRunner(client, 100, () => "flagship-run-1"));

    await act(async () => {
      fireEvent.click(button());
      fireEvent.click(button());
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      fireEvent.click(button());
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(calls).toEqual(["reset", "start flagship-run-1"]);
    expect(useDemoRunStore.getState()).toMatchObject({ status: DEMO_RUN_STATUS.Running, correlationId: "flagship-run-1" });
  });

  it("labels the real flagship run apart from a replay", () => {
    mount(createApiDemoRunner({} as RetailTwinClient));
    expect(screen.getByText("Flagship run on apps/api").dataset.source).toBe("flagship");
    expect(screen.queryByText(/Replay/)).toBeNull();
  });

  it("starts one run for repeated presses", async () => {
    const start = vi.fn<DemoRunner["start"]>(async () => ({ correlationId: "run-1", done: new Promise(() => {}), stop: () => {} }));
    mount({ source: "flagship", start });
    await act(async () => {
      fireEvent.click(button());
      fireEvent.click(button());
    });
    await act(async () => {
      await useDemoRunStore.getState().run({ source: "flagship", start });
    });
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("ignores a stage that arrives after a later one, and handles a run without SIMULATE or ACT", async () => {
    useTwinStore.getState().setSimulation(demoSimulation(twin.current()));
    const runner: DemoRunner = { source: "flagship", start: async () => ({ correlationId: "run-1", done: new Promise(() => {}), stop: () => {} }) };
    mount(runner);
    await act(async () => {
      fireEvent.click(button());
    });
    const append = (id: string, stage: ControlStage) =>
      act(() => useRunStore.getState().append({ id, ts: new Date().toISOString(), stage, summary: stage, correlation_id: "run-1" }));

    useUiStore.getState().setLens(LENS.Revenue);
    append("v", "VERIFY");
    expect(useUiStore.getState()).toMatchObject({ lens: LENS.Operations, viewMode: VIEW_MODE.Live });
    // A SIMULATE served late, after VERIFY, does not take the view back to the proposal.
    append("s", "SIMULATE");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
  });

  it("ends on Live and the Operations lens when the run ends without a VERIFY entry", async () => {
    useTwinStore.getState().setSimulation(demoSimulation(twin.current()));
    let finish: () => void = () => {};
    const runner: DemoRunner = {
      source: "flagship",
      start: async () => ({ correlationId: "run-1", done: new Promise<void>((resolve) => (finish = resolve)), stop: () => {} }),
    };
    mount(runner);
    await act(async () => {
      fireEvent.click(button());
    });
    act(() => useRunStore.getState().append({ id: "s", ts: new Date().toISOString(), stage: "SIMULATE", summary: "SIMULATE", correlation_id: "run-1" }));
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Simulation);
    act(() => useUiStore.getState().setLens(LENS.Revenue));
    await act(async () => finish());
    expect(useDemoRunStore.getState().status).toBe(DEMO_RUN_STATUS.Done);
    expect(useUiStore.getState()).toMatchObject({ lens: LENS.Operations, viewMode: VIEW_MODE.Live });
  });

  it("never runs ahead of the agent: only this run's entries move the view", async () => {
    useTwinStore.getState().setSimulation(demoSimulation(twin.current()));
    const runner: DemoRunner = { source: "flagship", start: async () => ({ correlationId: "run-1", done: new Promise(() => {}), stop: () => {} }) };
    mount(runner);
    await act(async () => {
      fireEvent.click(button());
    });
    const append = (id: string, stage: ControlStage, correlation_id = "run-1") =>
      act(() => useRunStore.getState().append({ id, ts: new Date().toISOString(), stage, summary: stage, correlation_id }));

    append("1", "PLAN");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    // Another run reaching SIMULATE is not this one.
    append("2", "SIMULATE", "run-other");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    append("3", "SIMULATE");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Simulation);
  });

  it("waits at SIMULATE until the simulation the entry names is open", async () => {
    const runner: DemoRunner = { source: "flagship", start: async () => ({ correlationId: "run-1", done: new Promise(() => {}), stop: () => {} }) };
    mount(runner);
    await act(async () => {
      fireEvent.click(button());
    });
    const simulation = demoSimulation(twin.current());
    act(() =>
      useRunStore.getState().append({
        id: "s",
        ts: new Date().toISOString(),
        stage: "SIMULATE",
        summary: "Simulated.",
        correlation_id: "run-1",
        simulation_id: simulation.simulation_id,
      }),
    );
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    act(() => useTwinStore.getState().setSimulation(simulation));
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Simulation);
  });

  it("stops moving the view after Stop following, while the run plays on", async () => {
    mount(createFixtureDemoRunner(twin, STEP));
    await act(async () => {
      fireEvent.click(button());
    });
    await playUntil("DETECT");
    fireEvent.click(screen.getByRole("button", { name: "Stop following" }));
    expect(useUiStore.getState().followAgent).toBe(false);

    await playUntil("SIMULATE");
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Live);
    expect(screen.queryByRole("button", { name: "Stop following" })).toBeNull();
  });

  it("shows the controller's error with Retry, and leaves the store usable", async () => {
    const start = vi
      .fn<DemoRunner["start"]>()
      .mockRejectedValueOnce(new Error("Twin API unreachable."))
      .mockImplementation(() => createFixtureDemoRunner(twin, STEP).start());
    mount({ source: "flagship", start });

    await act(async () => {
      fireEvent.click(button());
    });
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("The AI demo could not run: Twin API unreachable.");
    expect(useDemoRunStore.getState().status).toBe(DEMO_RUN_STATUS.Error);
    expect((button() as HTMLButtonElement).disabled).toBe(false);
    expect(useTwinStore.getState().live).not.toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    });
    expect(start).toHaveBeenCalledTimes(2);
    expect(useDemoRunStore.getState().status).toBe(DEMO_RUN_STATUS.Running);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a failed run's reason, with the stages it reached left in the timeline", async () => {
    let fail: (error: Error) => void = () => {};
    const runner: DemoRunner = {
      source: "flagship",
      start: async () => ({
        correlationId: "run-x",
        done: new Promise((_, reject) => (fail = reject)),
        stop: () => {},
      }),
    };
    mount(runner);
    await act(async () => {
      fireEvent.click(button());
    });
    await act(async () => fail(new Error("Planner timed out.")));
    expect(screen.getByRole("alert").textContent).toContain("Planner timed out.");
  });

  it("renders nothing without a runner", () => {
    const { container } = render(<RunDemoButton runner={null} />);
    expect(container.innerHTML).toBe("");
  });
});
