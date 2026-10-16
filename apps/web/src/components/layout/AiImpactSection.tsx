import { useTranslation } from "react-i18next";
import { AiImpactCard } from "@/components/twin/AiImpactCard";
import { useVerifiedImpact } from "@/hooks/aiImpact.hook";

/** The projected impact in the Operations lens, once the agent's run has reached VERIFY. Nothing before. */
export function AiImpactSection() {
  const { t } = useTranslation();
  const verified = useVerifiedImpact();
  if (!verified) return null;
  return (
    <section className="activity-section impact-section">
      <div className="activity-section-head">
        <h2 className="activity-section-title">{t("impact.section")}</h2>
      </div>
      <AiImpactCard impact={verified.impact} verify={verified.verify} />
    </section>
  );
}
