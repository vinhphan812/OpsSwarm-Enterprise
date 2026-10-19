import { describe, expect, it } from "vitest";
import { InvalidAssistantReplyError, parseAssistantTurn } from "@/core/assistant/parseAssistantTurn";
import { servedProposal, servedTurn } from "./turn";

const expected = { conversationId: "conv-1", messageId: "msg-1" };

function fieldOf(raw: unknown): string {
  try {
    parseAssistantTurn(raw, expected);
  } catch (error) {
    expect(error).toBeInstanceOf(InvalidAssistantReplyError);
    return (error as InvalidAssistantReplyError).field;
  }
  throw new Error("parsed");
}

describe("parseAssistantTurn", () => {
  it("takes a served answer, and a served plan with its proposal", () => {
    expect(parseAssistantTurn(servedTurn(), expected)).toMatchObject({ status: "answered", source: "vertex_gemini", evidence: [{ sku: "P017" }] });
    const plan = parseAssistantTurn(servedTurn({ status: "proposed", proposal: servedProposal() }), expected);
    expect(plan.proposal).toMatchObject({ simulation_id: "sim-9", actions: [{ type: "replenish_shelf", sku: "P017", quantity: 12 }] });
  });

  it("never shows a reply to another conversation or message as this one's", () => {
    expect(fieldOf(servedTurn({ conversation_id: "conv-2" }))).toBe("conversation_id");
    expect(fieldOf(servedTurn({ message_id: "msg-2" }))).toBe("message_id");
  });

  it("refuses a tool call outside read and simulation: the chat is never offered a commit or a write", () => {
    const call = { tool: "submit_action_for_commit", capability: "commit_request", ok: true, error_code: null, sku: null, duration_ms: null };
    expect(fieldOf(servedTurn({ tool_calls: [call] }))).toBe("tool_calls[0].capability");
  });

  it("refuses a plan without its status, or a status without its plan", () => {
    expect(fieldOf(servedTurn({ proposal: servedProposal() }))).toBe("proposal");
    expect(fieldOf(servedTurn({ status: "proposed" }))).toBe("proposal");
  });

  it.each([
    ["not an object", "text", "reply"],
    ["an unknown source", servedTurn({ source: "openai" }), "source"],
    ["an unknown status", servedTurn({ status: "done" }), "status"],
    ["text that is not text", servedTurn({ text: 42 }), "text"],
    ["evidence from an unknown source", servedTurn({ evidence: [{ ...(servedTurn().evidence as object[])[0], source: "guess" }] }), "evidence[0].source"],
    ["a confidence above 1", servedTurn({ evidence: [{ ...(servedTurn().evidence as object[])[0], confidence: 2 }] }), "evidence[0].confidence"],
    ["a proposal with no action", servedTurn({ status: "proposed", proposal: servedProposal({ actions: [] }) }), "proposal.actions"],
    ["an action of an unknown type", servedTurn({ status: "proposed", proposal: servedProposal({ actions: [{ type: "set_price", sku: "P017" }] }) }), "actions[0]"],
    ["a guard verdict it does not know", servedTurn({ status: "proposed", proposal: servedProposal({ guard: { verdict: "MAYBE" } }) }), "proposal.guard"],
  ])("refuses %s", (_name, raw, field) => {
    expect(fieldOf(raw)).toBe(field);
  });

  it("drops incomplete KPIs instead of guessing them", () => {
    const kpis = [{ name: "stockout_risk", value: 0.1, unit: "share", source: "simulation-kpi-v1" }, { name: "service_level", value: "0.8" }];
    const plan = parseAssistantTurn(servedTurn({ status: "proposed", proposal: servedProposal({ kpis }) }), expected);
    expect(plan.proposal?.kpis.map((kpi) => kpi.name)).toEqual(["stockout_risk"]);
  });
});
