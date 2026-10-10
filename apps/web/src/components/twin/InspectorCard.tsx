import { Button, Card, CardBody, CardHeader } from "@heroui/react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useUiStore } from "@/state/ui.store";

type InspectorCardProps = {
  title: string;
  /** Short line under the title, such as the merchandise group. */
  subtitle?: string;
  label: string;
  /** Chips beside the title: status, sample data. */
  badges?: ReactNode;
  children: ReactNode;
};

/** The card the selected entity's details show in, bottom left over the 3D view. Close clears the selection. */
export function InspectorCard({ title, subtitle, label, badges, children }: InspectorCardProps) {
  const { t } = useTranslation();
  const select = useUiStore((state) => state.select);
  return (
    <Card className="absolute bottom-16 left-4 z-10 w-80" aria-label={label}>
      <CardHeader className="flex items-start justify-between gap-2 pb-0">
        <div className="min-w-0">
          <h2 className="text-base font-semibold">{title}</h2>
          {subtitle ? <p className="text-xs text-default-500">{subtitle}</p> : null}
          {badges ? <div className="mt-1 flex flex-wrap gap-1">{badges}</div> : null}
        </div>
        <Button size="sm" variant="light" className="cursor-pointer" onPress={() => select(null)}>
          {t("inspector.close")}
        </Button>
      </CardHeader>
      <CardBody className="text-sm">{children}</CardBody>
    </Card>
  );
}

/** Label and value rows inside an inspector card. */
export function Figures({ rows }: { rows: Array<[label: string, value: ReactNode]> }) {
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-default-500">{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
