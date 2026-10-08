import { Button } from "@heroui/react";
import { AnimatePresence, motion, type Transition } from "framer-motion";
import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { useTranslation } from "react-i18next";
import { ActivityIcon, PanelToggleIcon } from "@/components/icons";
import { PromotionsPanel } from "@/components/promotions/PromotionsPanel";
import { RevenuePanel } from "@/components/revenue/RevenuePanel";
import { StoreStatus } from "@/components/status/StoreStatus";
import { PANEL_WIDTH, PANEL_WIDTH_STEP } from "@/constants/app.constant";
import { LENS } from "@/enums/ui.enum";
import { usePanelStore } from "@/state/panel.store";
import { useRunStore } from "@/state/run.store";
import { useUiStore } from "@/state/ui.store";
import { LENS_VIEW } from "./lens";

/** Panel slide: quick, settles without a visible bounce. Transform only, so the 3D view never resizes. */
const PANEL_SLIDE: Transition = { type: "spring", stiffness: 420, damping: 40 };
const PANEL_HIDDEN = { x: "calc(100% + 24px)", opacity: 0.6 };
/** Lens change: the old content fades left, the new one comes in from the right. */
const LENS_SWAP: Transition = { duration: 0.18, ease: "easeOut" };

/** HH:MM:SS of an ISO timestamp, in the viewer's time zone. */
function clock(ts: string) {
  return new Date(ts).toLocaleTimeString([], { hour12: false });
}

/**
 * Drag handle on the panel's left edge. Dragging left widens the panel; arrow keys step
 * it, and a double click restores the default width.
 */
function ResizeHandle() {
  const { t } = useTranslation();
  const width = usePanelStore((state) => state.width);
  const setWidth = usePanelStore((state) => state.setWidth);
  const drag = useRef<{ x: number; width: number } | null>(null);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, width };
    document.body.classList.add("is-resizing");
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    setWidth(drag.current.width + (drag.current.x - event.clientX));
  };
  const onPointerUp = () => {
    drag.current = null;
    document.body.classList.remove("is-resizing");
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = { ArrowLeft: PANEL_WIDTH_STEP, ArrowRight: -PANEL_WIDTH_STEP }[
      event.key
    ];
    if (step === undefined) return;
    event.preventDefault();
    setWidth(width + step);
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t("activity.resize")}
      aria-valuemin={PANEL_WIDTH.min}
      aria-valuemax={PANEL_WIDTH.max}
      aria-valuenow={width}
      tabIndex={0}
      title={t("activity.resize")}
      className="panel-resizer"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
      onDoubleClick={() => setWidth(PANEL_WIDTH.default)}
    />
  );
}

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

/** Operations lens: the store API check and the agent's timeline. */
function OperationsView() {
  const { t } = useTranslation();
  const activity = useRunStore((state) => state.activity);

  return (
    <>
      <StoreStatus />

      <section className="activity-section">
        <h2 className="activity-section-title">
          {t("activity.section")}
          <span className="activity-count">{activity.length}</span>
        </h2>
        <AnimatePresence initial={false} mode="popLayout">
          {activity.length ? (
            <motion.ol
              key="list"
              className="activity-list"
              aria-label={t("activity.timeline")}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <AnimatePresence initial={false}>
                {activity.map((entry) => (
                  <motion.li
                    key={entry.id}
                    layout
                    className="activity-item"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.22, ease: "easeOut" }}
                  >
                    <div className="activity-meta">
                      <time dateTime={entry.ts}>{clock(entry.ts)}</time>
                      <span className="activity-stage">{entry.stage}</span>
                      {entry.sku ? (
                        <span className="activity-sku">{entry.sku}</span>
                      ) : null}
                    </div>
                    <p className="activity-summary">{entry.summary}</p>
                  </motion.li>
                ))}
              </AnimatePresence>
            </motion.ol>
          ) : (
            <motion.div
              key="empty"
              className="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <ActivityIcon className="empty-icon" />
              <p>{t("activity.empty")}</p>
            </motion.div>
          )}
        </AnimatePresence>
      </section>
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
  const width = usePanelStore((state) => state.width);
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
          style={{ width }}
          initial={PANEL_HIDDEN}
          animate={{ x: 0, opacity: 1 }}
          exit={PANEL_HIDDEN}
          transition={PANEL_SLIDE}
        >
          <ResizeHandle />
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
