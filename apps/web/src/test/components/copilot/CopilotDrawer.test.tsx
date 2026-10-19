// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MotionGlobalConfig } from "framer-motion";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CopilotButton, CopilotDrawer } from "@/components/copilot/CopilotDrawer";
import { AssistantError } from "@/core/assistant/apiAssistant";
import { createDemoAssistant } from "@/core/assistant/demoAssistant";
import { VIEW_MODE } from "@/enums/ui.enum";
import { demoAnomalies } from "@/fixtures/demo/anomalies";
import { demoCandidates } from "@/fixtures/demo/candidates";
import { demoSimulation } from "@/fixtures/demo/simulation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useAnomalyStore } from "@/state/anomaly.store";
import { useCopilotStore } from "@/state/copilot.store";
import { useGuardStore } from "@/state/guard.store";
import { useRunStore } from "@/state/run.store";
import { selectedCandidate, useTwinStore } from "@/state/twin.store";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import type { Assistant, AssistantMessageRequest, AssistantTurn } from "@/types/assistant.type";

MotionGlobalConfig.skipAnimations = true;

const live = demoStoreState();

/** Lets the assistant answer and React render it. */
const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

function renderCopilot(assistant: Assistant | null) {
  return render(
    <>
      <CopilotButton />
      <CopilotDrawer assistant={assistant} />
    </>,
  );
}

const input = () => screen.getByRole("textbox", { name: "Message the Copilot" });

beforeEach(() => {
  vi.useFakeTimers();
  useCopilotStore.setState({ ...useCopilotStore.getInitialState(), open: false, messages: [], pending: null }, true);
  useTwinStore.setState({ ...useTwinStore.getInitialState(), live }, true);
  useTwinStore.getState().setSimulation(demoSimulation(live));
  useTwinStore.getState().setCandidates(demoCandidates(live));
  useAnomalyStore.getState().setAll(demoAnomalies(live));
  useRunStore.getState().reset();
  useGuardStore.getState().clear();
  useUiStore.getState().setViewMode(VIEW_MODE.Live);
  useUiStore.getState().select(null);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("CopilotDrawer", () => {
  it("opens from the header, focuses the message box, and closes with Escape", async () => {
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    const button = screen.getByRole("button", { name: "Copilot" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const drawer = screen.getByTestId("copilot");
    expect(document.activeElement).toBe(input());
    fireEvent.keyDown(drawer, { key: "Escape" });
    expect(useCopilotStore.getState().open).toBe(false);
  });

  it("labels the demo's replies as a script, never as Gemini, and offers its sample prompts", () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    expect(screen.getByText("Demo script")).toBeTruthy();
    expect(screen.queryByText(/Gemini/)).toBeNull();
    const buttons = within(screen.getByRole("group", { name: "Try asking" })).getAllByRole("button");
    // Each prompt is the button's name, with what it shows as its description.
    expect(buttons[1].getAttribute("aria-describedby")).toBeTruthy();
    expect(document.getElementById(buttons[2].getAttribute("aria-describedby")!)!.textContent).toBe("The chat can't commit: see the guardrail");
    const samples = buttons.map((button) => button.getAttribute("aria-label"));
    expect(samples).toEqual([
      "What is happening with P003?",
      "Suggest a safer restock for P003 this weekend",
      "Approve the plan",
      "What is happening with P017?",
    ]);
  });

  it("sends on Enter, keeps a new line on Shift+Enter, and shows the reply with its products, evidence and tools", async () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    fireEvent.change(input(), { target: { value: "What is happening with P003?" } });
    fireEvent.keyDown(input(), { key: "Enter", shiftKey: true });
    expect(useCopilotStore.getState().messages).toHaveLength(0);
    fireEvent.keyDown(input(), { key: "Enter" });
    expect((input() as HTMLTextAreaElement).value).toBe("");
    await settle();

    const reply = screen.getByText(/has 0 on the shelf and 18 in the backroom/).closest("li")!;
    expect(within(reply).getByText("Evidence (3)")).toBeTruthy();
    expect(within(reply).getByText("Tools used (2)")).toBeTruthy();
    fireEvent.click(within(within(reply).getByRole("group", { name: "Show in store" })).getByRole("button", { name: "Show P003 in the store" }));
    expect(selectedProductId(useUiStore.getState())).toBe("P003");
  });

  it("refuses an approval in chat and points to the Simulation banner", async () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    fireEvent.click(screen.getByRole("button", { name: "Approve the plan" }));
    await settle();
    const outcome = screen.getByText("Refused").closest("p")!;
    expect(outcome.textContent).toBe("RefusedApprove in Simulation, not in chat");
    expect(screen.getByText(/Open the plan in Simulation and press Accept there/)).toBeTruthy();
  });

  it("shows a plan with its KPIs and checks, and opens it in the Simulation view on its candidate; it has no Accept of its own", async () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    fireEvent.click(screen.getByRole("button", { name: "Suggest a safer restock for P003 this weekend" }));
    await settle();

    const plan = screen.getByRole("region", { name: "Proposed plan" });
    expect(plan.textContent).toContain("sim-demo-001 · from Live store-001:v1");
    expect(within(plan).getByRole("table", { name: "KPIs against the current store" }).textContent).toContain("Stockout risk0.40→0.15-0.25");
    expect(plan.textContent).toContain("Guard: runs when you press Accept");
    expect(within(plan).queryByRole("button", { name: /Accept|Approve/ })).toBeNull();

    fireEvent.click(within(plan).getByRole("button", { name: "Review in Simulation" }));
    expect(useUiStore.getState().viewMode).toBe(VIEW_MODE.Simulation);
    expect(selectedCandidate(useTwinStore.getState())?.candidate_id).toBe("cand-b");
    expect(selectedProductId(useUiStore.getState())).toBe("P003");
  });

  it("says a plan's run has closed once it has", async () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(createDemoAssistant(() => "sim-memory-001", 0));
    fireEvent.click(screen.getByRole("button", { name: "Suggest a safer restock for P003 this weekend" }));
    await settle();
    act(() => useTwinStore.getState().setSimulation(null));
    const plan = screen.getByRole("region", { name: "Proposed plan" });
    expect(plan.textContent).toContain("This plan is no longer open.");
    expect(within(plan).queryByRole("button", { name: "Review in Simulation" })).toBeNull();
  });

  it("shows why a Live message got no reply, with its HTTP status, code and correlation id, and retries it", async () => {
    let fail = true;
    const send = vi.fn(async (_conversationId: string, _request: AssistantMessageRequest, _correlationId: string): Promise<AssistantTurn> => {
      if (fail) {
        throw new AssistantError({
          code: "assistant_not_deployed",
          status: 404,
          message: "Not Found",
          correlation_id: "copilot-abc",
          retryable: true,
        });
      }
      throw new AssistantError({ code: "model_unavailable", status: 503, message: "Vertex AI did not answer.", correlation_id: "copilot-abc", retryable: false });
    });
    useCopilotStore.getState().setOpen(true);
    renderCopilot({ mode: "live", send });
    expect(screen.getByText("Live · apps/api")).toBeTruthy();
    fireEvent.change(input(), { target: { value: "What is happening with P017?" } });
    fireEvent.keyDown(input(), { key: "Enter" });
    await settle();

    const failure = screen.getByRole("alert");
    expect(failure.textContent).toContain("This apps/api has no Copilot route yet, so nothing was answered.");
    expect(failure.textContent).toContain("HTTP 404 · assistant_not_deployed");
    expect(failure.textContent).toContain("Correlation copilot-abc");

    fail = false;
    fireEvent.click(within(failure).getByRole("button", { name: "Retry" }));
    await settle();
    expect(screen.getByRole("alert").textContent).toContain("Gemini on Vertex AI did not answer. No reply was made up.");
    expect(send.mock.calls[1][1]).toBe(send.mock.calls[0][1]);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("says when the twin has no Copilot", () => {
    useCopilotStore.getState().setOpen(true);
    renderCopilot(null);
    expect(screen.getByText("This dev twin has no Copilot. Open the demo or the Live twin.")).toBeTruthy();
  });
});
