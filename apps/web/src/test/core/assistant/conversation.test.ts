// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantError } from "@/core/assistant/apiAssistant";
import { turnActivity } from "@/core/assistant/assistantActivity";
import { ask, retry } from "@/core/assistant/conversation";
import { demoStoreState } from "@/fixtures/demo/store";
import { useCopilotStore } from "@/state/copilot.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import type { Assistant, AssistantMessageRequest } from "@/types/assistant.type";
import { asTurn, servedProposal, servedTurn } from "./turn";

const live = demoStoreState();

/** An assistant that answers each message with `answer`, as served for that message. */
function assistant(answer: (request: AssistantMessageRequest, correlationId: string) => Promise<unknown>): Assistant {
  return {
    mode: "live",
    send: vi.fn(async (conversationId: string, request: AssistantMessageRequest, correlationId: string) => {
      const served = await answer(request, correlationId);
      return asTurn({ ...(served as object), conversation_id: conversationId, message_id: request.message_id, correlation_id: correlationId });
    }),
  };
}

const unavailable = (code: string, status: number, retryable: boolean) =>
  new AssistantError({ code, status, message: code, correlation_id: "copilot-x", retryable });

beforeEach(() => {
  useCopilotStore.setState({ ...useCopilotStore.getInitialState(), messages: [], pending: null }, true);
  useTwinStore.setState({ ...useTwinStore.getInitialState(), live }, true);
  useRunStore.getState().reset();
});

afterEach(() => vi.restoreAllMocks());

describe("ask", () => {
  it("sends the text with the Live state on screen, shows the reply, and records its tool calls in the timeline", async () => {
    const copilot = assistant(async () => servedTurn());
    await ask(copilot, "  What is happening with P017?  ");
    const [conversationId, request, correlationId] = vi.mocked(copilot.send).mock.calls[0];
    expect(conversationId).toBe(useCopilotStore.getState().conversationId);
    expect(request).toMatchObject({ text: "What is happening with P017?", store_id: live.store_id, context_version: live.context_version, mode: "live" });
    expect(correlationId).toMatch(/^copilot-/);
    expect(useCopilotStore.getState().messages.map((message) => message.kind)).toEqual(["user", "reply"]);
    expect(useCopilotStore.getState().pending).toBeNull();
    expect(useRunStore.getState().activity).toMatchObject([{ stage: "INVESTIGATE", sku: "P017", correlation_id: correlationId }]);
  });

  it("sends nothing blank, and nothing while a message is waiting", async () => {
    let finish!: (value: unknown) => void;
    const copilot = assistant(() => new Promise((resolve) => (finish = resolve)));
    await ask(copilot, "   ");
    const first = ask(copilot, "What is happening with P017?");
    await ask(copilot, "And P018?");
    expect(copilot.send).toHaveBeenCalledTimes(1);
    finish(servedTurn());
    await first;
  });

  it("says why there is no reply, and Retry resends the same message, which apps/api answers once", async () => {
    let fail = true;
    const copilot = assistant(async () => {
      if (fail) throw unavailable("model_unavailable", 503, true);
      return servedTurn();
    });
    await ask(copilot, "What is happening with P017?");
    const failed = useCopilotStore.getState().messages.at(-1)!;
    expect(failed).toMatchObject({ kind: "error", failure: { code: "model_unavailable", status: 503 } });

    fail = false;
    await retry(copilot, failed.kind === "error" ? failed.messageId : "");
    const [first, second] = vi.mocked(copilot.send).mock.calls;
    expect(second[1]).toBe(first[1]);
    expect(second[2]).toBe(first[2]);
    expect(useCopilotStore.getState().messages.map((message) => message.kind)).toEqual(["user", "reply"]);
  });

  it("asks again, as a new message on the current Live, after a stale context", async () => {
    const copilot = assistant(async () => {
      throw unavailable("stale_context", 409, false);
    });
    await ask(copilot, "Suggest a plan for P017");
    useTwinStore.setState({ live: { ...live, context_version: "store-001:v9" } });
    const failed = useCopilotStore.getState().messages.at(-1)!;
    await retry(copilot, failed.kind === "error" ? failed.messageId : "");
    const [first, second] = vi.mocked(copilot.send).mock.calls;
    expect(second[1].message_id).not.toBe(first[1].message_id);
    expect(second[1]).toMatchObject({ text: "Suggest a plan for P017", context_version: "store-001:v9" });
  });

  it("shows a reply once, even when the same turn comes back twice", async () => {
    const copilot = assistant(async () => servedTurn({ reply_id: "reply-same" }));
    await ask(copilot, "What is happening with P017?");
    useCopilotStore.getState().addReply(asTurn({ ...servedTurn({ reply_id: "reply-same" }) }));
    expect(useCopilotStore.getState().messages.filter((message) => message.kind === "reply")).toHaveLength(1);
  });

  it("says there is no Copilot on a twin that has none", async () => {
    await ask(null, "What is happening with P017?");
    expect(useCopilotStore.getState().messages.at(-1)).toMatchObject({ kind: "error", failure: { code: "no_assistant", retryable: false } });
  });
});

describe("turnActivity", () => {
  it("lays a plan's turn out in loop order, under its correlation id: reads, the plan, then its simulation", () => {
    const turn = asTurn(
      servedTurn({
        status: "proposed",
        proposal: servedProposal(),
        tool_calls: [
          { tool: "get_inventory", capability: "read", ok: true, error_code: null, sku: "P017", duration_ms: null },
          { tool: "replenish_shelf", capability: "simulation", ok: true, error_code: null, sku: "P017", duration_ms: null },
          { tool: "get_backroom_inventory", capability: "read", ok: false, error_code: "timeout", sku: "P017", duration_ms: null },
        ],
      }),
    );
    const entries = turnActivity(turn);
    expect(entries.map((entry) => entry.stage)).toEqual(["INVESTIGATE", "INVESTIGATE", "PLAN", "SIMULATE"]);
    expect(new Set(entries.map((entry) => entry.correlation_id))).toEqual(new Set(["copilot-1"]));
    expect(entries.map((entry) => entry.id)).toEqual(["reply-1:0", "reply-1:2", "reply-1:plan", "reply-1:1"]);
    expect(entries[1].summary).toBe("Copilot (Gemini on Vertex AI) get_backroom_inventory P017 failed: timeout");
    expect(entries[2]).toMatchObject({ summary: "Copilot (Gemini on Vertex AI) proposed: Restock P017 +12", simulation_id: "sim-9", decision_id: "dec-1" });
  });

  it("adds nothing for a turn without tool calls", () => {
    expect(turnActivity(asTurn(servedTurn({ tool_calls: [], evidence: [] })))).toEqual([]);
  });
});
