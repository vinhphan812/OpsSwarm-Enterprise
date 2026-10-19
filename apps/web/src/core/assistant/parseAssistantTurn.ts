import {
  ASSISTANT_SOURCES,
  ASSISTANT_STATUS,
  ASSISTANT_STATUSES,
  EVIDENCE_SOURCES,
  TOOL_CAPABILITIES,
} from "@/enums/assistant.enum";
import { ACTION_TYPE, GUARD_VERDICT, type GuardVerdict } from "@/enums/simulation.enum";
import type {
  AssistantConstraint,
  AssistantEvidence,
  AssistantProposal,
  AssistantToolCall,
  AssistantTurn,
} from "@/types/assistant.type";
import type { CandidateKPI, SimulationAction } from "@/types/simulation.type";

/** The reply breaks the contract at `field`, so none of it is shown. */
export class InvalidAssistantReplyError extends Error {
  readonly field: string;

  constructor(field: string) {
    super(`The assistant's reply is malformed at "${field}".`);
    this.name = "InvalidAssistantReplyError";
    this.field = field;
  }
}

type Fields = Record<string, unknown>;

const isObject = (value: unknown): value is Fields =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isText = (value: unknown): value is string => typeof value === "string" && value.trim() !== "";
const isTextOrNull = (value: unknown): value is string | null | undefined => value == null || isText(value);
const isCount = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0;
const textOrNull = (value: unknown) => (isText(value) ? value : null);

const ACTION_TYPES: readonly unknown[] = Object.values(ACTION_TYPE);
const VERDICTS: readonly unknown[] = Object.values(GUARD_VERDICT);

/** A list field: missing is empty, anything but an array breaks the contract. */
function listOf<T>(raw: Fields, field: string, parse: (item: unknown, at: string) => T): T[] {
  const value = raw[field];
  if (value == null) return [];
  if (!Array.isArray(value)) throw new InvalidAssistantReplyError(field);
  return value.map((item, index) => parse(item, `${field}[${index}]`));
}

function parseEvidence(raw: unknown, at: string): AssistantEvidence {
  if (!isObject(raw) || !isText(raw.id) || !isText(raw.kind) || !isText(raw.label) || typeof raw.detail !== "string") {
    throw new InvalidAssistantReplyError(at);
  }
  if (!EVIDENCE_SOURCES.includes(raw.source as never)) throw new InvalidAssistantReplyError(`${at}.source`);
  const confidence = raw.confidence ?? null;
  if (confidence !== null && (typeof confidence !== "number" || confidence < 0 || confidence > 1)) {
    throw new InvalidAssistantReplyError(`${at}.confidence`);
  }
  return {
    id: raw.id,
    kind: raw.kind,
    label: raw.label,
    detail: raw.detail,
    source: raw.source as AssistantEvidence["source"],
    tool: textOrNull(raw.tool),
    sku: textOrNull(raw.sku),
    as_of: textOrNull(raw.as_of),
    confidence,
  };
}

function parseToolCall(raw: unknown, at: string): AssistantToolCall {
  if (!isObject(raw) || !isText(raw.tool) || typeof raw.ok !== "boolean") throw new InvalidAssistantReplyError(at);
  // The chat is offered read and simulation tools only: a commit request or a write here means the reply cannot be trusted.
  if (!TOOL_CAPABILITIES.includes(raw.capability as never)) throw new InvalidAssistantReplyError(`${at}.capability`);
  const duration = raw.duration_ms ?? null;
  if (duration !== null && !isCount(duration)) throw new InvalidAssistantReplyError(`${at}.duration_ms`);
  return {
    tool: raw.tool,
    capability: raw.capability as AssistantToolCall["capability"],
    ok: raw.ok,
    error_code: textOrNull(raw.error_code),
    sku: textOrNull(raw.sku),
    duration_ms: duration,
  };
}

function parseAction(raw: unknown, at: string): SimulationAction {
  if (!isObject(raw) || !ACTION_TYPES.includes(raw.type) || !isText(raw.sku)) throw new InvalidAssistantReplyError(at);
  switch (raw.type) {
    case ACTION_TYPE.MoveProduct:
      if (!isText(raw.from_slot) || !isText(raw.to_slot)) throw new InvalidAssistantReplyError(at);
      return { type: raw.type, sku: raw.sku, from_slot: raw.from_slot, to_slot: raw.to_slot };
    case ACTION_TYPE.ChangeFacings:
      if (!isCount(raw.facings)) throw new InvalidAssistantReplyError(at);
      return { type: raw.type, sku: raw.sku, facings: raw.facings };
    default:
      if (!isCount(raw.quantity)) throw new InvalidAssistantReplyError(at);
      return { type: ACTION_TYPE.ReplenishShelf, sku: raw.sku, quantity: raw.quantity };
  }
}

/** A KPI as `parseCandidate` takes one: anything incomplete is left out, not guessed. */
function kpisOf(value: unknown): CandidateKPI[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((kpi): CandidateKPI[] =>
    isObject(kpi) && isText(kpi.name) && typeof kpi.value === "number" && isText(kpi.unit) && isText(kpi.source)
      ? [{ name: kpi.name, value: kpi.value, unit: kpi.unit, source: kpi.source }]
      : [],
  );
}

function parseConstraint(raw: unknown, at: string): AssistantConstraint {
  if (!isObject(raw) || !isText(raw.label) || typeof raw.passed !== "boolean") throw new InvalidAssistantReplyError(at);
  return { label: raw.label, passed: raw.passed };
}

function parseProposal(raw: unknown): AssistantProposal | null {
  if (raw == null) return null;
  if (!isObject(raw)) throw new InvalidAssistantReplyError("proposal");
  for (const field of ["simulation_id", "base_context_version", "summary"] as const) {
    if (!isText(raw[field])) throw new InvalidAssistantReplyError(`proposal.${field}`);
  }
  for (const field of ["candidate_id", "decision_id", "evaluator_version"] as const) {
    if (!isTextOrNull(raw[field])) throw new InvalidAssistantReplyError(`proposal.${field}`);
  }
  const actions = listOf(raw, "actions", parseAction);
  if (!actions.length) throw new InvalidAssistantReplyError("proposal.actions");
  const guard = raw.guard ?? null;
  if (guard !== null && (!isObject(guard) || !VERDICTS.includes(guard.verdict) || !isTextOrNull(guard.reason_code))) {
    throw new InvalidAssistantReplyError("proposal.guard");
  }
  return {
    simulation_id: raw.simulation_id as string,
    candidate_id: textOrNull(raw.candidate_id),
    decision_id: textOrNull(raw.decision_id),
    base_context_version: raw.base_context_version as string,
    actions,
    summary: raw.summary as string,
    kpis: kpisOf(raw.kpis),
    baseline_kpis: kpisOf(raw.baseline_kpis),
    evaluator_version: textOrNull(raw.evaluator_version),
    constraints: listOf(raw, "constraints", parseConstraint),
    guard: guard === null ? null : { verdict: guard.verdict as GuardVerdict, reason_code: textOrNull(guard.reason_code) },
  };
}

/**
 * Checks a reply of `POST /assistant/conversations/{id}/messages` against the contract, and
 * that it answers `expected`: a reply to another conversation or message is never shown as
 * this one's. Anything off throws `InvalidAssistantReplyError`.
 */
export function parseAssistantTurn(raw: unknown, expected: { conversationId: string; messageId: string }): AssistantTurn {
  if (!isObject(raw)) throw new InvalidAssistantReplyError("reply");
  for (const field of ["conversation_id", "message_id", "reply_id", "correlation_id", "store_id", "created_at"] as const) {
    if (!isText(raw[field])) throw new InvalidAssistantReplyError(field);
  }
  if (raw.conversation_id !== expected.conversationId) throw new InvalidAssistantReplyError("conversation_id");
  if (raw.message_id !== expected.messageId) throw new InvalidAssistantReplyError("message_id");
  if (!ASSISTANT_SOURCES.includes(raw.source as never)) throw new InvalidAssistantReplyError("source");
  if (!ASSISTANT_STATUSES.includes(raw.status as never)) throw new InvalidAssistantReplyError("status");
  if (typeof raw.text !== "string") throw new InvalidAssistantReplyError("text");
  for (const field of ["run_id", "context_version", "model", "outcome_code"] as const) {
    if (!isTextOrNull(raw[field])) throw new InvalidAssistantReplyError(field);
  }
  const proposal = parseProposal(raw.proposal);
  // A proposal and its status come together, or not at all.
  if ((raw.status === ASSISTANT_STATUS.Proposed) !== (proposal !== null)) throw new InvalidAssistantReplyError("proposal");
  return {
    conversation_id: raw.conversation_id as string,
    message_id: raw.message_id as string,
    reply_id: raw.reply_id as string,
    correlation_id: raw.correlation_id as string,
    run_id: textOrNull(raw.run_id),
    store_id: raw.store_id as string,
    context_version: textOrNull(raw.context_version),
    source: raw.source as AssistantTurn["source"],
    model: textOrNull(raw.model),
    status: raw.status as AssistantTurn["status"],
    outcome_code: textOrNull(raw.outcome_code),
    text: raw.text,
    evidence: listOf(raw, "evidence", parseEvidence),
    tool_calls: listOf(raw, "tool_calls", parseToolCall),
    proposal,
    created_at: raw.created_at as string,
  };
}
