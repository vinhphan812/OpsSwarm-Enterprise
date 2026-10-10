import { Button } from "@heroui/react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { STORE_STATUS_ROWS } from "@/constants/app.constant";
import { defaultClient } from "@/core/api/client";
import { isDemoMode } from "@/core/twin/demoMode";
import { productRows } from "@/core/twin/productRows";
import { format } from "@/core/utils/format";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import type { RetailTwinClient } from "@/types/api.type";
import { useStoreStatus } from "@/hooks/storeStatus.hook";
import { selectedProductId, useUiStore } from "@/state/ui.store";
import { ProductsDialog } from "./ProductsDialog";
import "./StoreStatus.css";

type StoreStatusProps = {
  /**
   * Reads health and SKU lookups; apps/api by default. Under `?twin=demo` there is none:
   * no health line, and a SKU is looked up in the demo store the scene already has.
   */
  client?: RetailTwinClient;
};

export function StoreStatus({ client = isDemoMode() ? undefined : defaultClient }: StoreStatusProps) {
  const { t } = useTranslation();
  const { health, store, loading, sku, setSku, inventory, lookupPending, onLookup } = useStoreStatus(client);
  const select = useUiStore((state) => state.select);
  const selected = useUiStore(selectedProductId);
  const [dialogOpen, setDialogOpen] = useState(false);

  const rows = useMemo(() => productRows(store?.products ?? []), [store]);
  const shown = rows.slice(0, STORE_STATUS_ROWS);
  const count = (state: StockState) => rows.filter((row) => row.state === state).length;

  return (
    <section className="store-status">
      <h2>{t("storeStatus.title")}</h2>
      <p className="store-status-note">{t("storeStatus.note")}</p>

      {loading ? <p className="store-status-muted">{t("storeStatus.loading")}</p> : null}
      {health ? (
        <p className="store-status-health">
          {t("storeStatus.health", { status: health.status, environment: health.environment, storeId: health.store_id })}
        </p>
      ) : null}

      {store ? (
        <>
          <h2 className="store-status-store">{store.store_id}</h2>
          <p className="store-status-muted">{t("storeStatus.context", { contextVersion: store.context_version, version: store.version })}</p>

          <dl className="store-status-stats">
            <div>
              <dt>{t("storeStatus.products")}</dt>
              <dd>{format.count(rows.length)}</dd>
            </div>
            <div data-state={STOCK_STATE.Low}>
              <dt>{t("storeStatus.lowStock")}</dt>
              <dd>{format.count(count(STOCK_STATE.Low))}</dd>
            </div>
            <div data-state={STOCK_STATE.Out}>
              <dt>{t("storeStatus.outOfStock")}</dt>
              <dd>{format.count(count(STOCK_STATE.Out))}</dd>
            </div>
          </dl>
        </>
      ) : null}

      <form className="store-status-lookup" onSubmit={onLookup}>
        <label htmlFor="sku">{t("storeStatus.sku")}</label>
        <div className="store-status-lookup-row">
          <input
            className="text-field flex-1"
            id="sku"
            name="sku"
            value={sku}
            placeholder="P017"
            onChange={(event) => setSku(event.target.value)}
            autoComplete="off"
          />
          <Button
            type="submit"
            radius="sm"
            size="sm"
            isDisabled={lookupPending}
            className="h-9 shrink-0 cursor-pointer bg-accent px-3 text-[13px] font-semibold text-canvas data-[hover=true]:bg-accent-hover data-[disabled=true]:cursor-not-allowed"
          >
            {t(lookupPending ? "storeStatus.lookingUp" : "storeStatus.lookup")}
          </Button>
        </div>
      </form>
      {inventory ? (
        <p className="store-status-result">
          {t("storeStatus.result", {
            sku: inventory.sku,
            shelf: inventory.shelf_id,
            slot: inventory.slot_id,
            onShelf: inventory.shelf_quantity,
            backroom: inventory.backroom_quantity,
          })}
        </p>
      ) : null}

      {store ? (
        rows.length === 0 ? (
          <p className="store-status-muted">{t("storeStatus.listEmpty")}</p>
        ) : (
          <div className="store-status-list">
            <div className="store-status-row store-status-head" aria-hidden="true">
              <span />
              <span>{t("storeStatus.sku")}</span>
              <span>{t("storeStatus.location")}</span>
              <span>{t("storeStatus.onShelf")}</span>
              <span>{t("storeStatus.back")}</span>
            </div>
            <ul>
              {shown.map((row) => (
                <li key={row.sku}>
                  <button
                    type="button"
                    className="store-status-row"
                    aria-label={t("storeStatus.selectProduct", { sku: row.sku })}
                    aria-pressed={selected === row.sku}
                    title={t(`storeStatus.state.${row.state}`)}
                    onClick={() => select(row.sku, ENTITY_TYPE.Product)}
                  >
                    <span className="store-status-dot" data-state={row.state} />
                    <span className="store-status-sku">{row.sku}</span>
                    <span className="store-status-muted">{row.slot_id}</span>
                    <span>
                      {row.shelf_quantity}
                      <span className="store-status-faint">/{row.facings}</span>
                    </span>
                    <span>{row.backroom_quantity}</span>
                  </button>
                </li>
              ))}
            </ul>
            {rows.length > STORE_STATUS_ROWS ? (
              <button type="button" className="store-status-more" onClick={() => setDialogOpen(true)}>
                {t("storeStatus.showAll", { count: rows.length })}
              </button>
            ) : null}
          </div>
        )
      ) : null}
      {store ? (
        <ProductsDialog
          isOpen={dialogOpen}
          onClose={() => setDialogOpen(false)}
          storeId={store.store_id}
          contextVersion={store.context_version}
          rows={rows}
        />
      ) : null}
    </section>
  );
}
