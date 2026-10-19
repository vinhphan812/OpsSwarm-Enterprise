import i18n from "@/i18n";
import { ACTION_TYPE } from "@/enums/simulation.enum";
import type { SimulationAction } from "@/types/simulation.type";

/** One proposed action in words, such as "Restock P003 +12". */
export function actionLabel(action: SimulationAction): string {
  switch (action.type) {
    case ACTION_TYPE.MoveProduct:
      return i18n.t("simulation.actions.move_product", { sku: action.sku, from: action.from_slot, to: action.to_slot });
    case ACTION_TYPE.ChangeFacings:
      return i18n.t("simulation.actions.change_facings", { sku: action.sku, facings: action.facings });
    case ACTION_TYPE.ReplenishShelf:
      return i18n.t("simulation.actions.replenish_shelf", { sku: action.sku, quantity: action.quantity });
  }
}
