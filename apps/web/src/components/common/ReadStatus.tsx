import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { AlertIcon, RetryIcon } from "@/components/icons";
import { clock } from "@/components/layout/ActivityLog";
import { INVALID_RESPONSE } from "@/core/api/client";
import type { ReadFailure } from "@/core/api/readFailure";
import { isDemoMode } from "@/core/twin/demoMode";

/** Where a figure comes from: the demo's synthetic data, or apps/api's Live data. */
export function ReadSource() {
  const { t } = useTranslation();
  const demo = isDemoMode();
  return (
    <span className="read-source" data-source={demo ? "demo" : "live"} title={t(demo ? "read.source.demoHint" : "read.source.liveHint")}>
      {t(demo ? "read.source.demo" : "read.source.live")}
    </span>
  );
}

/** The `read.failure` text for a failure's code; null when it has none, and the served message shows. */
function explanationKey(failure: ReadFailure): string | null {
  switch (failure.code) {
    case "analytics_unavailable":
      return "read.failure.analyticsUnavailable";
    case "validation_error":
      return "read.failure.validation";
    case INVALID_RESPONSE:
      return "read.failure.invalidResponse";
    case "network_error":
      return "read.failure.network";
    default:
      return failure.status === 404 && failure.code === "http_error" ? "read.failure.notDeployed" : null;
  }
}

/** What a failure means for the user, by its code; the served message when the code is unknown. */
function explanation(failure: ReadFailure, t: ReturnType<typeof useTranslation>["t"]): string {
  const key = explanationKey(failure);
  // A key picked at run time: typed `t` keys would instantiate the whole message tree here.
  return key ? String(t(key as never, { message: failure.message } as never)) : failure.message;
}

/**
 * A failed read, in place of its figures until it reads again: what failed and why, its HTTP
 * status and code, the route, where the data comes from, when, and the correlation id to find
 * it in the apps/api logs. The fields apps/api found invalid are listed; never a stack trace.
 */
export function ReadFailureCard({ title, failure, onRetry }: { title: string; failure: ReadFailure; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="read-card" data-kind="failed" role="alert" aria-label={title}>
      <h2 className="read-card-title">
        <AlertIcon className="h-4 w-4 shrink-0" />
        {title}
      </h2>
      <p>{explanation(failure, t)}</p>
      {failure.details.length ? (
        <ul className="read-card-details" aria-label={t("read.failure.details")}>
          {failure.details.map((detail) => (
            <li key={`${detail.field}:${detail.message}`}>
              <code>{detail.field}</code> {detail.message}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="read-card-meta">
        <span>
          {failure.status
            ? t("read.failure.status", { status: failure.status, code: failure.code })
            : t("read.failure.code", { code: failure.code })}
        </span>
        <span>{failure.route}</span>
        <ReadSource />
        <time dateTime={new Date(failure.at).toISOString()}>{clock(new Date(failure.at).toISOString())}</time>
        {failure.correlationId ? (
          <span className="read-card-id" title={failure.correlationId}>
            {t("read.failure.correlation", { id: failure.correlationId })}
          </span>
        ) : null}
      </p>
      <Button
        size="sm"
        variant="bordered"
        className="self-start border-white/15 text-[var(--color-ink)]"
        startContent={<RetryIcon className="h-3.5 w-3.5" />}
        onPress={onRetry}
      >
        {t("read.retry")}
      </Button>
    </section>
  );
}

/** A read that answered with nothing in it: says so plainly, with a retry, instead of figures of 0. */
export function ReadEmptyCard({ title, text, onRetry }: { title: string; text: string; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <section className="read-card" data-kind="empty" role="status" aria-label={title}>
      <h2 className="read-card-title">
        <AlertIcon className="h-4 w-4 shrink-0" />
        {title}
      </h2>
      <p>{text}</p>
      <p className="read-card-meta">
        <ReadSource />
      </p>
      <Button
        size="sm"
        variant="bordered"
        className="self-start border-white/15 text-[var(--color-ink)]"
        startContent={<RetryIcon className="h-3.5 w-3.5" />}
        onPress={onRetry}
      >
        {t("read.retry")}
      </Button>
    </section>
  );
}

/** A read on its way: no figures yet, rather than zeros. */
export function ReadingNotice({ route }: { route: string }) {
  const { t } = useTranslation();
  return (
    <p className="read-loading" role="status">
      {t("read.loading", { route })}
    </p>
  );
}
