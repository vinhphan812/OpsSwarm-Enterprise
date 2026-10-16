import { AnimatePresence, motion } from "framer-motion";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { IMPACT_TOAST_MS, IMPACT_TOAST_ROWS } from "@/constants/app.constant";
import { useVerifiedImpact } from "@/hooks/aiImpact.hook";
import { useImpactStore } from "@/state/impact.store";
import { CompareButton, ImpactRowView, VerifierStatus } from "./AiImpactCard";

/**
 * The projected impact over the 3D view, for `IMPACT_TOAST_MS`, the moment the agent's run of
 * an executed approval reaches VERIFY, with the verifier's status apart. Once per simulation;
 * the card stays in the Operations lens.
 */
export function AiImpactToast() {
  const { t } = useTranslation();
  const verified = useVerifiedImpact();
  const impact = verified?.impact ?? null;
  const shownFor = useImpactStore((state) => state.toastShownFor);
  const markToastShown = useImpactStore((state) => state.markToastShown);
  const visible = impact !== null && shownFor !== impact.simulation_id;

  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(() => markToastShown(impact.simulation_id), IMPACT_TOAST_MS);
    return () => clearTimeout(timer);
  }, [visible, impact, markToastShown]);

  return (
    <AnimatePresence>
      {visible ? (
        <motion.div
          key={impact.simulation_id}
          className="impact-toast"
          data-testid="ai-impact-toast"
          role="status"
          initial={{ opacity: 0, y: 12, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
        >
          <div className="impact-head">
            <span className="impact-title">{t("impact.title")}</span>
            <span className="impact-plan">{t("impact.plan", { id: impact.candidate_id })}</span>
            <button
              type="button"
              className="impact-toast-close"
              aria-label={t("impact.dismiss")}
              onClick={() => markToastShown(impact.simulation_id)}
            >
              ×
            </button>
          </div>
          <ul className="impact-rows">
            {impact.rows.slice(0, IMPACT_TOAST_ROWS).map((row) => (
              <ImpactRowView key={row.name} row={row} />
            ))}
          </ul>
          <div className="impact-foot">
            <span className="impact-note">{t("impact.note", { version: impact.evaluator_version })}</span>
            <CompareButton />
          </div>
          <VerifierStatus verify={verified!.verify} />
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
