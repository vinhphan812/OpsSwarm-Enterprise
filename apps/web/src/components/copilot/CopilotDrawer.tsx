import { Button } from "@heroui/react";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useLayoutEffect, useRef, useState, type ComponentType, type FormEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { ChatIcon, ChevronDownIcon, CloseIcon, InfoIcon, KpiIcon, SendIcon, ShieldIcon, SimulationIcon } from "@/components/icons";
import { COPILOT_MAX_MESSAGE, COPILOT_WIDTH, PANEL_WIDTH } from "@/constants/app.constant";
import { ask, retry } from "@/core/assistant/conversation";
import { ASSISTANT_MODE } from "@/enums/assistant.enum";
import { useCopilotStore } from "@/state/copilot.store";
import { usePanelStore } from "@/state/panel.store";
import type { Assistant } from "@/types/assistant.type";
import { CopilotMessages, sourceLabel } from "./CopilotMessages";
import "./copilot.css";

/** The demo's sample products: P003 is out on the shelf with stock in the backroom; P017 is not in the demo store. */
const DEMO_SKU = "P003";
const MISSING_SKU = "P017";
/** Tallest the message box grows before it scrolls, in px. */
const INPUT_MAX_HEIGHT = 120;

/** A prompt to start from: what it asks, and what it shows. */
type Sample = { text: string; hint: string; Icon: ComponentType<{ className?: string }> };

/** Prompts to start from, for the twin the Copilot talks about. */
function useSamples(assistant: Assistant | null): Sample[] {
  const { t } = useTranslation();
  if (!assistant) return [];
  if (assistant.mode === ASSISTANT_MODE.Demo) {
    return [
      { text: t("copilot.samples.explain", { sku: DEMO_SKU }), hint: t("copilot.samples.hint.explain"), Icon: KpiIcon },
      { text: t("copilot.samples.plan", { sku: DEMO_SKU }), hint: t("copilot.samples.hint.plan"), Icon: SimulationIcon },
      { text: t("copilot.samples.approve"), hint: t("copilot.samples.hint.approve"), Icon: ShieldIcon },
      { text: t("copilot.samples.explain", { sku: MISSING_SKU }), hint: t("copilot.samples.hint.missing"), Icon: InfoIcon },
    ];
  }
  return [
    { text: t("copilot.samples.explain", { sku: MISSING_SKU }), hint: t("copilot.samples.hint.explain"), Icon: KpiIcon },
    { text: t("copilot.samples.plan", { sku: MISSING_SKU }), hint: t("copilot.samples.hint.livePlan"), Icon: SimulationIcon },
  ];
}

/** The chip beside the title: the demo script, or Live and, once one has answered, the model behind it. */
function SourceChip({ assistant }: { assistant: Assistant | null }) {
  const { t } = useTranslation();
  const lastTurn = useCopilotStore((state) => {
    for (let index = state.messages.length - 1; index >= 0; index -= 1) {
      const message = state.messages[index];
      if (message.kind === "reply") return message.turn;
    }
    return null;
  });
  if (!assistant) return <span className="copilot-source">{t("copilot.source.none")}</span>;
  if (assistant.mode === ASSISTANT_MODE.Demo) {
    return (
      <span className="copilot-source" data-source="demo_script" title={t("copilot.source.demoHint")}>
        {t("copilot.source.demo")}
      </span>
    );
  }
  return (
    <span className="copilot-source" data-source={lastTurn?.source ?? "live"} title={t("copilot.source.liveHint")}>
      {lastTurn ? sourceLabel(lastTurn) : t("copilot.source.live")}
    </span>
  );
}

/** The empty conversation: what the Copilot is for, and prompts that show it, each with what it demonstrates. */
function Welcome({ assistant, onAsk }: { assistant: Assistant | null; onAsk: (text: string) => void }) {
  const { t } = useTranslation();
  const samples = useSamples(assistant);
  return (
    <li className="copilot-welcome">
      <span className="copilot-welcome-mark" aria-hidden>
        <ChatIcon className="h-5 w-5" />
      </span>
      <h3 className="copilot-welcome-title">{t("copilot.welcome")}</h3>
      <p className="copilot-welcome-text">{t(assistant ? "copilot.intro" : "copilot.note.none")}</p>
      {samples.length ? (
        <div className="copilot-samples" role="group" aria-label={t("copilot.samples.label")}>
          {samples.map(({ text, hint, Icon }, index) => (
            <button
              key={text}
              type="button"
              className="copilot-sample"
              aria-label={text}
              aria-describedby={`copilot-sample-${index}`}
              onClick={() => onAsk(text)}
            >
              <span className="copilot-sample-icon" aria-hidden>
                <Icon className="h-4 w-4" />
              </span>
              <span className="copilot-sample-body">
                <span className="copilot-sample-text">{text}</span>
                <span className="copilot-sample-hint" id={`copilot-sample-${index}`}>
                  {hint}
                </span>
              </span>
              <ChevronDownIcon className="copilot-sample-go" />
            </button>
          ))}
        </div>
      ) : null}
    </li>
  );
}

/**
 * The Store Copilot (#332): a conversation beside the Agent Activity panel, which it never
 * replaces. It reads the store and opens plans as simulations through `assistant`; it never
 * writes the Live Twin, and approval stays with the Simulation banner. Its tool calls show in
 * the Agent Activity timeline. Enter sends, Shift+Enter breaks the line, Escape closes it.
 */
export function CopilotDrawer({ assistant }: { assistant: Assistant | null }) {
  const { t } = useTranslation();
  const open = useCopilotStore((state) => state.open);
  const setOpen = useCopilotStore((state) => state.setOpen);
  const messages = useCopilotStore((state) => state.messages);
  const pending = useCopilotStore((state) => state.pending);
  // Sit left of the floating Agent Activity panel instead of under it.
  const panelInset = usePanelStore((state) => (state.open ? PANEL_WIDTH + 24 : 0));
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const list = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);

  // Keep the latest message in view.
  useEffect(() => {
    const node = list.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, pending]);

  // The message box grows with what is typed, up to INPUT_MAX_HEIGHT, then scrolls.
  useLayoutEffect(() => {
    const node = input.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, INPUT_MAX_HEIGHT)}px`;
  }, [text, open]);

  const send = (value: string) => {
    if (!value.trim() || pending) return;
    setText("");
    void ask(assistant, value);
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    send(text);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      send(text);
    }
  };
  const note = assistant?.mode === ASSISTANT_MODE.Demo ? "copilot.note.demo" : "copilot.note.live";
  const canSend = text.trim() !== "" && pending === null;

  return (
    <AnimatePresence>
      {open ? (
        <motion.aside
          key="copilot"
          id="copilot"
          className="copilot"
          data-testid="copilot"
          data-mode={assistant?.mode ?? "none"}
          aria-labelledby="copilot-title"
          style={{ width: COPILOT_WIDTH, marginRight: panelInset }}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          onKeyDown={(event) => {
            if (event.key === "Escape") setOpen(false);
          }}
        >
          <header className="copilot-head">
            <span className="copilot-mark" aria-hidden>
              <ChatIcon className="h-4 w-4" />
            </span>
            <div className="copilot-heading">
              <div className="copilot-title-row">
                <h2 id="copilot-title">{t("copilot.title")}</h2>
                <SourceChip assistant={assistant} />
              </div>
              {assistant ? (
                <p className="copilot-subtitle" data-mode={assistant.mode}>
                  {t(note)}
                </p>
              ) : null}
            </div>
            <Button
              isIconOnly
              size="sm"
              variant="light"
              radius="full"
              aria-label={t("copilot.close")}
              title={t("copilot.close")}
              onPress={() => setOpen(false)}
              className="min-w-0 shrink-0 cursor-pointer text-ink-muted data-[hover=true]:bg-card data-[hover=true]:text-ink"
            >
              <CloseIcon className="h-4 w-4" />
            </Button>
          </header>

          <ol
            ref={list}
            className="copilot-messages"
            data-empty={messages.length === 0 || undefined}
            aria-label={t("copilot.label")}
            aria-live="polite"
            aria-busy={pending !== null}
          >
            {messages.length === 0 ? (
              <Welcome assistant={assistant} onAsk={send} />
            ) : (
              <CopilotMessages messages={messages} busy={pending !== null} onRetry={(messageId) => void retry(assistant, messageId)} />
            )}
            {pending ? (
              <li className="copilot-row" data-kind="pending" role="status">
                <span className="copilot-avatar" aria-hidden>
                  <ChatIcon className="h-3.5 w-3.5" />
                </span>
                <span className="copilot-bubble copilot-typing">
                  <span className="copilot-dots" aria-hidden>
                    <i />
                    <i />
                    <i />
                  </span>
                  {t("copilot.thinking")}
                </span>
              </li>
            ) : null}
          </ol>

          <form className="copilot-compose" onSubmit={onSubmit}>
            <div className="copilot-composer">
              <label className="sr-only" htmlFor="copilot-input">
                {t("copilot.input")}
              </label>
              <textarea
                id="copilot-input"
                ref={input}
                className="copilot-input"
                rows={1}
                maxLength={COPILOT_MAX_MESSAGE}
                value={text}
                placeholder={t("copilot.placeholder", { sku: assistant?.mode === ASSISTANT_MODE.Demo ? DEMO_SKU : MISSING_SKU })}
                aria-describedby="copilot-hint"
                onChange={(event) => setText(event.target.value)}
                onKeyDown={onKeyDown}
              />
              <button type="submit" className="copilot-send" aria-label={t("copilot.send")} title={t("copilot.send")} disabled={!canSend}>
                <SendIcon className="h-4 w-4" />
              </button>
            </div>
            <p id="copilot-hint" className="copilot-hint">
              {t("copilot.hint")}
            </p>
          </form>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}

/** The header's Copilot button: opens and closes the drawer. */
export function CopilotButton() {
  const { t } = useTranslation();
  const open = useCopilotStore((state) => state.open);
  const toggle = useCopilotStore((state) => state.toggle);
  return (
    <button
      type="button"
      className="twin-header-copilot"
      aria-expanded={open}
      aria-controls="copilot"
      title={t("copilot.openHint")}
      onClick={toggle}
    >
      <ChatIcon className="h-3.5 w-3.5" />
      {t("copilot.open")}
    </button>
  );
}
