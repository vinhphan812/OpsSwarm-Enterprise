import { addToast } from "@heroui/react";
import i18n from "@/i18n";

/** Readable message for anything thrown or rejected. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return typeof error === "string" && error ? error : i18n.t("errors.unknown");
}

/** App toasts, so screens do not depend on the UI kit's toast API directly. */
export const notify = {
  error: (title: string, error?: unknown) =>
    addToast({ title, description: error === undefined ? undefined : errorMessage(error), color: "danger" }),
  warning: (title: string, description?: string) => addToast({ title, description, color: "warning" }),
  /** Something new worth a look, in the simulation accent. */
  info: (title: string, description?: string) => addToast({ title, description, color: "secondary" }),
  success: (title: string, description?: string) => addToast({ title, description, color: "success" }),
};
