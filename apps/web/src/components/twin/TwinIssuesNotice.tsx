import { Button, Card, CardBody } from "@heroui/react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { ISSUES_SHOWN, PANEL_WIDTH } from "@/constants/app.constant";
import { usePanelStore } from "@/state/panel.store";
import { issueReason } from "@/core/api/validate";
import { useTwinIssues } from "@/hooks/twinIssues.hook";
import { useUiStore } from "@/state/ui.store";

/** Products in the live state that the scene leaves out, with the reason for each. */
export function TwinIssuesNotice() {
  const { t } = useTranslation();
  const issues = useTwinIssues();
  const select = useUiStore((state) => state.select);
  // Sit left of the floating Agent Activity panel instead of under it.
  const panelInset = usePanelStore((state) => (state.open ? PANEL_WIDTH + 24 : 0));

  useEffect(() => {
    if (issues.length > 0) console.warn(t("issues.console"), issues);
  }, [issues, t]);

  if (issues.length === 0) return null;

  return (
    <Card className="absolute bottom-4 right-4 w-80" style={{ marginRight: panelInset }} role="status">
      <CardBody className="gap-1 text-sm">
        <h2 className="font-semibold text-warning-700">{t("issues.title", { count: issues.length })}</h2>
        <ul>
          {issues.slice(0, ISSUES_SHOWN).map((issue) => (
            <li key={`${issue.sku}-${issue.code}`}>
              <Button
                size="sm"
                variant="light"
                disableRipple
                className="h-auto min-w-0 cursor-pointer px-1 font-medium underline data-[hover=true]:bg-warning-100 data-[hover=true]:text-warning-700"
                onPress={() => select(issue.sku)}
              >
                {issue.sku}
              </Button>
              : {issueReason(issue)}
            </li>
          ))}
        </ul>
        {issues.length > ISSUES_SHOWN ? (
          <p className="text-default-500">{t("issues.more", { count: issues.length - ISSUES_SHOWN })}</p>
        ) : null}
      </CardBody>
    </Card>
  );
}
