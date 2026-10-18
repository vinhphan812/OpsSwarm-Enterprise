import { DEMO_RUN_POLL_MS } from "@/constants/app.constant";
import { useRunStore } from "@/state/run.store";
import type { ActivityEntry, ControlStage } from "@/types/agent.type";
import type { AgentEvent, FlagshipStatus, RetailTwinClient } from "@/types/api.type";

/**
 * What a Run AI Demo button plays: a `replay` of fixtures/demo on the memory twin, which
 * never calls apps/api, or the real `flagship` run of apps/api. The UI says which.
 */
export const DEMO_RUN_SOURCE = {
  Replay: "replay",
  Flagship: "flagship",
} as const;
export type DemoRunSource = (typeof DEMO_RUN_SOURCE)[keyof typeof DEMO_RUN_SOURCE];

/**
 * One flagship run as it plays: its `correlation_id`, a promise that settles when it ends
 * (rejected, with the reason, when it fails), and `stop` to stop reading it.
 */
export type DemoRun = { correlationId: string; done: Promise<void>; stop: () => void };

/** What the Run AI Demo button runs: resets the store and starts the flagship scenario. */
export type DemoRunner = { source: DemoRunSource; start: () => Promise<DemoRun> };

/** An `AgentEvent` of `GET /agent/events` as a timeline entry; only what the feed served. */
export function toActivityEntry(event: AgentEvent): ActivityEntry {
  return {
    id: event.id,
    ts: event.ts,
    stage: event.stage as ControlStage,
    summary: event.summary ?? event.stage,
    correlation_id: event.correlation_id,
    decision_id: event.decision ?? undefined,
    sku: event.sku ?? undefined,
    shelf_id: event.shelf_id ?? undefined,
    slot_id: event.slot_id ?? undefined,
    simulation_id: event.simulation_id ?? undefined,
  };
}

/** The controller's timeline steps that are agent stages, by name; its other steps (start, event, replan, error) are not. */
const TIMELINE_STAGE: Record<string, ControlStage> = {
  investigate: "INVESTIGATE",
  plan: "PLAN",
  simulate: "SIMULATE",
  guard: "GUARD",
  verify: "VERIFY",
};

/**
 * The agent stages of the run `status` describes, from its `timeline`, as timeline entries:
 * the step's own detail, under the run's `correlation_id`. Nothing is added: a step that is
 * not an agent stage is left out, and an ACT the controller does not record stays absent.
 */
export function timelineEntries(status: FlagshipStatus): ActivityEntry[] {
  if (!status.correlation_id) return [];
  const correlationId = status.correlation_id;
  return (status.timeline ?? []).flatMap((step, index): ActivityEntry[] => {
    const stage = TIMELINE_STAGE[step.stage];
    if (!stage) return [];
    // Use index-based ID since timeline entries may not have 'at' timestamp
    return [{ id: `${status.run_id ?? 'unknown'}:${index}`, ts: new Date().toISOString(), stage, summary: step.detail ?? "", correlation_id: correlationId }];
  });
}

/** A fresh `correlation_id` for one flagship run, so its entries never mix with an earlier run's. */
const newCorrelationId = () => `flagship-${crypto.randomUUID()}`;

/**
 * Retry configuration aligned with backend's idempotent start contract.
 * Backend uses exponential backoff: 1s, 2s, 4s - max 3 attempts.
 */
interface RetryConfig {
  /** Maximum number of retry attempts. */
  maxRetries: number;
  /** Initial delay in ms between retries (matches backend's 1s). */
  initialDelayMs: number;
  /** Maximum delay in ms between retries (matches backend's 4s). */
  maxDelayMs: number;
  /** Multiplier for exponential backoff (matches backend: 2x). */
  backoffMultiplier: number;
}

/** Default retry configuration aligned with backend contract. */
const DEFAULT_RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  initialDelayMs: 1000, // Backend's first backoff is 1s
  maxDelayMs: 4000, // Backend's max backoff is 4s
  backoffMultiplier: 2, // Backend uses 1s, 2s, 4s progression
};

/** Timeout configuration for start identification. */
interface TimeoutConfig {
  /** Maximum time to wait for run identification in ms. */
  identificationTimeoutMs: number;
}

/** Default timeout configuration. */
const DEFAULT_TIMEOUT_CONFIG: TimeoutConfig = {
  identificationTimeoutMs: 30000, // 30 seconds
};

/**
 * Calculate the delay for the next retry with exponential backoff.
 */
function calculateRetryDelay(attempt: number, config: RetryConfig): number {
  const delay = config.initialDelayMs * Math.pow(config.backoffMultiplier, attempt);
  return Math.min(delay, config.maxDelayMs);
}

/**
 * Check if an error is transient and should be retried.
 * Network errors, timeouts, and 5xx errors are considered transient.
 */
function isTransientError(error: unknown): boolean {
  if (error instanceof TypeError) {
    // Network errors (failed to fetch, etc.)
    return true;
  }
  if (error instanceof Error) {
    // AbortError (timeout) is transient
    if (error.name === "AbortError") return true;
    // Timeout errors are transient
    if (error.message.includes("timeout") || error.message.includes("timed out")) return true;
  }
  return false;
}

/**
 * The flagship demo on apps/api (#41). It first reads `GET /flagship/status`: a run already
 * RUNNING (another tab, a second press) is followed, never reset or started again, since a
 * reset would clear it. Otherwise `POST /flagship/reset`, then `POST /flagship/start` under a
 * fresh `correlation_id`. `start` answers only once the whole chain has run, so it is sent and
 * not awaited: every `pollMs` the runner reads the status and this run's stages into the
 * timeline, from `GET /agent/events` when it serves any for the run, else from the status's
 * `timeline` (#202 records its stages there, not in the feed). `start()` resolves as soon as
 * the status or `start`'s answer names the run; the run ends when the status says COMPLETE or
 * ERROR, or when the status names another run. A failed `start` (a timeout on Cloud Run, say)
 * ends it only once the status does not name the run: while the controller carries on, the
 * runner follows it and never sends `start` again.
 *
 * Bounded retry with exponential backoff is applied to transient failures during status and
 * agentEvents polling. After exhausting retries, a clear final error is surfaced.
 *
 * A timeout is applied to the start identification: if POST/start never results in a run being
 * identified within the configured timeout, the runner fails with a clear error.
 *
 * The frontend now consumes the backend's idempotent start contract:
 * - Checks `status` field (NOT_STARTED, STARTING, RUNNING, ERROR) for server state
 * - On STARTING, polls until RUNNING or ERROR with timeout
 * - Retry timing aligned with backend's exponential backoff (1s, 2s, 4s)
 *
 * It never advances a stage itself: the stages are the controller's.
 * TODO(BE): #41 to answer `start` at once (202) and to record each stage, ACT included, in the feed.
 */

/**
 * Wait for the server to transition from STARTING to RUNNING or ERROR.
 * Uses the backend's retry info for timing if available.
 */
async function waitForServerReady(
  client: RetailTwinClient,
  retryConfig: RetryConfig,
  timeoutMs: number,
): Promise<FlagshipStatus> {
  const startTime = Date.now();

  while (Date.now() - startTime < timeoutMs) {
    const status = await client.flagshipStatus();

    // Check server state from idempotent start contract
    // Handle backward compatibility: if status field is missing, assume not STARTING
    const serverStatus = status.status;
    if (serverStatus === "RUNNING") {
      return status;
    }
    if (serverStatus === "ERROR") {
      return status;
    }
    // If status is undefined or NOT_STARTED, exit the wait loop
    if (!serverStatus || serverStatus === "NOT_STARTED") {
      return status;
    }

    // If status is STARTING, use backend's retry info if available
    // Otherwise use our own backoff timing aligned with backend (1s, 2s, 4s)
    let delayMs: number;
    if (status.retry_info?.next_retry_at) {
      // Use backend's suggested next retry time
      const serverDelay = status.retry_info.next_retry_at * 1000 - Date.now();
      delayMs = Math.max(100, serverDelay);
    } else {
      // Fall back to our own exponential backoff aligned with backend
      const attempt = status.retry_info?.attempt ?? 1;
      delayMs = Math.min(
        retryConfig.initialDelayMs * Math.pow(retryConfig.backoffMultiplier, attempt - 1),
        retryConfig.maxDelayMs,
      );
    }

    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }

  throw new Error(`Server failed to start within ${timeoutMs}ms`);
}
export function createApiDemoRunner(
  client: RetailTwinClient,
  pollMs = DEMO_RUN_POLL_MS,
  correlationIdOf: () => string = newCorrelationId,
  retryConfig: RetryConfig = DEFAULT_RETRY_CONFIG,
  timeoutConfig: TimeoutConfig = DEFAULT_TIMEOUT_CONFIG,
): DemoRunner {
  return {
    source: DEMO_RUN_SOURCE.Flagship,
    async start() {
      // Initial status fetch - with retry for transient failures
      let initialStatus!: import("@/types/api.type").FlagshipStatus;
      let initialAttempt = 0;
      while (initialAttempt <= retryConfig.maxRetries) {
        try {
          initialStatus = await client.flagshipStatus();
          break;
        } catch (error) {
          initialAttempt++;
          if (initialAttempt > retryConfig.maxRetries || !isTransientError(error)) {
            throw error;
          }
          const delay = calculateRetryDelay(initialAttempt - 1, retryConfig);
          await new Promise((resolve) => setTimeout(resolve, delay));
        }
      }
      if (!initialStatus) throw new Error("Failed to get initial status");

      // Consume backend's idempotent start contract
      // Check server state (status field) for coordinated retry handling
      if (initialStatus.status === "STARTING") {
        // Server is starting with retry - wait for it to complete
        // Use timeout aligned with backend's max retry time (3 attempts * 4s = ~12s max)
        const serverReadyStatus = await waitForServerReady(
          client,
          retryConfig,
          timeoutConfig.identificationTimeoutMs,
        );
        if (serverReadyStatus.status === "ERROR") {
          throw new Error(serverReadyStatus.error ?? "Server failed to start");
        }
        // Use the resolved status
        initialStatus = serverReadyStatus;
      }

      const joined = initialStatus.phase === "RUNNING" && initialStatus.correlation_id ? initialStatus.correlation_id : null;
      if (!joined) await client.flagshipReset();
      const ours = joined ?? correlationIdOf();
      let identifiedYet = false;
      let feedServed = false;
      let stopped = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      /** How `POST /flagship/start` answered, once it has; a joined run sends none. */
      let answer: { ok: true } | { ok: false; error: unknown } | null = joined ? { ok: true } : null;
      /** Track when start identification times out. */
      let identificationTimeout: ReturnType<typeof setTimeout> | undefined;

      let identify!: () => void;
      let failStart!: (error: unknown) => void;
      let failIdentification!: (error: Error) => void;
      const identified = new Promise<void>((resolve, reject) => {
        identify = () => {
          identifiedYet = true;
          clearTimeout(identificationTimeout);
          resolve();
        };
        failStart = reject;
        failIdentification = reject;
      });

      // Set up identification timeout
      identificationTimeout = setTimeout(() => {
        if (!identifiedYet) {
          failIdentification(new Error(
            `Start identification timed out after ${timeoutConfig.identificationTimeoutMs}ms. The run was never identified.`,
          ));
        }
      }, timeoutConfig.identificationTimeoutMs);

      const append = (entries: ActivityEntry[]) => entries.forEach((entry) => useRunStore.getState().append(entry));

      /**
       * Read stages from agentEvents feed with bounded retry for transient failures.
       */
      const readStagesWithRetry = async (status: FlagshipStatus): Promise<void> => {
        let cursor: string | null = null;
        while (true) {
          let attempt = 0;
          let page;
          while (attempt <= retryConfig.maxRetries) {
            try {
              page = await client.agentEvents(cursor);
              break;
            } catch (error) {
              attempt++;
              if (attempt > retryConfig.maxRetries || !isTransientError(error)) {
                const errorMsg = error instanceof Error ? error.message : String(error);
                throw new Error(`Failed to fetch agent events after ${attempt} attempts: ${errorMsg}`);
              }
              const delay = calculateRetryDelay(attempt - 1, retryConfig);
              await new Promise((resolve) => setTimeout(resolve, delay));
            }
          }
          if (!page) break;
          
          const own = page.events.filter((event) => event.correlation_id === ours);
          if (own.length) feedServed = true;
          append(own.map(toActivityEntry));
          
          if (page.cursor === null || page.cursor === cursor) break;
          cursor = page.cursor;
          if (!page.events.length) break;
        }
        if (!feedServed) append(timelineEntries(status));
      };

      /**
       * Poll status with bounded retry for transient failures.
       */
      const pollStatusWithRetry = async (): Promise<FlagshipStatus> => {
        let attempt = 0;
        while (attempt <= retryConfig.maxRetries) {
          try {
            const status = await client.flagshipStatus();
            return status;
          } catch (error) {
            attempt++;
            if (attempt > retryConfig.maxRetries || !isTransientError(error)) {
              throw error;
            }
            const delay = calculateRetryDelay(attempt - 1, retryConfig);
            await new Promise((resolve) => setTimeout(resolve, delay));
          }
        }
        throw new Error("Status polling failed");
      };

      const done = new Promise<void>((resolve, reject) => {
        const fail = (error: unknown) => {
          clearTimeout(identificationTimeout);
          failStart(error);
          reject(error);
        };
        const poll = async () => {
          if (stopped) return;
          try {
            const status = await pollStatusWithRetry();
            // IDLE is the reset, before `start` has reached the controller.
            const isOurs = status.phase !== "IDLE" && status.correlation_id === ours;
            if (isOurs) identify();
            // `start` failed and the controller has no run of ours: it never started, or is gone.
            else if (answer && !answer.ok) return fail(answer.error);
            else if (identifiedYet || answer?.ok) return fail(new Error("Another flagship run replaced this one."));
            if (isOurs) await readStagesWithRetry(status);
            if (stopped) return;
            if (isOurs && status.phase === "COMPLETE") return resolve();
            if (isOurs && status.phase === "ERROR") {
              return fail(new Error(status.error ?? status.timeline?.at(-1)?.detail ?? "The flagship run failed."));
            }
            timer = setTimeout(poll, pollMs);
          } catch (error) {
            // Retry already threw after exhaustion - just propagate
            fail(error);
          }
        };

        if (!joined) {
          client.flagshipStart(ours).then(
            () => {
              answer = { ok: true };
              identify();
            },
            // The next poll decides: a run the status still names goes on.
            (error: unknown) => {
              answer = { ok: false, error };
            },
          );
        }
        void poll();
      });
      // A run that fails before it is identified rejects `start()`; nobody waits on `done` then.
      done.catch(() => {});

      await identified;
      return {
        correlationId: ours,
        done,
        stop: () => {
          stopped = true;
          clearTimeout(timer);
          clearTimeout(identificationTimeout);
        },
      };
    },
  };
}
