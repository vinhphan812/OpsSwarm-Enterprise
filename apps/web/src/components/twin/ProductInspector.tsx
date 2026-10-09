import { Button, Card, CardBody, CardHeader, Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { issueReason } from "@/core/api/validate";
import { inspectProduct } from "@/core/twin/twinIssues";
import { INSPECTION_KIND } from "@/enums/twin.enum";
import { useTwinIssues } from "@/hooks/twinIssues.hook";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

/** Twin figures of the selected product. Click an item on a shelf, or open `/?product=P001`. */
export function ProductInspector() {
  const { t } = useTranslation();
  const productId = useUiStore((state) => state.selectedEntityId);
  const select = useUiStore((state) => state.select);
  const live = useTwinStore((state) => state.live);
  const issues = useTwinIssues();
  if (!productId) return null;

  const inspection = inspectProduct(productId, live, issues);

  return (
    <Card className="absolute bottom-16 left-4 w-72" aria-label={t("inspector.label", { sku: productId })}>
      <CardHeader className="flex items-center justify-between pb-0">
        <h2 className="text-base font-semibold">{productId}</h2>
        <Button size="sm" variant="light" className="cursor-pointer" onPress={() => select(null)}>
          {t("inspector.close")}
        </Button>
      </CardHeader>
      <CardBody className="text-sm">
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
        {inspection.kind === INSPECTION_KIND.Ok ? (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
            <dt className="text-default-500">{t("inspector.shelfSlot")}</dt>
            <dd>
              {inspection.product.shelf_id} / {inspection.product.slot_id}
            </dd>
            <dt className="text-default-500">{t("inspector.facings")}</dt>
            <dd>{inspection.product.facings}</dd>
            <dt className="text-default-500">{t("inspector.onShelf")}</dt>
            <dd>{inspection.product.shelf_quantity}</dd>
            <dt className="text-default-500">{t("inspector.backroom")}</dt>
            <dd>{inspection.product.backroom_quantity}</dd>
            <dt className="text-default-500">{t("inspector.version")}</dt>
            <dd>{inspection.product.version}</dd>
          </dl>
        ) : null}
      </CardBody>
    </Card>
  );
}
