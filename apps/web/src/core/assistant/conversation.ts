import i18n from "@/i18n";
import { COPILOT_MAX_MESSAGE } from "@/constants/app.constant";
import { ASSISTANT_ERROR, ASSISTANT_MODE } from "@/enums/assistant.enum";
import { storeFixture } from "@/fixtures/storeFixture";
import { useCopilotStore } from "@/state/copilot.store";
import { useRunStore } from "@/state/run.store";
import { useTwinStore } from "@/state/twin.store";
import type { Assistant, AssistantMessageRequest } from "@/types/assistant.type";
import { failureOf } from "./apiAssistant";
import { turnActivity } from "./assistantActivity";

/** Sends `request` and shows what comes back: the reply and its tool calls in the timeline, or why there is none. */
async function deliver(assistant: Assistant | null, request: AssistantMessageRequest, correlationId: string) {
  const copilot = useCopilotStore.getState();
  copilot.setPending(request.message_id);
  try {
    if (!assistant) {
      copilot.addError(request.message_id, {
        code: ASSISTANT_ERROR.NoAssistant,
        status: 0,
        message: i18n.t("copilot.error.no_assistant"),
        correlation_id: null,
        retryable: false,
      });
      return;
    }
    const turn = await assistant.send(copilot.conversationId, request, correlationId);
    useCopilotStore.getState().addReply(turn);
    const { append } = useRunStore.getState();
    turnActivity(turn).forEach(append);
  } catch (error) {
    useCopilotStore.getState().addError(request.message_id, failureOf(error, correlationId));
  } finally {
    useCopilotStore.getState().setPending(null);
  }
}

/**
 * Sends what the user typed, with the Live state on screen as its `context_version`. Nothing
 * while a message is waiting, or for blank text. Text past `COPILOT_MAX_MESSAGE` is cut there.
 */
export function ask(assistant: Assistant | null, text: string): Promise<void> {
  const trimmed = text.trim().slice(0, COPILOT_MAX_MESSAGE);
  const copilot = useCopilotStore.getState();
  if (!trimmed || copilot.pending) return Promise.resolve();
  const live = useTwinStore.getState().live;
  const request: AssistantMessageRequest = {
    message_id: `msg-${crypto.randomUUID()}`,
    text: trimmed,
    store_id: live?.store_id ?? storeFixture.storeId,
    context_version: live?.context_version ?? null,
    mode: assistant?.mode ?? ASSISTANT_MODE.Live,
  };
  const correlationId = `copilot-${crypto.randomUUID()}`;
  copilot.addUser(request, correlationId);
  return deliver(assistant, request, correlationId);
}

/**
 * Sends a failed message again. The same message, same id, so apps/api answers it once
 * however often it is sent; but after `stale_context` it is asked anew on the current Live.
 */
export function retry(assistant: Assistant | null, messageId: string): Promise<void> {
  const { messages, pending } = useCopilotStore.getState();
  if (pending) return Promise.resolve();
  const sent = messages.find((message) => message.kind === "user" && message.id === messageId);
  const failed = messages.find((message) => message.kind === "error" && message.messageId === messageId);
  if (sent?.kind !== "user") return Promise.resolve();
  if (failed?.kind === "error" && failed.failure.code === ASSISTANT_ERROR.StaleContext) return ask(assistant, sent.request.text);
  return deliver(assistant, sent.request, sent.correlationId);
}
