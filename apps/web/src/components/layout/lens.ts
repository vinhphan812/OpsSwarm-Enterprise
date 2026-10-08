import type { ComponentType } from "react";
import { ActivityIcon, PromotionIcon, RevenueIcon } from "@/components/icons";
import { LENS, type Lens } from "@/enums/ui.enum";

/** Panel title, header note, and mark of each lens, as i18n keys. */
export const LENS_VIEW: Record<
  Lens,
  { title: "activity.title" | "revenue.title" | "promotions.title"; note: "activity.note" | "revenue.note" | "promotions.note"; Icon: ComponentType<{ className?: string }> }
> = {
  [LENS.Operations]: { title: "activity.title", note: "activity.note", Icon: ActivityIcon },
  [LENS.Revenue]: { title: "revenue.title", note: "revenue.note", Icon: RevenueIcon },
  [LENS.Promotions]: { title: "promotions.title", note: "promotions.note", Icon: PromotionIcon },
};
