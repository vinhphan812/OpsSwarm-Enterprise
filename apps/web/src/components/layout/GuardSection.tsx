import { useTranslation } from "react-i18next";
import { GuardCard } from "@/components/twin/GuardCard";
import { useGuardStore } from "@/state/guard.store";

/** The guard's last answer in the Operations lens, so it stays in view after its run closes. Nothing before the first approval. */
export function GuardSection() {
  const { t } = useTranslation();
  const last = useGuardStore((state) => state.last);
  if (!last) return null;
  return (
    <section className="activity-section">
      <div className="activity-section-head">
        <h2 className="activity-section-title">{t("guard.section")}</h2>
      </div>
      <GuardCard review={last} />
    </section>
  );
}
