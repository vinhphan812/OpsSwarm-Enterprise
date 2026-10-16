import { useTranslation } from "react-i18next";
import { aiChangeCount, type AiChanges } from "@/core/twin/aiChanges";
import { useUiStore } from "@/state/ui.store";

type Row = { sku: string; detail: string };

/**
 * The AI CHANGES list: what a change does to the store, grouped as Moved, Facings and
 * Replenished, each value as one of the two states has it. Picking a row selects the
 * product, and the camera flies to it. Nothing when there is no change.
 */
export function AiChangesList({ changes }: { changes: AiChanges | null }) {
  const { t } = useTranslation();
  const select = useUiStore((state) => state.select);
  if (!changes) return null;
  const count = aiChangeCount(changes);
  if (!count) return null;

  const groups: { key: keyof AiChanges; rows: Row[] }[] = [
    { key: "moved", rows: changes.moved.map(({ sku, from, to }) => ({ sku, detail: `${from} → ${to}` })) },
    { key: "facings", rows: changes.facings.map(({ sku, before, after }) => ({ sku, detail: `${before} → ${after}` })) },
    {
      key: "replenished",
      rows: changes.replenished.map(({ sku, before, after }) => ({ sku, detail: `${before} → ${after}` })),
    },
  ];

  return (
    <div className="ai-changes" role="region" aria-label={t("aiChanges.title")}>
      <span className="ai-changes-title">
        {t("aiChanges.title")}
        <span className="ai-changes-count">{t("simulation.changes.count", { count })}</span>
      </span>
      {groups.map(({ key, rows }) =>
        rows.length ? (
          <div key={key} className="ai-changes-group">
            <span className="ai-changes-kind">{t(`aiChanges.${key}`)}</span>
            <ul aria-label={t(`aiChanges.${key}`)}>
              {rows.map(({ sku, detail }) => (
                <li key={sku}>
                  <button
                    type="button"
                    aria-label={t("aiChanges.row", { sku, kind: t(`aiChanges.${key}`), detail })}
                    onClick={() => select(sku)}
                  >
                    <span className="ai-changes-sku">{sku}</span>
                    <span className="ai-changes-detail">{detail}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null,
      )}
    </div>
  );
}
