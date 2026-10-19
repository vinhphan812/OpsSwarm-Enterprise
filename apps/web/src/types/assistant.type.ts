import type {
  AssistantMode,
  AssistantSource,
  AssistantStatus,
  EvidenceSource,
  ToolCapability,
} from "@/enums/assistant.enum";
import type { GuardVerdict } from "@/enums/simulation.enum";
import type { CandidateKPI, SimulationAction } from "./simulation.type";

/**
 * Body of `POST /assistant/conversations/{conversation_id}/messages`, sent with an
 * `X-Correlation-ID` header. TODO(BE #332): FE proposal; apps/api serves no assistant yet.
 */
export type AssistantMessageRequest = {
  /** Made by the web app. A resend with the same id must answer with the same turn, never run it twice. */
  message_id: string;
  /** What the user typed, at most `COPILOT_MAX_MESSAGE` characters. */
  text: string;
  store_id: string;
  /** The Live state on screen when the message was sent; null before the first one loads. */
  context_version: string | null;
  mode: AssistantMode;
};

/** One fact a reply rests on, as a tool or a feed served it. Never model reasoning. */
export type AssistantEvidence = {
  id: string;
  /** An `EVIDENCE_KIND`, or another kind as served. */
  kind: string;
  /** Short heading, such as "Shelf and backroom". */
  label: string;
  /** The fact itself, such as "0 on the shelf, 18 in the backroom". */
  detail: string;
  source: EvidenceSource;
  /** The registry tool that read it; null when it came from a feed (anomalies, say). */
  tool: string | null;
  sku: string | null;
  /** When the fact was true (ISO) or the context version it was read at; null when not served. */
  as_of: string | null;
  /** 0..1 when the source scores it, such as a forecast; null otherwise. Never filled in by the FE. */
  confidence: number | null;
};

/** One allow-listed tool call the assistant made for this turn. */
export type AssistantToolCall = {
  tool: string;
  capability: ToolCapability;
  ok: boolean;
  /** The registry's code when it refused (`not_found`, `timeout`, …); null on success. */
  error_code: string | null;
  sku: string | null;
  duration_ms: number | null;
};

/** One constraint the plan was checked against, and whether it holds. */
export type AssistantConstraint = { label: string; passed: boolean };

/**
 * A plan the assistant opened as a simulation. It is a proposal only: the user approves it in
 * the Simulation view, through `POST /simulations/{id}/approve` and the guard.
 */
export type AssistantProposal = {
  simulation_id: string;
  /** The candidate of that simulation the plan is; null for the simulation's own proposal. */
  candidate_id: string | null;
  decision_id: string | null;
  /** The Live state the plan was built on. */
  base_context_version: string;
  actions: SimulationAction[];
  summary: string;
  /** The plan's KPIs as the evaluator scored them; empty when not scored. */
  kpis: CandidateKPI[];
  /** The baseline's KPIs, the "before" of `kpis`; empty when not served. */
  baseline_kpis: CandidateKPI[];
  evaluator_version: string | null;
  constraints: AssistantConstraint[];
  /** A guard pre-check when apps/api ran one; null when the guard has not seen the plan yet. */
  guard: { verdict: GuardVerdict; reason_code: string | null } | null;
};

/** The reply to one message. TODO(BE #332): FE proposal of the response body. */
export type AssistantTurn = {
  conversation_id: string;
  /** The `message_id` it answers. */
  message_id: string;
  reply_id: string;
  correlation_id: string;
  /** The agent run it belongs to, when it started or joined one. */
  run_id: string | null;
  store_id: string;
  /** The Live state the reply was grounded on. */
  context_version: string | null;
  source: AssistantSource;
  /** The model that wrote it, such as `gemini-2.5-flash`; null for the demo script. */
  model: string | null;
  status: AssistantStatus;
  /** Why it was unsupported or refused, an `ASSISTANT_OUTCOME` or as served; null otherwise. */
  outcome_code: string | null;
  /** The user-facing explanation. Never chain of thought. */
  text: string;
  evidence: AssistantEvidence[];
  tool_calls: AssistantToolCall[];
  proposal: AssistantProposal | null;
  /** ISO timestamp. */
  created_at: string;
};

/** Why a message got no reply, with what the user needs to report it. */
export type AssistantFailure = {
  /** An `ASSISTANT_ERROR`, or apps/api's own code as served. */
  code: string;
  /** HTTP status; 0 when apps/api was not reached or never asked. */
  status: number;
  message: string;
  /** The `X-Correlation-ID` the message was sent with, to find it in the apps/api logs. */
  correlation_id: string | null;
  /** Whether sending the same message again may work. */
  retryable: boolean;
};

/** Where the Copilot's messages go: the demo script, or apps/api. */
export type Assistant = {
  mode: AssistantMode;
  /** Answers one message. Rejects with an `AssistantError` when there is no reply. */
  send: (conversationId: string, request: AssistantMessageRequest, correlationId: string) => Promise<AssistantTurn>;
};
