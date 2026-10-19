import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import { AlertIcon, ChatIcon, RetryIcon } from "@/components/icons";
import { SkuChip, clock } from "@/components/layout/ActivityLog";
import { ASSISTANT_ERROR, ASSISTANT_SOURCE, ASSISTANT_STATUS } from "@/enums/assistant.enum";
import { format } from "@/core/utils/format";
import type { CopilotMessage } from "@/state/copilot.store";
import type { AssistantFailure, AssistantTurn } from "@/types/assistant.type";
import { CopilotProposal } from "./CopilotProposal";

/** Who wrote a reply, as its source and model say. */
export function sourceLabel(turn: Pick<AssistantTurn, "source" | "model">): string {
  if (turn.source === ASSISTANT_SOURCE.DemoScript) return i18n.t("copilot.source.demo");
  return turn.model ? i18n.t("copilot.source.geminiModel", { model: turn.model }) : i18n.t("copilot.source.gemini");
}

/** Every product a reply is about, in the order it names them. */
function productsOf(turn: AssistantTurn): string[] {
  const skus = [
    ...turn.evidence.map((item) => item.sku),
    ...(turn.proposal?.actions.map((action) => action.sku) ?? []),
    ...turn.tool_calls.map((call) => call.sku),
  ];
  return [...new Set(skus.filter((sku): sku is string => sku !== null))];
}

/** A label for a served code: the Copilot's own words when it knows the code, the code otherwise. */
function codeLabel(prefix: "copilot.outcome" | "copilot.error", code: string, fallback: string = code): string {
  return String(i18n.t(`${prefix}.${code}` as never, { defaultValue: fallback } as never));
}

/** The Copilot's side of the conversation: a small mark beside each of its bubbles. */
function Avatar({ alert = false }: { alert?: boolean }) {
  return (
    <span className="copilot-avatar" data-alert={alert || undefined} aria-hidden>
      {alert ? <AlertIcon className="h-3.5 w-3.5" /> : <ChatIcon className="h-3.5 w-3.5" />}
    </span>
  );
}

/** What a reply rests on, folded until opened: its evidence, the tools it called, and how to trace it. */
function ReplyDetails({ turn }: { turn: AssistantTurn }) {
  const { t } = useTranslation();
  return (
    <div className="copilot-details-row">
      {turn.evidence.length ? (
        <details className="copilot-details">
          <summary>{t("copilot.evidence.title", { count: turn.evidence.length })}</summary>
          <ul>
            {turn.evidence.map((item) => (
              <li key={item.id}>
                <span className="copilot-details-label">{item.label}</span>
                <span>{item.detail}</span>
                <span className="copilot-details-meta">
                  <span className="copilot-source" data-source={item.source}>
                    {t(`copilot.evidence.source.${item.source}`)}
                  </span>
                  {item.as_of ? <span>{t("copilot.evidence.asOf", { time: item.as_of })}</span> : null}
                  {item.confidence !== null ? (
                    <span>{t("copilot.evidence.confidence", { value: format.percent(item.confidence) })}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {turn.tool_calls.length ? (
        <details className="copilot-details">
          <summary>{t("copilot.tools.title", { count: turn.tool_calls.length })}</summary>
          <ul>
            {turn.tool_calls.map((call, index) => (
              <li key={`${call.tool}:${index}`} className="copilot-tool" data-ok={call.ok}>
                <code>{call.tool}</code>
                {call.sku ? <span>{call.sku}</span> : null}
                <span className="copilot-details-meta">
                  {t(`copilot.tools.capability.${call.capability}`)} ·{" "}
                  {call.ok ? t("copilot.tools.ok") : t("copilot.tools.failed", { code: call.error_code ?? "" })}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <details className="copilot-details">
        <summary>{t("copilot.meta.trace")}</summary>
        <ul>
          <li>
            <span className="copilot-details-label">{t("copilot.meta.correlationLabel")}</span>
            <code className="copilot-trace-id">{turn.correlation_id}</code>
          </li>
          {turn.context_version ? (
            <li>
              <span className="copilot-details-label">{t("copilot.meta.contextLabel")}</span>
              <code>{turn.context_version}</code>
            </li>
          ) : null}
        </ul>
      </details>
    </div>
  );
}

/** One reply: its text, the products it names, its plan, and what it rests on; who wrote it and when, under it. */
function Reply({ turn }: { turn: AssistantTurn }) {
  const { t } = useTranslation();
  const products = productsOf(turn);
  const declined = turn.status === ASSISTANT_STATUS.Refused || turn.status === ASSISTANT_STATUS.Unsupported;
  return (
    <li className="copilot-row" data-kind="reply" data-status={turn.status}>
      <Avatar />
      <div className="copilot-stack">
        <div className="copilot-bubble">
          {declined ? (
            <p className="copilot-outcome">
              <span className="copilot-outcome-pill">{t(`copilot.status.${turn.status}`)}</span>
              {turn.outcome_code ? <span>{codeLabel("copilot.outcome", turn.outcome_code)}</span> : null}
            </p>
          ) : null}
          <p className="copilot-text">{turn.text}</p>
          {products.length ? (
            <div className="copilot-products" role="group" aria-label={t("copilot.products")}>
              {products.map((sku) => (
                <SkuChip key={sku} sku={sku} />
              ))}
            </div>
          ) : null}
          {turn.proposal ? <CopilotProposal proposal={turn.proposal} /> : null}
          <ReplyDetails turn={turn} />
        </div>
        <p className="copilot-meta" title={t("copilot.meta.correlation", { id: turn.correlation_id })}>
          <span className="copilot-meta-source" data-source={turn.source}>
            {sourceLabel(turn)}
          </span>
          <time dateTime={turn.created_at}>{clock(turn.created_at)}</time>
          {turn.context_version ? <span>{t("copilot.meta.context", { version: turn.context_version })}</span> : null}
        </p>
      </div>
    </li>
  );
}

/** Why a message got no reply: what happened, its HTTP status and code, the correlation id to look it up by, and a retry. */
function Failure({ failure, at, onRetry, busy }: { failure: AssistantFailure; at: string; onRetry: () => void; busy: boolean }) {
  const { t } = useTranslation();
  const stale = failure.code === ASSISTANT_ERROR.StaleContext;
  const known = codeLabel("copilot.error", failure.code, "");
  return (
    <li className="copilot-row" data-kind="error" role="alert">
      <Avatar alert />
      <div className="copilot-stack">
        <div className="copilot-bubble">
          <p className="copilot-outcome">
            <span className="copilot-outcome-pill">{t("copilot.error.title")}</span>
          </p>
          <p className="copilot-text">{known || t("copilot.error.request_failed")}</p>
          {failure.message && failure.message !== known ? <p className="copilot-error-detail">{failure.message}</p> : null}
          <p className="copilot-error-meta">
            <span>
              {failure.status
                ? t("copilot.error.meta", { status: failure.status, code: failure.code })
                : t("copilot.error.metaNoStatus", { code: failure.code })}
            </span>
            {failure.correlation_id ? (
              <span className="copilot-meta-id" title={failure.correlation_id}>
                {t("copilot.meta.correlation", { id: failure.correlation_id })}
              </span>
            ) : null}
          </p>
          {failure.retryable || stale ? (
            <button type="button" className="copilot-retry" disabled={busy} onClick={onRetry}>
              <RetryIcon className="h-3.5 w-3.5" />
              {stale ? t("copilot.error.askAgain") : t("copilot.error.retry")}
            </button>
          ) : null}
        </div>
        <p className="copilot-meta">
          <time dateTime={at}>{clock(at)}</time>
        </p>
      </div>
    </li>
  );
}

/** The conversation, oldest first. */
export function CopilotMessages({
  messages,
  busy,
  onRetry,
}: {
  messages: CopilotMessage[];
  busy: boolean;
  onRetry: (messageId: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <>
      {messages.map((message) => {
        if (message.kind === "user") {
          return (
            <li key={message.id} className="copilot-row" data-kind="user">
              <div className="copilot-bubble">
                <span className="sr-only">{t("copilot.you")}: </span>
                <p className="copilot-text">{message.request.text}</p>
              </div>
            </li>
          );
        }
        if (message.kind === "reply") return <Reply key={message.id} turn={message.turn} />;
        return (
          <Failure
            key={message.id}
            failure={message.failure}
            at={message.at}
            busy={busy}
            onRetry={() => onRetry(message.messageId)}
          />
        );
      })}
    </>
  );
}
