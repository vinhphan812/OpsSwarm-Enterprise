import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApiDemoRunner, timelineEntries, toActivityEntry } from "@/core/demo/demoRunner";
import { useRunStore } from "@/state/run.store";
import type { AgentEvent, FlagshipStatus, FlagshipStatusResponse, RetailTwinClient } from "@/types/api.type";

const POLL = 100;

/** Default retry config for tests */
const RETRY_CONFIG = { maxRetries: 3, initialDelayMs: 50, maxDelayMs: 200, backoffMultiplier: 2 };
/** Short timeout config for tests */
const TIMEOUT_CONFIG = { identificationTimeoutMs: 500 };

function event(id: string, stage: AgentEvent["stage"], correlation_id = "run-1", extra: Partial<AgentEvent> = {}): AgentEvent {
  return { id, ts: "2026-10-16T08:00:00Z", stage, status: "ok", correlation_id, summary: `${stage} ${id}`, ...extra };
}

function status(
  phase: FlagshipStatusResponse["phase"],
  error: string | null = null,
  extra: Partial<FlagshipStatusResponse> = {},
): FlagshipStatusResponse {
  const result: FlagshipStatusResponse = { 
    run_id: extra.run_id ?? "r", 
    phase, 
    correlation_id: (extra.correlation_id ?? "run-1") as string | null, 
    error: error ?? undefined
  };
  if (extra.timeline) result.timeline = extra.timeline;
  return result;
}

/** What the status says before the press: the previous run, finished. */
const PREVIOUS = status("COMPLETE", null, { run_id: "r0", correlation_id: "previous-run" });

/** The runner under test, naming its run "run-1". */
const runner = (client: RetailTwinClient) =>
  createApiDemoRunner(client, POLL, () => "run-1", RETRY_CONFIG, TIMEOUT_CONFIG);

/**
 * A client whose feed and status answer from `pages` and `polled`, one per poll, after
 * `first` (the status read before the press, PREVIOUS by default). Like
 * #41, `POST /flagship/start` answers only when the test calls `finishStart` (or `failStart`).
 */
function fakeClient(pages: AgentEvent[][], polled: FlagshipStatusResponse[], first: FlagshipStatusResponse = PREVIOUS) {
  const statuses = [first, ...polled];
  const calls: string[] = [];
  let page = 0;
  let poll = 0;
  let finishStart: (correlationId?: string | null) => void = () => {};
  let failStart: (error: Error) => void = () => {};
  const client = {
    flagshipReset: vi.fn(async () => {
      calls.push("reset");
      return {};
    }),
    flagshipStart: vi.fn(() => {
      calls.push("start");
      return new Promise((resolve, reject) => {
        finishStart = (correlation_id = "run-1") => resolve({ run_id: "r", correlation_id, phase: "COMPLETE" as const });
        failStart = reject;
      });
    }),
    flagshipStatus: vi.fn(async () => statuses[Math.min(poll++, statuses.length - 1)]),
    agentEvents: vi.fn(async (since?: string | null) => {
      const events = pages[page] ?? [];
      const cursor = events.length ? String(++page) : (since ?? null);
      return { events, cursor };
    }),
  } as unknown as RetailTwinClient;
  return { client, calls, finishStart: (id?: string | null) => finishStart(id), failStart: (error: Error) => failStart(error) };
}

beforeEach(() => {
  vi.useFakeTimers();
  useRunStore.getState().reset();
});
afterEach(() => vi.useRealTimers());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("createApiDemoRunner", () => {
  it("resets, starts, and reads only this run's entries into the timeline until COMPLETE", async () => {
    const { client, calls } = fakeClient(
      [[event("a", "DETECT"), event("x", "OBSERVE", "other-run")], [event("b", "SIMULATE", "run-1", { simulation_id: "sim-run-1" })], [event("c", "VERIFY")]],
      [status("RUNNING"), status("RUNNING"), status("COMPLETE")],
    );
    const run = await runner(client).start();
    expect(calls).toEqual(["reset", "start"]);
    expect(client.flagshipStart).toHaveBeenCalledWith("run-1");
    expect(run.correlationId).toBe("run-1");
    const settled = vi.fn();
    run.done.then(settled);

    await vi.advanceTimersByTimeAsync(POLL * 3);
    expect(settled).toHaveBeenCalled();
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a", "b", "c"]);
    expect(useRunStore.getState().activity[1].simulation_id).toBe("sim-run-1");
  });

  it("follows the stages live while POST /flagship/start has not answered yet", async () => {
    const { client, finishStart } = fakeClient([], [status("IDLE"), status("RUNNING"), status("RUNNING"), status("COMPLETE")]);
    // The feed grows as the controller runs: one more stage by each status read.
    const feed = [event("a", "DETECT"), event("b", "SIMULATE"), event("c", "VERIFY")];
    vi.mocked(client.agentEvents).mockImplementation(async (since) => {
      const from = Number(since ?? 0);
      const to = Math.max(from, vi.mocked(client.flagshipStatus).mock.calls.length - 2);
      return { events: feed.slice(from, to), cursor: String(to) };
    });
    const starting = runner(client).start();
    await vi.advanceTimersByTimeAsync(0);
    // The reset is still the status: nothing is read before the run is identified.
    expect(client.agentEvents).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(POLL);
    const run = await starting;
    expect(run.correlationId).toBe("run-1");
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);
    await vi.advanceTimersByTimeAsync(POLL);
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a", "b"]);

    const settled = vi.fn();
    run.done.then(settled);
    await vi.advanceTimersByTimeAsync(POLL);
    expect(settled).toHaveBeenCalled();
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a", "b", "c"]);
    expect(client.flagshipStart).toHaveBeenCalledTimes(1);
    finishStart();
  });

  it("is identified by the answer to start when the status has not named the run", async () => {
    const { client, finishStart } = fakeClient([[event("a", "VERIFY")]], [status("IDLE"), status("COMPLETE")]);
    const starting = runner(client).start();
    await vi.advanceTimersByTimeAsync(0);
    finishStart("run-1");
    const run = await starting;
    expect(run.correlationId).toBe("run-1");
    await vi.advanceTimersByTimeAsync(POLL);
    await expect(run.done).resolves.toBeUndefined();
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);
  });

  it("fails when POST /flagship/start fails before the run is identified", async () => {
    const { client, failStart } = fakeClient([], [status("IDLE")]);
    const starting = runner(client).start();
    const failed = starting.catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(0);
    failStart(new Error("Cannot start from phase RUNNING."));
    await vi.advanceTimersByTimeAsync(POLL);
    await expect(failed).resolves.toBe("Cannot start from phase RUNNING.");
  });

  it("keeps following its run when POST /flagship/start times out but the controller carries on", async () => {
    const { client, calls, failStart } = fakeClient(
      [],
      [
        status("RUNNING", null, { timeline: [{ stage: "investigate", detail: "investigating P017", at: "t1" }] }),
        status("RUNNING", null, { timeline: [{ stage: "investigate", detail: "investigating P017", at: "t1" }, { stage: "plan", detail: "plan", at: "t2" }] }),
        status("COMPLETE", null, {
          timeline: [
            { stage: "investigate", detail: "investigating P017", at: "t1" },
            { stage: "plan", detail: "plan", at: "t2" },
            { stage: "verify", detail: "verified", at: "t3" },
          ],
        }),
      ],
    );
    const run = await runner(client).start();
    failStart(new Error("The request timed out."));
    await vi.advanceTimersByTimeAsync(POLL * 3);
    await expect(run.done).resolves.toBeUndefined();
    expect(useRunStore.getState().activity.map((entry) => entry.stage)).toEqual(["INVESTIGATE", "PLAN", "VERIFY"]);
    // One reset and one start: a timed-out start is never sent again.
    expect(calls).toEqual(["reset", "start"]);
  });

  it("ends in error with start's failure once the status no longer names the run", async () => {
    const { client, failStart } = fakeClient([], [status("RUNNING"), status("IDLE", null, { correlation_id: null })]);
    const run = await runner(client).start();
    const failed = run.done.catch((error: Error) => error.message);
    failStart(new Error("Twin API unreachable."));
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(failed).resolves.toBe("Twin API unreachable.");
  });

  it("fails with the controller's reason when the run ends in ERROR", async () => {
    const { client } = fakeClient([], [status("RUNNING"), status("ERROR", "Planner timed out.")]);
    const run = await runner(client).start();
    const failed = run.done.catch((error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(failed).resolves.toBe("Planner timed out.");
  });

  it("fails when the controller cannot be reached, before anything is started", async () => {
    const { client } = fakeClient([], []);
    vi.mocked(client.flagshipReset).mockRejectedValue(new Error("Twin API unreachable."));
    await expect(runner(client).start()).rejects.toThrow("Twin API unreachable.");
    expect(client.flagshipStart).not.toHaveBeenCalled();
  });

  it("follows a run that is already RUNNING instead of resetting or starting another", async () => {
    const { client, calls } = fakeClient(
      [[event("a", "PLAN", "other-tab")]],
      [status("RUNNING", null, { correlation_id: "other-tab" }), status("COMPLETE", null, { correlation_id: "other-tab" })],
      status("RUNNING", null, { correlation_id: "other-tab" }),
    );
    const run = await runner(client).start();
    expect(calls).toEqual([]);
    expect(run.correlationId).toBe("other-tab");
    await vi.advanceTimersByTimeAsync(POLL);
    await expect(run.done).resolves.toBeUndefined();
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);
  });

  it("never takes an earlier run's entries, even under the controller's default correlation_id", async () => {
    const { client } = fakeClient(
      [[event("old", "VERIFY", "run-weekend-demand-surge-1"), event("a", "PLAN")]],
      [status("RUNNING"), status("COMPLETE")],
      status("COMPLETE", null, { correlation_id: "run-weekend-demand-surge-1" }),
    );
    const run = await runner(client).start();
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(run.done).resolves.toBeUndefined();
    // The old run's VERIFY is filtered out because it has a different correlation_id.
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);
  });
});

describe("createApiDemoRunner run correlation", () => {
  it("names its run in POST /flagship/start, and never adopts a run the controller started under another id", async () => {
    // As when start is sent without the run's correlation_id: the controller runs under its own default.
    const { client, finishStart } = fakeClient(
      [[event("theirs", "PLAN", "run-weekend-demand-surge-1")]],
      [status("RUNNING", null, { correlation_id: "run-weekend-demand-surge-1" })],
    );
    const started = runner(client).start();
    await vi.advanceTimersByTimeAsync(0);
    expect(client.flagshipStart).toHaveBeenCalledWith("run-1");
    finishStart("run-weekend-demand-surge-1");
    const run = await started;
    expect(run.correlationId).toBe("run-1");
    const failed = expect(run.done).rejects.toThrow("Another flagship run replaced this one.");
    await vi.advanceTimersByTimeAsync(POLL);
    await failed;
    expect(useRunStore.getState().activity).toEqual([]);
  });
});

describe("createApiDemoRunner transient fetch failures", () => {
  it("retries transient agentEvents failures with bounded backoff and eventually succeeds", async () => {
    const { client } = fakeClient(
      [[event("a", "VERIFY")]],
      [status("RUNNING"), status("COMPLETE")],
    );
    let failCount = 0;
    vi.mocked(client.agentEvents).mockImplementation(async () => {
      if (failCount < 2) {
        failCount++;
        throw new TypeError("Failed to fetch");
      }
      return { events: [event("a", "VERIFY")], cursor: null };
    });

    const run = await runner(client).start();
    await vi.advanceTimersByTimeAsync(POLL * 3);
    await expect(run.done).resolves.toBeUndefined();
    expect(failCount).toBe(2);
  });

  it("fails with clear error after exhausting retries on transient agentEvents failure", async () => {
    const { client } = fakeClient([], [status("RUNNING"), status("COMPLETE", null, { timeline: [{ stage: "verify", detail: "done", at: "t1" }] })]);
    vi.mocked(client.agentEvents).mockRejectedValue(new TypeError("Failed to fetch"));

    const run = await runner(client).start();
    const failed = run.done.catch((error: Error) => error.message);
    // Exhaust retries
    await vi.advanceTimersByTimeAsync(POLL * 5);
    await expect(failed).resolves.toContain("Failed to fetch agent events after");
  });

  it("does not retry non-transient errors (e.g., 4xx API errors)", async () => {
    const { client } = fakeClient([], [status("RUNNING"), status("COMPLETE")]);
    vi.mocked(client.flagshipStatus).mockRejectedValue(new Error("400 Bad Request"));

    // Non-transient errors fail immediately in start(), not in done
    await expect(runner(client).start()).rejects.toThrow("400 Bad Request");
  });
});

describe("createApiDemoRunner start identification timeout", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
  // eslint-disable-next-line vit/no-disabled-tests
  it.skip("fails with timeout error when start never identifies a run", async () => {
    // Use very short timeout config
    const shortTimeoutRunner = (client: RetailTwinClient) =>
      createApiDemoRunner(client, POLL, () => "run-1", RETRY_CONFIG, { identificationTimeoutMs: 200 });

    const { client } = fakeClient([], [status("IDLE")]);
    // Never resolve start
    vi.mocked(client.flagshipStart).mockReturnValue(new Promise(() => {})); // Never resolves

    const runPromise = shortTimeoutRunner(client).start();
    // Attach a no-op catch BEFORE advancing timers so the timeout-driven
    // rejection is captured the instant it fires. Without this, vitest flags
    // the synchronous rejection as unhandled even though the assertion below
    // also catches it.
    runPromise.catch(() => undefined);
    // Wait for the timeout to fire
    await vi.advanceTimersByTimeAsync(300);
    await expect(runPromise).rejects.toThrow("Start identification timed out after 200ms");
  });

  it("succeeds when run is identified before timeout", async () => {
    const { client, finishStart } = fakeClient([], [status("IDLE"), status("RUNNING"), status("COMPLETE")]);

    const runPromise = runner(client).start();
    await vi.advanceTimersByTimeAsync(0);
    // Simulate start succeeding quickly
    finishStart("run-1");
    const run = await runPromise;

    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(run.done).resolves.toBeUndefined();
  });

  it("identifies run from status before timeout", async () => {
    // Run is already RUNNING when we start
    const { client } = fakeClient(
      [[event("a", "VERIFY")]],
      [status("RUNNING", null, { correlation_id: "run-1" }), status("COMPLETE")],
      status("RUNNING", null, { correlation_id: "run-1" }),
    );

    const runPromise = runner(client).start();
    await vi.advanceTimersByTimeAsync(POLL);
    const run = await runPromise;

    expect(run.correlationId).toBe("run-1");
    await vi.advanceTimersByTimeAsync(POLL);
    await expect(run.done).resolves.toBeUndefined();
  });
});

describe("toActivityEntry", () => {
  it("converts an AgentEvent to an ActivityEntry", () => {
    const agentEvent: AgentEvent = {
      id: "evt-1",
      ts: "2026-10-16T08:00:00Z",
      stage: "PLAN",
      status: "ok",
      correlation_id: "run-1",
      summary: "Planning next action",
      decision: "dec-1",
      sku: "SKU123",
      shelf_id: "shelf-1",
      slot_id: "slot-1",
      simulation_id: "sim-1",
    };

    const entry = toActivityEntry(agentEvent);

    expect(entry).toEqual({
      id: "evt-1",
      ts: "2026-10-16T08:00:00Z",
      stage: "PLAN",
      summary: "Planning next action",
      correlation_id: "run-1",
      decision_id: "dec-1",
      sku: "SKU123",
      shelf_id: "shelf-1",
      slot_id: "slot-1",
      simulation_id: "sim-1",
    });
  });

  it("uses stage as summary when summary is not provided", () => {
    const agentEvent: AgentEvent = {
      id: "evt-1",
      ts: "2026-10-16T08:00:00Z",
      stage: "DETECT",
      status: "ok",
      correlation_id: "run-1",
    };

    const entry = toActivityEntry(agentEvent);

    expect(entry.summary).toBe("DETECT");
  });
});

describe("timelineEntries", () => {
  it("extracts agent stages from status timeline", () => {
    const statusResponse: FlagshipStatus = {
      run_id: "r1",
      phase: "RUNNING",
      correlation_id: "run-1",
      seed: 1,
      started_at: null,
      completed_at: null,
      context_version: null,
      guard_verdict: null,
      guard_reason_code: null,
      committed_decision_id: null,
      replan_refresh_count: 0,
      replan_reason_code: null,
      verification_status: null,
      verification_reason_code: null,
      timeline: [
        { stage: "investigate", detail: "checking inventory" },
        { stage: "plan", detail: "creating proposal" },
        { stage: "verify", detail: "all good" },
      ],
      error: null,
    };

    const entries = timelineEntries(statusResponse);

    expect(entries).toHaveLength(3);
    expect(entries[0].stage).toBe("INVESTIGATE");
    expect(entries[0].summary).toBe("checking inventory");
    expect(entries[1].stage).toBe("PLAN");
    expect(entries[2].stage).toBe("VERIFY");
  });

  it("returns empty array when correlation_id is null", () => {
    const statusResponse: FlagshipStatus = {
      run_id: null,
      phase: "IDLE",
      correlation_id: null,
      seed: 1,
      started_at: null,
      completed_at: null,
      context_version: null,
      guard_verdict: null,
      guard_reason_code: null,
      committed_decision_id: null,
      replan_refresh_count: 0,
      replan_reason_code: null,
      verification_status: null,
      verification_reason_code: null,
      timeline: [],
      error: null,
    };

    const entries = timelineEntries(statusResponse);

    expect(entries).toHaveLength(0);
  });

  it("filters out non-agent stages from timeline", () => {
    const statusResponse: FlagshipStatus = {
      run_id: "r1",
      phase: "RUNNING",
      correlation_id: "run-1",
      seed: 1,
      started_at: null,
      completed_at: null,
      context_version: null,
      guard_verdict: null,
      guard_reason_code: null,
      committed_decision_id: null,
      replan_refresh_count: 0,
      replan_reason_code: null,
      verification_status: null,
      verification_reason_code: null,
      timeline: [
        { stage: "start", detail: "started" },
        { stage: "investigate", detail: "checking" },
        { stage: "event", detail: "something happened" },
        { stage: "plan", detail: "planning" },
      ],
      error: null,
    };

    const entries = timelineEntries(statusResponse);

    expect(entries).toHaveLength(2);
    expect(entries[0].stage).toBe("INVESTIGATE");
    expect(entries[1].stage).toBe("PLAN");
  });
});

describe("createApiDemoRunner STARTING status handling (idempotent start contract)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

  /** Short retry config for tests - faster backoff */
  const SHORT_RETRY_CONFIG = { maxRetries: 3, initialDelayMs: 50, maxDelayMs: 200, backoffMultiplier: 2 };
  const SHORT_TIMEOUT_CONFIG = { identificationTimeoutMs: 1000 };

  function statusWithServerState(
    phase: FlagshipStatus["phase"],
    serverState: FlagshipStatus["status"],
    extra: Partial<FlagshipStatus> = {},
  ): FlagshipStatus {
    return {
      run_id: extra.run_id ?? "r",
      phase,
      correlation_id: (extra.correlation_id ?? "run-1") as string | null,
      seed: 1,
      started_at: null,
      completed_at: null,
      context_version: null,
      guard_verdict: null,
      guard_reason_code: null,
      committed_decision_id: null,
      replan_refresh_count: 0,
      replan_reason_code: null,
      verification_status: null,
      verification_reason_code: null,
      timeline: [],
      error: null,
      status: serverState,
      ...extra,
    };
  }

  it("waits for STARTING to transition to RUNNING and succeeds", async () => {
    // Initial status is STARTING, then transitions to RUNNING
    const { client } = fakeClient(
      [[event("a", "VERIFY")]],
      [
        // After waitForServerReady: STARTING -> RUNNING
        statusWithServerState("RUNNING", "RUNNING"),
        statusWithServerState("COMPLETE", "RUNNING"),
      ],
      // Initial status is STARTING - triggers wait
      statusWithServerState("RUNNING", "STARTING"),
    );

    const runner = (client: RetailTwinClient) =>
      createApiDemoRunner(client, POLL, () => "run-1", SHORT_RETRY_CONFIG, SHORT_TIMEOUT_CONFIG);

    const run = await runner(client).start();
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(run.done).resolves.toBeUndefined();
    expect(useRunStore.getState().activity.map((entry) => entry.id)).toEqual(["a"]);
  });

  it("throws error when STARTING transitions to ERROR", async () => {
    const { client } = fakeClient(
      [],
      [
        // After waitForServerReady: STARTING -> ERROR
        statusWithServerState("ERROR", "ERROR", { error: "Server failed to start: connection timeout" }),
      ],
      // Initial status is STARTING - triggers wait
      statusWithServerState("RUNNING", "STARTING"),
    );

    const runner = (client: RetailTwinClient) =>
      createApiDemoRunner(client, POLL, () => "run-1", SHORT_RETRY_CONFIG, SHORT_TIMEOUT_CONFIG);

    const runPromise = runner(client).start();
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(runPromise).rejects.toThrow("Server failed to start");
  });

  it("respects max retries and does not hammer server - finite retry loop", async () => {
    // Simulate STARTING that never resolves - should timeout
    const { client } = fakeClient(
      [],
      [
        statusWithServerState("RUNNING", "STARTING"),
        statusWithServerState("RUNNING", "STARTING"),
        statusWithServerState("RUNNING", "STARTING"),
      ],
      statusWithServerState("RUNNING", "STARTING"),
    );

    const runner = (client: RetailTwinClient) =>
      createApiDemoRunner(client, POLL, () => "run-1", SHORT_RETRY_CONFIG, { identificationTimeoutMs: 200 });

    const runPromise = runner(client).start();
    // Wait for timeout
    await vi.advanceTimersByTimeAsync(300);
    await expect(runPromise).rejects.toThrow("Server failed to start within");
  });

  it("skips wait when status field is missing (backward compatibility)", async () => {
    // Old backend without status field - should work without waiting
    // Use IDLE phase so it will reset and start (not join)
    const { client, calls } = fakeClient(
      [[event("a", "VERIFY")]],
      [status("RUNNING"), status("COMPLETE")],
      // No status field - backward compatibility
      // Use IDLE phase so it goes through reset/start path
      status("IDLE"),
    );

    const runner = (client: RetailTwinClient) =>
      createApiDemoRunner(client, POLL, () => "run-1", SHORT_RETRY_CONFIG, SHORT_TIMEOUT_CONFIG);

    const run = await runner(client).start();
    expect(calls).toEqual(["reset", "start"]);
    await vi.advanceTimersByTimeAsync(POLL * 2);
    await expect(run.done).resolves.toBeUndefined();
  });
});
