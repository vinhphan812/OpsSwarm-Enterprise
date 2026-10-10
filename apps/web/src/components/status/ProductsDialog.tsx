import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ListDialog } from "@/components/common/ListDialog";
import { Segmented } from "@/components/commerce/Segmented";
import { matchRows, type ProductRow } from "@/core/twin/productRows";
import { ENTITY_TYPE } from "@/enums/scene.enum";
import { STOCK_STATE, type StockState } from "@/enums/stock.enum";
import { useUiStore } from "@/state/ui.store";

const ALL = "all";
type StateFilter = StockState | typeof ALL;
const FILTERS: readonly StateFilter[] = [ALL, STOCK_STATE.Out, STOCK_STATE.Low, STOCK_STATE.Ok];

type ProductsDialogProps = {
  isOpen: boolean;
  onClose: () => void;
  storeId: string;
  contextVersion: string;
  /** Already sorted, out and low stock first. */
  rows: ProductRow[];
};

/**
 * Every product of the live store in one table, filtered by stock state or a search.
 * Clicking a product selects it in the 3D view and closes the dialog.
 */
export function ProductsDialog({ isOpen, onClose, storeId, contextVersion, rows }: ProductsDialogProps) {
  const { t } = useTranslation();
  const select = useUiStore((state) => state.select);
  const [filter, setFilter] = useState<StateFilter>(ALL);
  const [query, setQuery] = useState("");

  const shown = useMemo(
    () => matchRows(filter === ALL ? rows : rows.filter((row) => row.state === filter), query),
    [rows, filter, query],
  );
  const countOf = (value: StateFilter) => (value === ALL ? rows.length : rows.filter((row) => row.state === value).length);

  const show = (sku: string) => {
    select(sku, ENTITY_TYPE.Product);
    onClose();
  };

  return (
    <ListDialog
      isOpen={isOpen}
      onClose={onClose}
      title={t("storeStatus.dialog.title", { storeId })}
      subtitle={t("storeStatus.dialog.context", { contextVersion })}
      empty={t("storeStatus.dialog.empty")}
      isEmpty={shown.length === 0}
      toolbar={
        <>
          <Segmented
            variant="chips"
            label={t("storeStatus.dialog.filter")}
            layoutId="product-state-filter"
            value={filter}
            onChange={setFilter}
            options={FILTERS.map((value) => ({
              value,
              label: value === ALL ? t("storeStatus.dialog.all") : t(`storeStatus.state.${value}`),
              badge: countOf(value),
            }))}
          />
          <input
            type="search"
            className="text-field dialog-search"
            aria-label={t("storeStatus.dialog.search")}
            placeholder={t("storeStatus.dialog.search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            autoComplete="off"
          />
        </>
      }
    >
      <table className="data-table products-table">
        <thead>
          <tr>
            <th scope="col">
              <span className="sr-only">{t("storeStatus.dialog.state")}</span>
            </th>
            <th scope="col">{t("storeStatus.sku")}</th>
            <th scope="col">{t("storeStatus.dialog.shelf")}</th>
            <th scope="col">{t("storeStatus.dialog.slot")}</th>
            <th scope="col" className="num">{t("storeStatus.dialog.facings")}</th>
            <th scope="col" className="num">{t("storeStatus.onShelf")}</th>
            <th scope="col" className="num">{t("storeStatus.dialog.backroom")}</th>
            <th scope="col" className="num">{t("storeStatus.dialog.version")}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((row) => (
            <tr
              key={row.sku}
              tabIndex={0}
              aria-label={t("storeStatus.selectProduct", { sku: row.sku })}
              onClick={() => show(row.sku)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  show(row.sku);
                }
              }}
            >
              <td>
                <span className="store-status-dot" data-state={row.state} title={t(`storeStatus.state.${row.state}`)} />
              </td>
              <td className="font-semibold">{row.sku}</td>
              <td>{row.shelf_id}</td>
              <td className="text-ink-muted">{row.slot_id}</td>
              <td className="num">{row.facings}</td>
              <td className="num" data-state={row.state}>
                {row.shelf_quantity}
              </td>
              <td className="num">{row.backroom_quantity}</td>
              <td className="num text-ink-muted">{row.version}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ListDialog>
  );
}
