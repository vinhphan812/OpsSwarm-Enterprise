import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Segmented } from "@/components/commerce/Segmented";
import { LiveIcon, SimulationIcon } from "@/components/icons";
import { notify } from "@/core/notify";
import i18n from "@/i18n";
import { VIEW_MODE, type ViewMode } from "@/enums/ui.enum";
import { useTwinStore } from "@/state/twin.store";
import { useUiStore } from "@/state/ui.store";

/**
 * Live / Simulation switch over the 3D view. Simulation can be picked only while a
 * simulation is open; when it closes (committed or discarded) the view goes back to Live.
 * A newly opened simulation raises a toast once, and a dot stays on Simulation until
 * the run has been looked at in the Simulation view.
 */
export function ViewModeSwitch() {
  const { t } = useTranslation();
  const viewMode = useUiStore((state) => state.viewMode);
  const setViewMode = useUiStore((state) => state.setViewMode);
  const simulationId = useTwinStore((state) => state.simulation?.simulation_id ?? null);
  const open = simulationId !== null;
  const viewing = open && viewMode === VIEW_MODE.Simulation;
  const [seenId, setSeenId] = useState<string | null>(null);
  const announcedId = useRef<string | null>(null);

  useEffect(() => {
    if (!open && viewMode === VIEW_MODE.Simulation) setViewMode(VIEW_MODE.Live);
  }, [open, viewMode, setViewMode]);

  useEffect(() => {
    if (viewing) setSeenId(simulationId);
  }, [viewing, simulationId]);

  useEffect(() => {
    if (simulationId === null || simulationId === announcedId.current) return;
    announcedId.current = simulationId;
    if (useUiStore.getState().viewMode !== VIEW_MODE.Simulation) {
      notify.info(i18n.t("simulation.opened", { id: simulationId }), i18n.t("simulation.openedHint"));
    }
  }, [simulationId]);

  const unseen = open && !viewing && simulationId !== seenId;

  return (
    <Segmented<ViewMode>
      variant="glass"
      label={t("viewMode.label")}
      layoutId="view-mode"
      value={open ? viewMode : VIEW_MODE.Live}
      onChange={setViewMode}
      options={[
        { value: VIEW_MODE.Live, label: t("viewMode.live"), icon: <LiveIcon className="h-3.5 w-3.5 shrink-0" /> },
        {
          value: VIEW_MODE.Simulation,
          label: t("viewMode.simulation"),
          hint: open ? undefined : t("viewMode.noSimulation"),
          icon: <SimulationIcon className="h-3.5 w-3.5 shrink-0" />,
          disabled: !open,
          dot: unseen ? t("viewMode.newSimulation") : undefined,
        },
      ]}
    />
  );
}
