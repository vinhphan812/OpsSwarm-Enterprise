import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { defaultClient } from "@/core/api/client";
import type { RetailTwinClient } from "@/types/api.type";
import type { ProductInventory } from "@/types/twin.type";
import { useStoreStatus } from "@/hooks/storeStatus.hook";
import "./StoreStatus.css";

/** Columns of the product table, in order. */
const COLUMNS = [
  { label: "storeStatus.sku", value: (item: ProductInventory) => item.sku },
  { label: "storeStatus.shelf", value: (item: ProductInventory) => item.shelf_id },
  { label: "storeStatus.slot", value: (item: ProductInventory) => item.slot_id },
  { label: "storeStatus.facings", value: (item: ProductInventory) => item.facings },
  { label: "storeStatus.onShelf", value: (item: ProductInventory) => item.shelf_quantity },
  { label: "storeStatus.backroom", value: (item: ProductInventory) => item.backroom_quantity },
] as const;

type StoreStatusProps = {
  client?: RetailTwinClient;
};

export function StoreStatus({ client = defaultClient }: StoreStatusProps) {
  const { t } = useTranslation();
  const { health, store, loading, sku, setSku, inventory, lookupPending, onLookup } = useStoreStatus(client);

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
          <div className="store-status-table">
            <table>
              <thead>
                <tr>
                  {COLUMNS.map((column) => (
                    <th key={column.label} scope="col">
                      {t(column.label)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {store.products.map((item) => (
                  <tr key={item.sku}>
                    {COLUMNS.map((column) => (
                      <td key={column.label}>
                        <span className="store-status-label">{t(column.label)}</span>
                        {column.value(item)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <form className="store-status-lookup" onSubmit={onLookup}>
        <label htmlFor="sku">{t("storeStatus.sku")}</label>
        <div className="store-status-lookup-row">
          <input
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
    </section>
  );
}
