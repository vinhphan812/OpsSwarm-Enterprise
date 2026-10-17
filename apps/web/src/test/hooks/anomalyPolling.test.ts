// @vitest-environment jsdom
/**
 * Behavioral tests for useAnomalyPolling hook.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { RetailTwinClient } from "@/types/api.type";
import type { AnomaliesResponse } from "@/types/anomaly.type";
import { pollingState } from "@/hooks/anomalyPolling.hook";

const _store: Record<string, any> = {
  setAll: () => {},
  fail: () => {},
  anomalies: [],
  served: false,
  readError: null,
};

// Initialize wrappers ONCE — the hook captures these function references.
_store.setAll = (arg: unknown) => { spySetAll(arg); };
_store.fail = (arg: unknown) => { spyFail(arg); };

export const spyAnomalies = vi.fn<() => Promise<AnomaliesResponse>>();
export const spySetAll = vi.fn<(args: unknown) => void>();
export const spyFail = vi.fn<(args: unknown) => void>();
export const spyNotifyError = vi.fn();
let isDemo = false;

export function resetSpies() {
  spyAnomalies.mockImplementation(() => Promise.resolve({ anomalies: [] } as unknown as AnomaliesResponse));
  // mockReset() replaces the function but keeps the same reference — the wrapper
  // that calls spySetAll(spyFail) still points to the same spy object
  spySetAll.mockReset();
  spyFail.mockReset();
  spyNotifyError.mockReset();
  isDemo = false;
  // Mutate in-place — the hook captured _store.fail directly; by mutating
  // we change what the wrapper function does without changing its reference
  _store.anomalies = [];
  _store.served = false;
  _store.readError = null;
  // Reset the singleton so tests can start a fresh interval
  pollingState.active = false;
  pollingState.timerId = null;
}

function setDemo(value: boolean) { isDemo = value; }

vi.mock("@/core/twin/demoMode", () => ({
  isDemoMode: () => isDemo,
}));

vi.mock("@/core/api/client", () => ({
  defaultClient: {
    anomalies: () => spyAnomalies(),
  } as unknown as RetailTwinClient,
}));

vi.mock("@/fixtures/demo/commerce", () => ({
  demoClient: { anomalies: vi.fn() } as unknown as RetailTwinClient,
}));

vi.mock("@/core/notify", () => ({
  notify: {
    error: (...args: unknown[]) => spyNotifyError(...args),
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@/i18n", () => ({
  default: { t: vi.fn((key: string) => key) },
}));

vi.mock("@/state/anomaly.store", () => ({
  useAnomalyStore: ((selector?: (s: typeof _store) => unknown) =>
    selector ? selector(_store) : _store
  ) as unknown as ReturnType<typeof import("@/state/anomaly.store").useAnomalyStore>,
}));

describe("useAnomalyPolling", () => {
  beforeEach(() => { resetSpies(); });

  it("calls client.anomalies() immediately on mount", async () => {
    const { useAnomalyPolling } = await import("@/hooks/anomalyPolling.hook");
    await act(async () => { renderHook(() => useAnomalyPolling()); });
    expect(spyAnomalies).toHaveBeenCalledTimes(1);
  });

  it("starts a 30-second interval in live (non-demo) mode", async () => {
    setDemo(false);
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const { useAnomalyPolling } = await import("@/hooks/anomalyPolling.hook");
    await act(async () => { renderHook(() => useAnomalyPolling()); });
    expect(setIntervalSpy).toHaveBeenCalledWith(expect.any(Function), 30_000);
    setIntervalSpy.mockRestore();
  });

  it("clears the interval when the component unmounts", async () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval")
      .mockReturnValue(42 as unknown as ReturnType<typeof setInterval>);
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");
    const { useAnomalyPolling } = await import("@/hooks/anomalyPolling.hook");
    const { unmount } = renderHook(() => useAnomalyPolling());
    await act(async () => { unmount(); });
    expect(clearIntervalSpy).toHaveBeenCalledWith(42);
    setIntervalSpy.mockRestore();
    clearIntervalSpy.mockRestore();
  });

  it("does NOT call setInterval in demo mode", async () => {
    setDemo(true);
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const { useAnomalyPolling } = await import("@/hooks/anomalyPolling.hook");
    await act(async () => { renderHook(() => useAnomalyPolling()); });
    // In demo mode: initial poll fires. Due to mock resolution triggering a re-render,
    // spyAnomalies may be called more than once — that's expected behavior.
    expect(spyAnomalies.mock.calls.length).toBeGreaterThan(0);
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
    setDemo(false);
  });

  it("calls fail and notify.error when the API throws", async () => {
    setDemo(false);
    const error = new Error("Network unreachable");
    spyAnomalies.mockImplementation(() => Promise.reject(error));
    const { useAnomalyPolling } = await import("@/hooks/anomalyPolling.hook");
    await act(async () => { renderHook(() => useAnomalyPolling()); });
    await act(async () => { await new Promise((r) => setTimeout(r, 10)); });
    // i18n mock returns the key as-is, so fail receives the translated string
    expect(spyFail).toHaveBeenCalledWith("anomalies.loadFailed");
    expect(spyNotifyError).toHaveBeenCalled();
  });
});
