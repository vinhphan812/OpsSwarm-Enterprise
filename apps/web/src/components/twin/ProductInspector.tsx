import { Button, Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { issueReason } from "@/core/api/validate";
import { inspectProduct } from "@/core/twin/twinIssues";
import { INSPECTION_KIND } from "@/enums/twin.enum";
import { useTwinIssues } from "@/hooks/twinIssues.hook";
import { anomaliesOf, useAnomalyStore } from "@/state/anomaly.store";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";
import { AnomalyList } from "./AnomalyList";
import { Figures, InspectorCard } from "./InspectorCard";

/**
 * Twin figures and open anomalies of the selected product. Click an item on a shelf, or
 * open `/?product=P001`. **Details** opens the product's dialog.
 */
export function ProductInspector({ productId }: { productId: string }) {
  const { t } = useTranslation();
  const live = useTwinStore((state) => state.live);
  const issues = useTwinIssues();
  const inspection = inspectProduct(productId, live, issues);
  const anomalies = anomaliesOf(useAnomalyStore((state) => state.anomalies), productId);
  const showDetails = useUiStore((state) => state.showDetails);

  return (
    <InspectorCard title={productId} label={t("inspector.label", { sku: productId })}>
      {inspection.kind === INSPECTION_KIND.Loading ? <p>{t("twin.loading")}</p> : null}
      {inspection.kind === INSPECTION_KIND.Missing ? (
        <Chip color="danger" variant="flat">
          {t("inspector.missing")}
        </Chip>
      ) : null}
      {inspection.kind === INSPECTION_KIND.Invalid ? (
        <div className="flex flex-col gap-2">
          <Chip color="warning" variant="flat">
            {t("inspector.invalid")}
          </Chip>
          <p>{issueReason(inspection.issue)}</p>
        </div>
      ) : null}
      {inspection.kind === INSPECTION_KIND.Ok && live ? (
        <AnomalyList anomalies={anomalies} contextVersion={live.context_version} />
      ) : null}
      {inspection.kind === INSPECTION_KIND.Ok ? (
        <Figures
          rows={[
            [t("inspector.shelfSlot"), `${inspection.product.shelf_id} / ${inspection.product.slot_id}`],
            [t("inspector.facings"), inspection.product.facings],
            [t("inspector.onShelf"), inspection.product.shelf_quantity],
            [t("inspector.backroom"), inspection.product.backroom_quantity],
            [t("inspector.version"), inspection.product.version],
          ]}
        />
      ) : null}
      {inspection.kind === INSPECTION_KIND.Ok ? (
        <Button
          size="sm"
          radius="sm"
          variant="flat"
          className="mt-3 w-full cursor-pointer font-semibold"
          onPress={() => showDetails(productId)}
        >
          {t("inspector.details")}
        </Button>
      ) : null}
    </InspectorCard>
  );
}
