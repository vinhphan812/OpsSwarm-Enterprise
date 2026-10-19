import { create } from "zustand";
import type { AssistantFailure, AssistantMessageRequest, AssistantTurn } from "@/types/assistant.type";

/** One line of the Copilot conversation: what the user sent, a reply, or why a message got none. */
export type CopilotMessage =
  | { kind: "user"; id: string; request: AssistantMessageRequest; correlationId: string; at: string }
  | { kind: "reply"; id: string; turn: AssistantTurn }
  | { kind: "error"; id: string; messageId: string; failure: AssistantFailure; at: string };

type CopilotStore = {
  /** Whether the drawer is open. Closed on load. */
  open: boolean;
  /** One conversation per page load. */
  conversationId: string;
  messages: CopilotMessage[];
  /** The `message_id` waiting for its reply, or null. One at a time. */
  pending: string | null;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  addUser: (request: AssistantMessageRequest, correlationId: string) => void;
  /** Adds a reply; a reply already shown (same `reply_id`) is not added again. */
  addReply: (turn: AssistantTurn) => void;
  /** Says why `messageId` got no reply, in place of an earlier failure of the same message. */
  addError: (messageId: string, failure: AssistantFailure) => void;
  setPending: (messageId: string | null) => void;
};

export const newConversationId = () => `conv-${crypto.randomUUID()}`;

/** The Copilot conversation on this page. Nothing in it is ever written to the twin. */
export const useCopilotStore = create<CopilotStore>()((set) => ({
  open: false,
  conversationId: newConversationId(),
  messages: [],
  pending: null,
  setOpen: (open) => set({ open }),
  toggle: () => set((state) => ({ open: !state.open })),
  addUser: (request, correlationId) =>
    set((state) => ({
      messages: [
        ...state.messages,
        { kind: "user", id: request.message_id, request, correlationId, at: new Date().toISOString() },
      ],
    })),
  addReply: (turn) =>
    set((state) =>
      state.messages.some((message) => message.kind === "reply" && message.turn.reply_id === turn.reply_id)
        ? {}
        : {
            messages: [
              ...state.messages.filter((message) => !(message.kind === "error" && message.messageId === turn.message_id)),
              { kind: "reply", id: turn.reply_id, turn },
            ],
          },
    ),
  addError: (messageId, failure) =>
    set((state) => ({
      messages: [
        ...state.messages.filter((message) => !(message.kind === "error" && message.messageId === messageId)),
        { kind: "error", id: `error-${messageId}`, messageId, failure, at: new Date().toISOString() },
      ],
    })),
  setPending: (pending) => set({ pending }),
}));
