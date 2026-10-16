import { AnimatePresence, motion } from "framer-motion";
import { useTranslation } from "react-i18next";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import type { ActivityEntry } from "@/types/agent.type";

/** HH:MM:SS of an ISO timestamp, in the viewer's time zone. */
export function clock(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour12: false });
}

/** The SKU of a timeline entry, as a button that selects that product. */
export function SkuChip({ sku }: { sku: string }) {
  const { t } = useTranslation();
  const select = useUiStore((state) => state.select);
  const selected = useUiStore(selectedProductId);
  return (
    <button
      type="button"
      className="activity-sku"
      aria-label={t("activity.selectProduct", { sku })}
      aria-pressed={selected === sku}
      onClick={() => select(sku, ENTITY_TYPE.Product)}
    >
      {sku}
    </button>
  );
}

/** Timeline entries as log lines (time · stage · SKU · summary), in the order given. */
export function ActivityLog({ entries, label }: { entries: ActivityEntry[]; label: string }) {
  return (
    <ol className="activity-list" aria-label={label}>
      <AnimatePresence initial={false}>
        {entries.map((entry) => (
          <motion.li
            key={entry.id}
            layout
            className="activity-item"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
          >
            <div className="activity-meta">
              <time dateTime={entry.ts}>{clock(entry.ts)}</time>
              <span className="activity-stage">{entry.stage}</span>
              {entry.sku ? <SkuChip sku={entry.sku} /> : null}
            </div>
            <p className="activity-summary">{entry.summary}</p>
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}
