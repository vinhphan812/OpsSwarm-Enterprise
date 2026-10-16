import { Button, Switch } from "@heroui/react";
import { AnimatePresence, motion, type Transition } from "framer-motion";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { ActivityIcon, PanelToggleIcon } from "@/components/icons";
import { PromotionsPanel } from "@/components/promotions/PromotionsPanel";
import { RevenuePanel } from "@/components/revenue/RevenuePanel";
import { StoreStatus } from "@/components/status/StoreStatus";
import { PANEL_WIDTH } from "@/constants/app.constant";
import { groupRuns } from "@/core/agent/agentRuns";
import { ACTIVITY_VIEW, ACTIVITY_VIEWS } from "@/enums/agent.enum";
import { LENS } from "@/enums/ui.enum";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useUiStore } from "@/state/ui.store";
import { ActivityLog } from "./ActivityLog";
import { AgentRunCard } from "./AgentRunCard";
import { AiImpactSection } from "./AiImpactSection";
import { AlertsSection } from "./AlertsSection";
import { GuardSection } from "./GuardSection";
import { LENS_VIEW } from "./lens";

/** Panel slide: quick, settles without a visible bounce. Transform only, so the 3D view never resizes. */
const PANEL_SLIDE: Transition = { type: "spring", stiffness: 420, damping: 40 };
const PANEL_HIDDEN = { x: "calc(100% + 24px)", opacity: 0.6 };
/** Lens change: the old content fades left, the new one comes in from the right. */
const LENS_SWAP: Transition = { duration: 0.18, ease: "easeOut" };

/** Floating button over the 3D view that brings the closed panel back. */
export function AgentActivityOpenButton() {
  const { t } = useTranslation();
  const open = usePanelStore((state) => state.open);
  const setOpen = usePanelStore((state) => state.setOpen);
  const { title } = LENS_VIEW[useUiStore((state) => state.lens)];
  const label = t("panel.open", { title: t(title) });
  return (
    <AnimatePresence>
      {open ? null : (
        <motion.div
          key="open-panel"
          className="absolute right-4 top-4 z-10"
          initial={{ opacity: 0, scale: 0.9, x: 12 }}
          animate={{ opacity: 1, scale: 1, x: 0 }}
          exit={{ opacity: 0, scale: 0.9, x: 12 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
        >
          <Button
            isIconOnly
            radius="full"
            disableRipple
            aria-label={label}
            title={label}
            onPress={() => setOpen(true)}
            className="h-9 w-9 min-w-0 cursor-pointer bg-panel/75 text-accent shadow-lg shadow-black/20 ring-1 ring-line backdrop-blur-md data-[hover=true]:bg-panel/90"
          >
            <PanelToggleIcon expand className="h-4.5 w-4.5" />
          </Button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/**
 * Operations lens: the open alerts and opportunities, the guard's last answer, the agent's
 * timeline, and the inventory check last, as it is reference rather than the work in hand.
 * The timeline shows one card per run (`correlation_id`), newest first, with entries of no run
 * listed below; or the raw log. A SKU in it selects that product; picking an alert narrows it
 * to its run. Follow agent lets the agent's own steps move the camera (`useAgentFocus`).
 */
function OperationsView() {
  const { t } = useTranslation();
  const activity = useRunStore((state) => state.activity);
  const followAgent = useUiStore((state) => state.followAgent);
  const setFollowAgent = useUiStore((state) => state.setFollowAgent);
  const focusedCorrelationId = useUiStore((state) => state.focusedCorrelationId);
  const showAllActivity = useUiStore((state) => state.showAllActivity);
  const activityView = useUiStore((state) => state.activityView);
  const setActivityView = useUiStore((state) => state.setActivityView);
  const shown = useMemo(
    () => (focusedCorrelationId ? activity.filter((entry) => entry.correlation_id === focusedCorrelationId) : activity),
    [activity, focusedCorrelationId],
  );
  const { runs, loose } = useMemo(() => groupRuns(shown), [shown]);

  return (
    <>
      <AlertsSection />
      <GuardSection />
      <AiImpactSection />

      <section className="activity-section">
        <div className="activity-section-head">
          <h2 className="activity-section-title">
            {t("activity.section")}
            <span className="activity-count">{shown.length}</span>
          </h2>
          <Switch
            size="sm"
            isSelected={followAgent}
            onValueChange={setFollowAgent}
            title={t("activity.followAgentHint")}
            classNames={{ label: "text-xs text-ink-soft" }}
          >
            {t("activity.followAgent")}
          </Switch>
        </div>
        <div className="activity-view" role="group" aria-label={t("activity.view.label")}>
          {ACTIVITY_VIEWS.map((view) => (
            <button
              key={view}
              type="button"
              aria-pressed={activityView === view}
              onClick={() => setActivityView(view)}
            >
              {t(`activity.view.${view}`)}
            </button>
          ))}
        </div>
        {focusedCorrelationId ? (
          <div className="activity-filter">
            <span>{t("alerts.filtered")}</span>
            <button type="button" onClick={showAllActivity}>
              {t("alerts.showAll")}
            </button>
          </div>
        ) : null}
        <AnimatePresence initial={false} mode="popLayout">
          {!shown.length ? (
            <motion.div
              key="empty"
              className="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <ActivityIcon className="empty-icon" />
              <p>{t(focusedCorrelationId ? "alerts.noRunYet" : "activity.empty")}</p>
            </motion.div>
          ) : activityView === ACTIVITY_VIEW.Log ? (
            <motion.div key="log" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <ActivityLog entries={shown} label={t("activity.timeline")} />
            </motion.div>
          ) : (
            <motion.div key="runs" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              {runs.length ? (
                <ol className="run-list" aria-label={t("activity.runs")}>
                  <AnimatePresence initial={false}>
                    {runs.map((run) => (
                      <AgentRunCard key={run.id} run={run} />
                    ))}
                  </AnimatePresence>
                </ol>
              ) : null}
              {loose.length ? (
                <>
                  <h3 className="activity-loose-title">{t("activity.loose")}</h3>
                  <ActivityLog entries={loose} label={t("activity.loose")} />
                </>
              ) : null}
            </motion.div>
          )}
        </AnimatePresence>
      </section>

      <StoreStatus />
    </>
  );
}

/** The panel body of each lens. */
const LENS_BODY = {
  [LENS.Operations]: OperationsView,
  [LENS.Revenue]: RevenuePanel,
  [LENS.Promotions]: PromotionsPanel,
};

export function AgentActivityPanel() {
  const { t } = useTranslation();
  const open = usePanelStore((state) => state.open);
  const setOpen = usePanelStore((state) => state.setOpen);
  const lens = useUiStore((state) => state.lens);
  const { title, note, Icon } = LENS_VIEW[lens];
  const Body = LENS_BODY[lens];

  return (
    <AnimatePresence initial={false}>
      {open ? (
        <motion.aside
          key="agent-activity"
          className="agent-activity"
          data-testid="agent-activity"
          data-lens={lens}
          style={{ width: PANEL_WIDTH }}
          initial={PANEL_HIDDEN}
          animate={{ x: 0, opacity: 1 }}
          exit={PANEL_HIDDEN}
          transition={PANEL_SLIDE}
        >
          <div className="agent-activity-inner">
            <header className="agent-activity-header">
              <div className="agent-activity-titlebar">
                <AnimatePresence initial={false} mode="wait">
                  <motion.div
                    key={lens}
                    className="agent-activity-heading"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 4 }}
                    transition={LENS_SWAP}
                  >
                    <span className="agent-activity-mark">
                      <Icon className="h-4 w-4" />
                    </span>
                    <h1>{t(title)}</h1>
                  </motion.div>
                </AnimatePresence>
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  radius="sm"
                  aria-label={t("panel.close", { title: t(title) })}
                  title={t("panel.close", { title: t(title) })}
                  onPress={() => setOpen(false)}
                  className="ml-auto min-w-0 cursor-pointer text-ink-muted data-[hover=true]:bg-card data-[hover=true]:text-ink"
                >
                  <PanelToggleIcon expand={false} className="h-4.5 w-4.5" />
                </Button>
              </div>
              <p className="fixture-note">{t(note)}</p>
            </header>

            <AnimatePresence initial={false} mode="wait">
              <motion.div
                key={lens}
                className="agent-activity-body"
                initial={{ opacity: 0, x: 16 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -16 }}
                transition={LENS_SWAP}
              >
                <Body />
              </motion.div>
            </AnimatePresence>
          </div>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}
