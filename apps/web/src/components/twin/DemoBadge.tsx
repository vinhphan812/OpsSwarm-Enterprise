import { Chip, Tooltip } from "@heroui/react";
import { useTranslation } from "react-i18next";
import { isDemoMode } from "@/core/twin/demoMode";

/** Marks figures as demo data under `?twin=demo`; renders nothing otherwise. */
export function DemoBadge() {
  const { t } = useTranslation();
  if (!isDemoMode()) return null;
  return (
    <Tooltip content={t("checkout.demoHint")}>
      <Chip size="sm" variant="bordered" color="warning">
        {t("checkout.demo")}
      </Chip>
    </Tooltip>
  );
}
