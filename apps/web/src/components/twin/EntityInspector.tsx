import { useTranslation } from "react-i18next";
import { EQUIPMENT_TITLE, stockLabelKey } from "@/constants/scene.constant";
import { findFixture } from "@/core/twin/fixtureStock";
import { ENTITY_TYPE, EQUIPMENT_KIND } from "@/enums/scene.enum";
import { useUiStore } from "@/state/ui.store";
import { CheckoutInspector } from "./CheckoutInspector";
import { FixtureInspector } from "./FixtureInspector";
import { ProductInspector } from "./ProductInspector";

/** The details card of whatever is selected: a product, a shelf, display equipment, or a checkout. */
export function EntityInspector() {
  const { t } = useTranslation();
  const id = useUiStore((state) => state.selectedEntityId);
  const type = useUiStore((state) => state.selectedEntityType);
  if (!id) return null;
  if (type === ENTITY_TYPE.Product) return <ProductInspector productId={id} />;

  const fixture = findFixture(id);
  if (fixture?.shelf) return <FixtureInspector fixtureId={id} title={t(stockLabelKey(fixture.shelf.category))} />;
  const titleKey = fixture?.equipment ? EQUIPMENT_TITLE[fixture.equipment.kind] : undefined;
  if (!fixture?.equipment || !titleKey) return null;
  if (fixture.equipment.kind === EQUIPMENT_KIND.Checkout) return <CheckoutInspector checkoutId={id} title={t(titleKey)} />;
  return <FixtureInspector fixtureId={id} title={t(titleKey)} />;
}
