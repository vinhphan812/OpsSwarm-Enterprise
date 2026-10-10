import { Button, Chip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { InfoIcon } from "@/components/icons";
import { fixtureStock } from "@/core/twin/fixtureStock";
import { format } from "@/core/utils/format";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import { useActiveState } from "@/hooks/activeTwin.hook";
import { useUiStore } from "@/state/ui.store";
import { Figures, InspectorCard } from "./InspectorCard";

const STATE_COLOR: Record<StockState, "success" | "warning" | "danger"> = {
  [STOCK_STATE.Ok]: "success",
  [STOCK_STATE.Low]: "warning",
  [STOCK_STATE.Out]: "danger",
};

type FixtureInspectorProps = {
  fixtureId: string;
  /** Merchandise group or kind, already translated. */
  title: string;
};

/**
 * What the twin has on the selected shelf or display equipment: totals, then each
 * product with its stock state. Every figure comes from the state on screen (Live, or
 * the simulation's proposal). A product's
 * SKU selects it; its info button opens its details dialog.
 */
export function FixtureInspector({ fixtureId, title }: FixtureInspectorProps) {
  const { t } = useTranslation();
  const live = useActiveState();
  const select = useUiStore((state) => state.select);
  const showDetails = useUiStore((state) => state.showDetails);
  const stock = live ? fixtureStock(fixtureId, live) : null;

  return (
    <InspectorCard title={fixtureId} subtitle={title} label={t("inspector.fixtureLabel", { title, id: fixtureId })}>
      {!live ? <p>{t("twin.loading")}</p> : null}
      {stock ? (
        <div className="flex flex-col gap-3">
          <Figures
            rows={[
              [t("inspector.products"), format.count(stock.products.length)],
              [t("inspector.slotsUsed"), `${stock.products.length} / ${stock.slotCount}`],
              [t("inspector.unitsOnShelf"), format.count(stock.unitsOnShelf)],
              [t("inspector.unitsInBackroom"), format.count(stock.unitsInBackroom)],
              [t("inspector.lowStock"), format.count(stock.lowCount)],
              [t("inspector.outOfStock"), format.count(stock.outCount)],
            ]}
          />
          <section aria-label={t("inspector.productList", { id: fixtureId })}>
            {stock.products.length === 0 ? (
              <p className="text-default-500">{t("inspector.empty")}</p>
            ) : (
              <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
                {stock.products.map((product) => (
                  <li key={product.productId} className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="light"
                      disableRipple
                      aria-label={t("inspector.selectProduct", { sku: product.productId })}
                      className="h-auto min-w-0 cursor-pointer px-1 font-medium underline"
                      onPress={() => select(product.productId, ENTITY_TYPE.Product)}
                    >
                      {product.productId}
                    </Button>
                    <span className="min-w-0 flex-1 truncate text-xs text-default-500">
                      {t("inspector.productLine", {
                        slot: product.slotId,
                        shelf: product.shelfQuantity,
                        facings: product.facings,
                      })}
                    </span>
                    <Chip size="sm" variant="flat" color={STATE_COLOR[product.state]}>
                      {t(`inspector.state.${product.state}`)}
                    </Chip>
                    <Button
                      isIconOnly
                      size="sm"
                      variant="light"
                      radius="sm"
                      aria-label={t("inspector.detailsOf", { sku: product.productId })}
                      title={t("inspector.detailsOf", { sku: product.productId })}
                      className="h-6 w-6 min-w-0 shrink-0 cursor-pointer text-default-500"
                      onPress={() => showDetails(product.productId)}
                    >
                      <InfoIcon className="h-4 w-4" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      ) : null}
    </InspectorCard>
  );
}
