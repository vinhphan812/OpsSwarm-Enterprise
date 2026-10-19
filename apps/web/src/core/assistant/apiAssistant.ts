import i18n from "@/i18n";
import { ApiError, configuredBase, toApiError } from "@/core/api/client";
import { isDemoMode } from "@/core/twin/demoMode";
import { ASSISTANT_ERROR, ASSISTANT_MODE } from "@/enums/assistant.enum";
import type { Assistant, AssistantFailure } from "@/types/assistant.type";
import { InvalidAssistantReplyError, parseAssistantTurn } from "./parseAssistantTurn";

/** A message that got no reply, and why. */
export class AssistantError extends Error {
  readonly failure: AssistantFailure;

  constructor(failure: AssistantFailure) {
    super(failure.message);
    this.name = "AssistantError";
    this.failure = failure;
  }
}

/** apps/api's error codes the Copilot names as its own, by the code served. */
const SERVED_CODES: Record<string, string> = {
  stale_context: ASSISTANT_ERROR.StaleContext,
  VERSION_MISMATCH: ASSISTANT_ERROR.StaleContext,
  VERSION_STALE: ASSISTANT_ERROR.StaleContext,
  model_unavailable: ASSISTANT_ERROR.ModelUnavailable,
  llm_unavailable: ASSISTANT_ERROR.ModelUnavailable,
  analytics_unavailable: ASSISTANT_ERROR.AnalyticsUnavailable,
  validation_error: ASSISTANT_ERROR.InvalidMessage,
};

/** The code a failed answer of apps/api goes by: what it served, or what its status says. */
function codeOf({ status, code }: ApiError): string {
  if (SERVED_CODES[code]) return SERVED_CODES[code];
  if (status === 0) return ASSISTANT_ERROR.Network;
  // FastAPI's own 404 (`http_error`): no route there, as opposed to a 404 the assistant served.
  if (status === 404 && code === "http_error") return ASSISTANT_ERROR.NotDeployed;
  if (status === 401 || status === 403) return ASSISTANT_ERROR.PermissionDenied;
  if (status === 409) return ASSISTANT_ERROR.StaleContext;
  if (status === 429) return ASSISTANT_ERROR.RateLimited;
  return code === "request_failed" ? ASSISTANT_ERROR.RequestFailed : code;
}

/** Codes a resend of the same message may fix; the rest need the user (or apps/api) to change something. */
const RETRYABLE: ReadonlySet<string> = new Set([
  ASSISTANT_ERROR.Network,
  ASSISTANT_ERROR.ModelUnavailable,
  ASSISTANT_ERROR.AnalyticsUnavailable,
  ASSISTANT_ERROR.RateLimited,
  ASSISTANT_ERROR.InvalidReply,
  ASSISTANT_ERROR.RequestFailed,
]);

/** Why a message got no reply, as the Copilot shows it. A 5xx may pass on a resend. */
export function failureOf(error: unknown, correlationId: string | null): AssistantFailure {
  if (error instanceof AssistantError) return error.failure;
  if (error instanceof InvalidAssistantReplyError) {
    return { code: ASSISTANT_ERROR.InvalidReply, status: 200, message: error.message, correlation_id: correlationId, retryable: true };
  }
  if (error instanceof ApiError) {
    const code = codeOf(error);
    const retryable = RETRYABLE.has(code) || error.status >= 500;
    return { code, status: error.status, message: error.message, correlation_id: correlationId, retryable };
  }
  const message = error instanceof Error ? error.message : String(error);
  return { code: ASSISTANT_ERROR.RequestFailed, status: 0, message, correlation_id: correlationId, retryable: true };
}

/**
 * The Copilot on apps/api: `POST /assistant/conversations/{id}/messages`, which answers with
 * Gemini on Vertex AI and the allow-listed read and simulation tools. When it does not answer,
 * the message fails with the reason; nothing stands in for the reply. Never under the demo.
 * TODO(BE #332): apps/api serves no assistant route yet, so every message fails with
 * `assistant_not_deployed` until it does.
 */
export function createApiAssistant(baseUrl: string = configuredBase, fetchImpl?: typeof fetch): Assistant {
  const base = baseUrl.replace(/\/$/, "");
  return {
    mode: ASSISTANT_MODE.Live,
    async send(conversationId, request, correlationId) {
      if (isDemoMode()) {
        throw new AssistantError({
          code: "demo_read_only",
          status: 0,
          message: i18n.t("errors.demoReadOnly"),
          correlation_id: correlationId,
          retryable: false,
        });
      }
      const doFetch = fetchImpl ?? fetch;
      let response: Response;
      try {
        response = await doFetch(`${base}/assistant/conversations/${encodeURIComponent(conversationId)}/messages`, {
          method: "POST",
          // `x-correlation-id` is one of the headers apps/api's CORS allows; the message id is in the body.
          headers: { "Content-Type": "application/json", "X-Correlation-ID": correlationId },
          body: JSON.stringify(request),
        });
      } catch {
        throw new AssistantError(failureOf(new ApiError(0, "network_error", i18n.t("errors.unreachable")), correlationId));
      }
      if (!response.ok) throw new AssistantError(failureOf(await toApiError(response), correlationId));
      let raw: unknown;
      try {
        raw = await response.json();
      } catch {
        throw new AssistantError(failureOf(new InvalidAssistantReplyError("reply"), correlationId));
      }
      try {
        return parseAssistantTurn(raw, { conversationId, messageId: request.message_id });
      } catch (error) {
        throw new AssistantError(failureOf(error, correlationId));
      }
    },
  };
}
