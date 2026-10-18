// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { FlagshipStatusSection } from "@/components/layout/FlagshipStatusSection";
import { useFlagshipStore } from "@/state/flagship.store";
import type { FlagshipStatusResponse } from "@/types/api.type";

const running: FlagshipStatusResponse = {
  run_id: "run-42",
  phase: "RUNNING",
  correlation_id: "flagship-abc",
  context_version: "store-001:v12",
  guard_verdict: "ALLOW",
  guard_reason_code: "APPROVED",
  timeline: [{ stage: "plan", detail: "3 actions", at: "2026-10-18T10:00:00Z" }],
};

afterEach(() => {
  cleanup();
  useFlagshipStore.getState().clear();
});

describe("FlagshipStatusSection", () => {
  it("shows nothing before the first read, or once the controller is IDLE with no run", () => {
    const { container } = render(<FlagshipStatusSection />);
    expect(container.innerHTML).toBe("");
    act(() => useFlagshipStore.getState().setStatus({ run_id: null, phase: "IDLE", correlation_id: null }, null));
    expect(container.innerHTML).toBe("");
  });

  it("shows the served run, its correlation id and the guard's verdict, as served", () => {
    act(() => useFlagshipStore.getState().setStatus(running, null));
    render(<FlagshipStatusSection />);
    const section = screen.getByTestId("flagship-status");
    expect(section.textContent).toContain("run-42");
    expect(section.textContent).toContain("flagship-abc");
    expect(section.textContent).toContain("store-001:v12");
    expect(screen.getByTestId("flagship-verdict").textContent).toContain("ALLOW");
  });

  it("follows the run the status names: another run replaces the shown ids, never mixes with them", () => {
    act(() => useFlagshipStore.getState().setStatus(running, null));
    render(<FlagshipStatusSection />);
    act(() => useFlagshipStore.getState().setStatus({ ...running, run_id: "run-43", correlation_id: "flagship-def" }, null));
    const section = screen.getByTestId("flagship-status");
    expect(section.textContent).toContain("flagship-def");
    expect(section.textContent).not.toContain("flagship-abc");
  });

  it("says a poll failed, and keeps the last status it read", () => {
    act(() => useFlagshipStore.getState().setStatus(running, null));
    render(<FlagshipStatusSection />);
    act(() => useFlagshipStore.setState({ error: "The API is unreachable." }));
    expect(screen.getByRole("alert").textContent).toContain("The API is unreachable.");
    expect(screen.getByTestId("flagship-status").textContent).toContain("flagship-abc");
  });
});
