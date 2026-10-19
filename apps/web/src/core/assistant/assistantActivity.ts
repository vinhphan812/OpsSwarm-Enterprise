import i18n from "@/i18n";
import { ASSISTANT_SOURCE, TOOL_CAPABILITY } from "@/enums/assistant.enum";
import type { ActivityEntry } from "@/types/agent.type";
import type { AssistantTurn } from "@/types/assistant.type";

/**
 * A Copilot turn as Agent Activity timeline entries, under the turn's `correlation_id`: a
 * read tool call as INVESTIGATE, the plan as PLAN, and a simulation tool call as SIMULATE.
 * Only what the turn served; a turn without tool calls adds nothing. Ids follow the reply,
 * so the same turn shown twice adds its entries once.
 */
export function turnActivity(turn: AssistantTurn): ActivityEntry[] {
  const source = i18n.t(turn.source === ASSISTANT_SOURCE.DemoScript ? "copilot.source.demo" : "copilot.source.gemini");
  const entry = (call: AssistantTurn["tool_calls"][number], index: number): ActivityEntry => ({
    id: `${turn.reply_id}:${index}`,
    ts: turn.created_at,
    stage: call.capability === TOOL_CAPABILITY.Read ? "INVESTIGATE" : "SIMULATE",
    summary: i18n.t(call.ok ? "copilot.activity.tool" : "copilot.activity.toolFailed", {
      source,
      tool: call.tool,
      target: call.sku ? ` ${call.sku}` : "",
      code: call.error_code ?? "",
    }),
    correlation_id: turn.correlation_id,
    sku: call.sku ?? undefined,
    simulation_id: call.capability === TOOL_CAPABILITY.Simulation ? turn.proposal?.simulation_id : undefined,
  });
  const calls = turn.tool_calls.map(entry);
  // In loop order, so the run card's stepper ends on the last stage reached: reads, the plan, then its simulation.
  const entries = calls.filter((item) => item.stage === "INVESTIGATE");
  if (turn.proposal) {
    entries.push({
      id: `${turn.reply_id}:plan`,
      ts: turn.created_at,
      stage: "PLAN",
      summary: i18n.t("copilot.activity.plan", { source, summary: turn.proposal.summary }),
      correlation_id: turn.correlation_id,
      decision_id: turn.proposal.decision_id ?? undefined,
      simulation_id: turn.proposal.simulation_id,
      sku: turn.proposal.actions[0]?.sku,
    });
  }
  entries.push(...calls.filter((item) => item.stage !== "INVESTIGATE"));
  return entries;
}
