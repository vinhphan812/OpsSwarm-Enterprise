import i18n from "@/i18n";
import { ApiError, type ErrorDetail } from "./client";

/** A read of apps/api that failed, with what the user needs to report it. */
export type ReadFailure = {
  /** The route read, such as `GET /revenue`. */
  route: string;
  /** HTTP status; 0 when apps/api was not reached. */
  status: number;
  /** apps/api's error code (`analytics_unavailable`, `validation_error`, …) or the FE's own. */
  code: string;
  message: string;
  correlationId: string | null;
  details: ErrorDetail[];
  /** When it failed, in ms since the epoch. */
  at: number;
};

/** `error` from a read of `route`, as the failure card shows it. Never a stack trace. */
export function readFailureOf(error: unknown, route: string, at = Date.now()): ReadFailure {
  if (error instanceof ApiError) {
    return { route, status: error.status, code: error.code, message: error.message, correlationId: error.correlationId, details: error.details, at };
  }
  const message = error instanceof Error ? error.message : i18n.t("errors.unknown");
  return { route, status: 0, code: "request_failed", message, correlationId: null, details: [], at };
}
