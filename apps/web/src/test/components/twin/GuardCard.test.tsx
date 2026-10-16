// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GuardSection } from "@/components/layout/GuardSection";
import { GuardCard } from "@/components/twin/GuardCard";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import type { SimulationReviewer } from "@/core/twin/simulationReview";
import { GUARD_VERDICT, REVIEW_DECISION, SIMULATION_STATUS } from "@/enums/simulation.enum";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useGuardStore, type GuardReview } from "@/state/guard.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import type { GuardResult, ReviewResult } from "@/types/simulation.type";

vi.mock("@/core/notify", () => ({ notify: { info: vi.fn(), warning: vi.fn(), error: vi.fn(), success: vi.fn() } }));

afterEach(() => {
  cleanup();
  useGuardStore.getState().clear();
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
});

const BASE = "store-001:v182";

function review(result: Partial<ReviewResult>, guard: Partial<GuardResult> | null = {}): GuardReview {
  return {
    base_context_version: BASE,
    result: {
      simulation_id: "sim-1",
      decision: REVIEW_DECISION.Approve,
      status: SIMULATION_STATUS.Committed,
      verdict: GUARD_VERDICT.Allow,
      reason_code: "APPROVED",
      live_context_version: "store-001:v183",
      detail_code: null,
      ...result,
      guard: guard && {
        verdict: result.verdict ?? GUARD_VERDICT.Allow,
        reason_code: "ALLOWED",
        context_version: BASE,
        failed_gate: null,
        checks: [],
        ...guard,
      },
    },
  };
}

const card = () => screen.getByRole("region", { name: "Decision Context Guard verdict for sim-1" });
const gates = () => within(card()).queryByRole("list", { name: "Gates" });

describe("GuardCard", () => {
  it("shows an ALLOW with every gate the guard passed and the new Live version", () => {
    const checks = ["integrity", "evidence", "context", "freshness", "feasibility", "policy"].map((gate) => ({
      gate,
      passed: true,
      detail: "",
    }));
    render(<GuardCard review={review({}, { checks })} />);

    expect(card().dataset.verdict).toBe("ALLOW");
    expect(card().textContent).toContain("Allow");
    expect(card().textContent).toContain("Every gate passed.");
    expect(card().textContent).toContain("Committed. Live is now store-001:v183.");
    const rows = within(gates()!).getAllByRole("listitem");
    expect(rows.map((row) => row.dataset.state)).toEqual(Array(6).fill("passed"));
    expect(rows[3].textContent).toContain("Context freshness");
  });

  it("shows REFRESH_REQUIRED with both versions, and the gates it never reached", () => {
    render(
      <GuardCard
        review={review(
          {
            status: SIMULATION_STATUS.Evaluated,
            verdict: GUARD_VERDICT.RefreshRequired,
            reason_code: "VERSION_STALE",
            live_context_version: "store-001:v184",
          },
          {
            reason_code: "VERSION_STALE",
            failed_gate: "freshness",
            checks: [
              { gate: "integrity", passed: true, detail: "" },
              { gate: "evidence", passed: true, detail: "" },
              { gate: "context", passed: true, detail: "" },
              { gate: "freshness", passed: false, detail: "P018 is at v7; the decision used v6." },
            ],
          },
        )}
      />,
    );

    expect(card().textContent).toContain("Refresh required");
    expect(card().textContent).toContain("Live is newer than the context this decision used.");
    expect(card().textContent).toContain(`Live moved: ${BASE} → store-001:v184`);
    expect(card().textContent).toContain("Nothing was committed. Live did not change.");
    const rows = within(gates()!).getAllByRole("listitem");
    expect(rows.map((row) => row.dataset.state)).toEqual(["passed", "passed", "passed", "failed", "notRun", "notRun"]);
    expect(rows[3].textContent).toContain("P018 is at v7; the decision used v6.");
  });

  it("shows DENY and HUMAN_REVIEW with their reasons", () => {
    const { rerender } = render(
      <GuardCard
        review={review({ status: SIMULATION_STATUS.Evaluated, verdict: GUARD_VERDICT.Deny, reason_code: "DCG_DENY" })}
      />,
    );
    expect(card().dataset.verdict).toBe("DENY");
    expect(card().textContent).toContain("The guard denied the decision.");

    rerender(
      <GuardCard
        review={review({
          status: SIMULATION_STATUS.Evaluated,
          verdict: GUARD_VERDICT.HumanReview,
          reason_code: "DCG_HUMAN_REVIEW",
        })}
      />,
    );
    expect(card().dataset.verdict).toBe("HUMAN_REVIEW");
    expect(card().textContent).toContain("Human review");
    expect(card().textContent).toContain("needs a person to approve it");
  });

  it("lists no gates the guard did not send, and shows an unknown reason as served", () => {
    render(
      <GuardCard
        review={review(
          { status: SIMULATION_STATUS.Evaluated, verdict: GUARD_VERDICT.Deny, reason_code: "NEW_CODE" },
          null,
        )}
      />,
    );
    expect(gates()).toBeNull();
    expect(card().textContent).toContain("No gate-by-gate checks were sent.");
    expect(card().textContent).toContain("NEW_CODE");
  });
});

describe("the guard's answer on screen", () => {
  it("shows under the run after Accept, and stays in the Operations lens once the run closes", async () => {
    const live = demoStoreState();
    const simulation = demoSimulation(live);
    useTwinStore.setState({ ...useTwinStore.getInitialState(), live, simulation }, true);
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    const answer = review({ simulation_id: simulation.simulation_id }).result;
    const reviewer = vi.fn<SimulationReviewer>(async () => answer);
    render(
      <>
        <SimulationBanner reviewer={reviewer} />
        <GuardSection />
      </>,
    );
    expect(screen.queryByRole("region", { name: /Decision Context Guard/ })).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Accept/ }));
    });
    expect(screen.getAllByRole("region", { name: `Decision Context Guard verdict for ${simulation.simulation_id}` })).toHaveLength(2);

    act(() => useTwinStore.getState().setSimulation(null));
    expect(screen.getAllByRole("region", { name: /Decision Context Guard/ })).toHaveLength(1);
    expect(screen.getByText("Latest guard decision")).toBeDefined();
  });

  it("keeps nothing for a rejection, which never reaches the guard", async () => {
    const live = demoStoreState();
    const simulation = demoSimulation(live);
    useTwinStore.setState({ ...useTwinStore.getInitialState(), live, simulation }, true);
    useUiStore.getState().setViewMode(VIEW_MODE.Simulation);
    const reviewer = vi.fn<SimulationReviewer>(async () => ({
      ...review({ simulation_id: simulation.simulation_id }, null).result,
      decision: REVIEW_DECISION.Reject,
      status: SIMULATION_STATUS.Rejected,
      verdict: null,
    }));
    render(<SimulationBanner reviewer={reviewer} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    });
    expect(useGuardStore.getState().last).toBeNull();
  });
});
