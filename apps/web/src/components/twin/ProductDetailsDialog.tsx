import { Button, Chip, Modal, ModalBody, ModalContent, ModalFooter, ModalHeader } from "@heroui/react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AlertIcon, PromotionIcon } from "@/components/icons";
import { discountOf } from "@/components/promotions/PromotionCard";
import { stockState } from "@/core/twin/fixtureStock";
import { format } from "@/core/utils/format";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import { usePromotions } from "@/hooks/commerce.hook";
import { useActiveState, useShownAnomalies } from "@/hooks/activeTwin.hook";
import { useMovedFrom, useQuantityChange } from "@/hooks/recentChanges.hook";
import { useTwinIssues, useUnitsNotShown } from "@/hooks/twinIssues.hook";
import { isInconsistentTransfer } from "@/core/twin/twinIssues";
import { issueReason } from "@/core/api/validate";
import { QuantityDeltas } from "./ProductInspector";
import { anomaliesOf } from "@/state/anomaly.store";
import { usePanelStore } from "@/state/panel.store";
import { useUiStore } from "@/state/ui.store";
import type { Anomaly } from "@/types/anomaly.type";
import type { ProductInventory } from "@/types/twin.type";
import "@/components/commerce/commerce.css";
import "./ProductDetailsDialog.css";

const STATE_COLOR: Record<StockState, "success" | "warning" | "danger"> = {
  [STOCK_STATE.Ok]: "success",
  [STOCK_STATE.Low]: "warning",
  [STOCK_STATE.Out]: "danger",
};

/** One section of the dialog: a small heading, an optional count, then its content. */
function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="details-section" aria-label={title}>
      <h3 className="activity-section-title">
        {title}
        {count === undefined ? null : <span className="activity-count">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

/**
 * Stock tiles: units on the shelf against facings (with how full the front is, and how
 * many units the facings cannot hold), backroom, facings, version.
 */
function StockTiles({ product, state }: { product: ProductInventory; state: StockState }) {
  const { t } = useTranslation();
  const notShown = useUnitsNotShown(product.sku);
  const fill = product.facings ? Math.min(1, product.shelf_quantity / product.facings) : 0;
  return (
    <dl className="details-tiles">
      <div className="details-tile details-tile-wide" data-state={state}>
        <dt>{t("inspector.onShelf")}</dt>
        <dd>
          {format.count(product.shelf_quantity)}
          <small>{t("productDetails.ofFacings", { facings: product.facings })}</small>
          {notShown ? <small>· {t("inspector.notShown", { count: notShown })}</small> : null}
        </dd>
        <span className="details-fill" aria-hidden>
          <span style={{ width: `${fill * 100}%` }} />
        </span>
      </div>
      <div className="details-tile">
        <dt>{t("inspector.backroom")}</dt>
        <dd>{format.count(product.backroom_quantity)}</dd>
      </div>
      <div className="details-tile">
        <dt>{t("inspector.facings")}</dt>
        <dd>{format.count(product.facings)}</dd>
      </div>
      <div className="details-tile">
        <dt>{t("inspector.version")}</dt>
        <dd>{product.version}</dd>
      </div>
    </dl>
  );
}

/** Open anomalies as rows marked by severity. One read from an older twin state says so. */
function AnomalyRows({ anomalies, contextVersion }: { anomalies: Anomaly[]; contextVersion: string }) {
  const { t } = useTranslation();
  if (anomalies.length === 0) return <p className="details-empty">{t("productDetails.noAnomalies")}</p>;
  return (
    <ul className="details-anomalies" aria-label={t("anomaly.list")}>
      {anomalies.map((anomaly) => (
        <li key={anomaly.anomaly_id} className="details-anomaly" data-severity={anomaly.severity}>
          <AlertIcon className="details-anomaly-icon" />
          <span className="details-anomaly-kind">{t(`anomaly.kind.${anomaly.kind}`)}</span>
          <span className="details-anomaly-severity">{t(`anomaly.severity.${anomaly.severity}`)}</span>
          <span className="details-anomaly-meta">
            {t("anomaly.detected", { time: format.hour(anomaly.detected_at) })}
            {anomaly.context_version !== contextVersion ? ` · ${t("anomaly.olderState")}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * The promotions a product is in, from `GET /promotions`. Its own component so the
 * read happens only while the dialog is open, not when the page loads.
 */
function ProductPromotions({ sku, onView }: { sku: string; onView: (promotionId: string) => void }) {
  const { t } = useTranslation();
  const { promotions } = usePromotions();
  const inPromotions = promotions.filter((promotion) => promotion.skus.includes(sku));

  return (
    <Section title={t("productDetails.promotions")} count={inPromotions.length}>
      {inPromotions.length ? (
        <ul className="details-promotions">
          {inPromotions.map((promotion) => (
            <li key={promotion.id}>
              <button
                type="button"
                className="promotion-card details-promotion"
                data-status={promotion.status}
                aria-label={t("productDetails.viewPromotion", { name: promotion.name })}
                onClick={() => onView(promotion.id)}
              >
                <span className="promotion-card-head">
                  <span className="promotion-status">
                    <span className="promotion-status-dot" aria-hidden />
                    {t(`promotions.status.${promotion.status}`)}
                  </span>
                  <span className="promotion-kind">
                    {t(`promotions.kind.${promotion.kind}`, { value: discountOf(promotion) })}
                  </span>
                </span>
                <span className="promotion-name">{promotion.name}</span>
                <span className="details-promotion-foot">
                  <span className="promotion-meta">
                    {t("promotions.dates", { start: format.day(promotion.starts_at), end: format.day(promotion.ends_at) })}{" "}
                    · {t("promotions.skus", { count: promotion.skus.length })}
                  </span>
                  <span className="details-promotion-go" aria-hidden>
                    {t("productDetails.view")} →
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="details-empty">
          <PromotionIcon className="h-4 w-4" />
          {t("productDetails.noPromotions")}
        </p>
      )}
    </Section>
  );
}

/**
 * Everything about one product in a centered dialog: its stock in the twin, its open
 * anomalies, and the promotions it is in. Opened by **Details** on the product card or
 * on a shelf's product list (`showDetails`). Every figure comes from the state on screen, the
 * anomaly store, and `GET /promotions`. A promotion opens the Promotions lens on it.
 */
export function ProductDetailsDialog() {
  const { t } = useTranslation();
  const sku = useUiStore((state) => state.detailsSku);
  const showDetails = useUiStore((state) => state.showDetails);
  const select = useUiStore((state) => state.select);
  const focusPromotion = useUiStore((state) => state.focusPromotion);
  const openPanel = usePanelStore((state) => state.setOpen);
  const live = useActiveState();
  const allAnomalies = useShownAnomalies();
  const movedFrom = useMovedFrom(sku);
  const quantityChange = useQuantityChange(sku);
  const transfer = useTwinIssues().find((issue) => issue.sku === sku && isInconsistentTransfer(issue));

  const product = sku ? live?.products.find((candidate) => candidate.sku === sku) : undefined;
  const anomalies = sku ? anomaliesOf(allAnomalies, sku) : [];
  const close = () => showDetails(null);
  /** Opens the Promotions lens on one promotion, with this product selected so it stands out there and in 3D. */
  const viewPromotion = (promotionId: string) => {
    if (product) select(product.sku, ENTITY_TYPE.Product);
    focusPromotion(promotionId);
    openPanel(true);
    close();
  };
  const state = product ? stockState({ facings: product.facings, shelfQuantity: product.shelf_quantity }) : null;

  return (
    <Modal
      isOpen={sku !== null}
      onClose={close}
      size="2xl"
      placement="center"
      backdrop="blur"
      scrollBehavior="inside"
      classNames={{ base: "max-h-[min(720px,90dvh)]" }}
    >
      <ModalContent aria-label={sku ? t("inspector.detailsOf", { sku }) : undefined}>
        {sku ? (
          <>
            <ModalHeader className="flex flex-col gap-1 pb-2">
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-xl font-semibold">{t("productDetails.title", { sku })}</span>
                {state ? (
                  <Chip size="sm" variant="flat" color={STATE_COLOR[state]}>
                    {t(`inspector.state.${state}`)}
                  </Chip>
                ) : null}
                {product && movedFrom ? (
                  <Chip size="sm" variant="flat" color="primary">
                    {t("inspector.movedFrom", { slot: movedFrom })}
                  </Chip>
                ) : null}
                {product && transfer ? (
                  <Chip size="sm" variant="flat" color="warning" title={issueReason(transfer)}>
                    {t("inspector.inconsistentTransfer")}
                  </Chip>
                ) : null}
                {anomalies.length ? (
                  <Chip size="sm" variant="flat" color="danger">
                    {t("productDetails.anomalyCount", { count: anomalies.length })}
                  </Chip>
                ) : null}
              </span>
              {product && quantityChange ? <QuantityDeltas change={quantityChange} /> : null}
              {product && live ? (
                <span className="text-xs font-normal text-ink-muted">
                  {t("productDetails.subtitle", {
                    shelf: product.shelf_id,
                    slot: product.slot_id,
                    contextVersion: live.context_version,
                  })}
                </span>
              ) : null}
            </ModalHeader>
            <ModalBody className="gap-5 pb-2 text-sm">
              {product && live && state ? (
                <>
                  <Section title={t("productDetails.twin")}>
                    <StockTiles product={product} state={state} />
                  </Section>
                  <Section title={t("productDetails.anomalies")} count={anomalies.length}>
                    <AnomalyRows anomalies={anomalies} contextVersion={live.context_version} />
                  </Section>
                </>
              ) : (
                <Chip color="danger" variant="flat">
                  {t("inspector.missing")}
                </Chip>
              )}
              <ProductPromotions sku={sku} onView={viewPromotion} />
            </ModalBody>
            <ModalFooter className="border-t border-line">
              <Button size="sm" radius="sm" variant="light" className="ml-auto cursor-pointer" onPress={close}>
                {t("productDetails.close")}
              </Button>
              {product ? (
                <Button
                  size="sm"
                  radius="sm"
                  className="cursor-pointer bg-accent font-semibold text-canvas data-[hover=true]:bg-accent-hover"
                  onPress={() => {
                    select(sku, ENTITY_TYPE.Product);
                    close();
                  }}
                >
                  {t("productDetails.showInStore")}
                </Button>
              ) : null}
            </ModalFooter>
          </>
        ) : null}
      </ModalContent>
    </Modal>
  );
}
