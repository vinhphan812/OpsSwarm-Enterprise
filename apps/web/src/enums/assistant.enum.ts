/**
 * The Store Copilot's conversation contract (#332). TODO(BE #332): FE proposal for
 * `POST /assistant/conversations/{conversation_id}/messages`; agree the values with apps/api.
 */

/** How a turn ended. A failed request is not a turn: it has no reply (`AssistantFailure`). */
export const ASSISTANT_STATUS = {
  /** An explanation, grounded on the evidence it cites. */
  Answered: "answered",
  /** A plan, opened as a simulation; nothing in Live has changed. */
  Proposed: "proposed",
  /** The assistant cannot do it: an unknown SKU, an intent it does not handle, no plan. */
  Unsupported: "unsupported",
  /** The assistant will not do it: a write to Live, an approval from chat, an injected instruction. */
  Refused: "refused",
} as const;
export type AssistantStatus = (typeof ASSISTANT_STATUS)[keyof typeof ASSISTANT_STATUS];
export const ASSISTANT_STATUSES: readonly AssistantStatus[] = Object.values(ASSISTANT_STATUS);

/** Who wrote the reply: the scripted demo, or Gemini on Vertex AI behind apps/api. */
export const ASSISTANT_SOURCE = {
  DemoScript: "demo_script",
  VertexGemini: "vertex_gemini",
} as const;
export type AssistantSource = (typeof ASSISTANT_SOURCE)[keyof typeof ASSISTANT_SOURCE];
export const ASSISTANT_SOURCES: readonly AssistantSource[] = Object.values(ASSISTANT_SOURCE);

/** Which twin the conversation is about. Only `live` is ever sent to apps/api. */
export const ASSISTANT_MODE = {
  Live: "live",
  Demo: "demo",
} as const;
export type AssistantMode = (typeof ASSISTANT_MODE)[keyof typeof ASSISTANT_MODE];

/**
 * What a tool of `agents/orchestrator/tool_registry.py` may do. The chat gets read and
 * simulation tools only; `commit_request` and live writes are never offered to it.
 */
export const TOOL_CAPABILITY = {
  Read: "read",
  Simulation: "simulation",
} as const;
export type ToolCapability = (typeof TOOL_CAPABILITY)[keyof typeof TOOL_CAPABILITY];
export const TOOL_CAPABILITIES: readonly ToolCapability[] = Object.values(TOOL_CAPABILITY);

/** Where a piece of evidence was read. `fixture` is the demo's synthetic data, never Live. */
export const EVIDENCE_SOURCE = {
  Firestore: "firestore",
  BigQuery: "bigquery",
  Detector: "detector",
  Evaluator: "evaluator",
  Fixture: "fixture",
} as const;
export type EvidenceSource = (typeof EVIDENCE_SOURCE)[keyof typeof EVIDENCE_SOURCE];
export const EVIDENCE_SOURCES: readonly EvidenceSource[] = Object.values(EVIDENCE_SOURCE);

/** What a piece of evidence is about. */
export const EVIDENCE_KIND = {
  Inventory: "inventory",
  Sales: "sales",
  Anomaly: "anomaly",
  Forecast: "forecast",
  Simulation: "simulation",
} as const;
export type EvidenceKind = (typeof EVIDENCE_KIND)[keyof typeof EVIDENCE_KIND];

/** Why a turn was unsupported or refused (`AssistantTurn.outcome_code`); the UI labels the ones it knows. */
export const ASSISTANT_OUTCOME = {
  SkuNotFound: "sku_not_found",
  NoSku: "no_sku",
  NoPlan: "no_plan",
  UnknownIntent: "unknown_intent",
  LiveWriteForbidden: "live_write_forbidden",
  ApprovalInChat: "approval_in_chat",
} as const;
export type AssistantOutcome = (typeof ASSISTANT_OUTCOME)[keyof typeof ASSISTANT_OUTCOME];

/**
 * Why a message got no reply (`AssistantFailure.code`). The upper ones are apps/api's error
 * codes as the FE proposes them; `invalid_reply`, `network_error` and the rest are the FE's own.
 */
export const ASSISTANT_ERROR = {
  /** apps/api answered 404 on the assistant route: it is not deployed there. */
  NotDeployed: "assistant_not_deployed",
  /** Gemini on Vertex AI did not answer. */
  ModelUnavailable: "model_unavailable",
  /** BigQuery analytics did not answer. */
  AnalyticsUnavailable: "analytics_unavailable",
  /** Live moved on past the `context_version` the message was sent with. */
  StaleContext: "stale_context",
  PermissionDenied: "permission_denied",
  RateLimited: "rate_limited",
  /** The message broke the request contract (too long, wrong store). */
  InvalidMessage: "invalid_message",
  /** apps/api could not be reached. */
  Network: "network_error",
  /** The reply broke the contract, so none of it is shown. */
  InvalidReply: "invalid_reply",
  /** Any other failure, with its HTTP status. */
  RequestFailed: "request_failed",
  /** This twin has no assistant (a `?twin=` dev twin other than memory, demo or firestore). */
  NoAssistant: "no_assistant",
} as const;
export type AssistantErrorCode = (typeof ASSISTANT_ERROR)[keyof typeof ASSISTANT_ERROR];
