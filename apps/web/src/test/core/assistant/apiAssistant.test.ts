// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantError, createApiAssistant } from "@/core/assistant/apiAssistant";
import type { AssistantMessageRequest } from "@/types/assistant.type";
import { servedTurn } from "./turn";

const request: AssistantMessageRequest = {
  message_id: "msg-1",
  text: "What is happening with P017?",
  store_id: "store-001",
  context_version: "store-001:v7",
  mode: "live",
};

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

async function failureOf(answer: Response | Error) {
  const fetchImpl = vi.fn(async () => {
    if (answer instanceof Error) throw answer;
    return answer;
  });
  const error = await createApiAssistant("http://127.0.0.1:8000", fetchImpl).send("conv-1", request, "copilot-1").catch((caught: unknown) => caught);
  expect(error).toBeInstanceOf(AssistantError);
  return (error as AssistantError).failure;
}

afterEach(() => window.history.replaceState(null, "", "/"));

describe("createApiAssistant", () => {
  it("posts the message to the conversation, with its id in the body and the correlation id as a header", async () => {
    const fetchImpl = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => json(servedTurn()));
    const turn = await createApiAssistant("http://127.0.0.1:8000/", fetchImpl).send("conv-1", request, "copilot-1");
    const [url, init] = fetchImpl.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8000/assistant/conversations/conv-1/messages");
    expect(init?.method).toBe("POST");
    expect(new Headers(init?.headers).get("x-correlation-id")).toBe("copilot-1");
    expect(JSON.parse(String(init?.body))).toEqual(request);
    expect(turn.reply_id).toBe("reply-1");
  });

  it("says the route is not deployed on FastAPI's own 404, and does not offer a retry", async () => {
    expect(await failureOf(json({ error: { code: "http_error", message: "Not Found" } }, 404))).toEqual({
      code: "assistant_not_deployed",
      status: 404,
      message: "Not Found",
      correlation_id: "copilot-1",
      retryable: false,
    });
  });

  it("names Gemini and BigQuery failures, which a retry may pass", async () => {
    expect(await failureOf(json({ error: { code: "model_unavailable", message: "Vertex AI did not answer." } }, 503))).toMatchObject({
      code: "model_unavailable",
      status: 503,
      retryable: true,
    });
    expect(await failureOf(json({ error: { code: "analytics_unavailable", message: "x" } }, 503))).toMatchObject({
      code: "analytics_unavailable",
      retryable: true,
    });
  });

  it("tells a stale context, a refusal and a rate limit apart", async () => {
    expect(await failureOf(json({ error: { code: "VERSION_STALE", message: "x" } }, 409))).toMatchObject({ code: "stale_context", retryable: false });
    expect(await failureOf(json({ error: { code: "forbidden", message: "x" } }, 403))).toMatchObject({ code: "permission_denied", retryable: false });
    expect(await failureOf(json({ error: { code: "too_many", message: "x" } }, 429))).toMatchObject({ code: "rate_limited", retryable: true });
    expect(await failureOf(json({ error: { code: "validation_error", message: "x" } }, 422))).toMatchObject({ code: "invalid_message", retryable: false });
  });

  it("says apps/api could not be reached, or that its reply was malformed, and never makes one up", async () => {
    expect(await failureOf(new TypeError("Failed to fetch"))).toMatchObject({ code: "network_error", status: 0, retryable: true });
    expect(await failureOf(new Response("not json", { status: 200 }))).toMatchObject({ code: "invalid_reply", retryable: true });
    expect(await failureOf(json(servedTurn({ message_id: "msg-other" })))).toMatchObject({ code: "invalid_reply" });
  });

  it("never sends anything from the demo", async () => {
    window.history.replaceState(null, "", "/?twin=demo");
    const fetchImpl = vi.fn();
    const error = await createApiAssistant("http://127.0.0.1:8000", fetchImpl).send("conv-1", request, "copilot-1").catch((caught: unknown) => caught);
    expect((error as AssistantError).failure.code).toBe("demo_read_only");
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
