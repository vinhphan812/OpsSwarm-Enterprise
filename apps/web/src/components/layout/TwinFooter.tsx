import { useTranslation } from "react-i18next";
import { buildLabel } from "@/core/app/buildInfo";
import { useTwinStore } from "@/state/twin.store";

/** The services RetailTwin runs on, as one line. */
export const TECH_STACK = ["Gemini on Vertex AI", "Cloud Run", "Firestore", "BigQuery"] as const;

/**
 * A low line under the 3D view: the Google Cloud services behind RetailTwin, the Live Twin's
 * `context_version` as served (it moves after each execution), and the build.
 */
export function TwinFooter() {
  const { t } = useTranslation();
  const contextVersion = useTwinStore((state) => state.live?.context_version ?? null);
  const build = buildLabel();
  return (
    <footer className="twin-footer">
      <span className="twin-footer-stack">{TECH_STACK.join(" · ")}</span>
      <span className="twin-footer-meta">
        <span data-testid="footer-context" title={t("footer.contextHint")}>
          {t("footer.context", { version: contextVersion ?? "—" })}
        </span>
        <span data-testid="footer-build">{t("footer.build", { build: build ?? t("footer.devBuild") })}</span>
      </span>
    </footer>
  );
}
