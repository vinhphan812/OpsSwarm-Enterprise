import { Button } from "@heroui/react";
import { useTranslation } from "react-i18next";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <main className="col-span-full flex h-full flex-col items-center justify-center gap-4 bg-canvas p-4 text-center">
      <p className="text-7xl font-bold text-ink-faint">404</p>
      <h1 className="text-xl font-semibold text-ink">{t("notFound.title")}</h1>
      <p className="max-w-sm text-sm text-ink-muted">{t("notFound.body")}</p>
      <Button href="/" as="a" radius="sm" className="cursor-pointer bg-accent font-semibold text-canvas data-[hover=true]:bg-accent-hover">
        {t("notFound.home")}
      </Button>
    </main>
  );
}
