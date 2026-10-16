import {
  AgentActivityOpenButton,
  AgentActivityPanel,
} from "@/components/layout/AgentActivityPanel";
import { BuildBadge } from "@/components/layout/BuildBadge";
import { CameraHelp } from "@/components/layout/CameraHelp";
import { KpiStrip } from "@/components/layout/KpiStrip";
import { AgentFocusCaption } from "@/components/twin/AgentFocusCaption";
import { LensSwitcher } from "@/components/layout/LensSwitcher";
import { ViewModeSwitch } from "@/components/layout/ViewModeSwitch";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { ProductDetailsDialog } from "@/components/twin/ProductDetailsDialog";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import { TwinIssuesNotice } from "@/components/twin/TwinIssuesNotice";
import { TwinStatusOverlay } from "@/components/twin/TwinStatusOverlay";
import { pickSimulationReviewer, pickSimulationSource, pickSource } from "@/core/twin/devSources";
import { useAgentFocus } from "@/hooks/agentFocus.hook";
import { useNetworkStatus } from "@/hooks/networkStatus.hook";
import { useProductParam } from "@/hooks/productParam.hook";
import { useSimulationSource } from "@/hooks/simulationSource.hook";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { StoreScene } from "@/scene/StoreScene";

const source = pickSource();
const simulationSource = pickSimulationSource();
// After pickSource: under ?twin=memory|demo it reviews on the twin pickSource made.
const reviewer = pickSimulationReviewer();

export function TwinPage() {
  useTwinSource(source);
  useSimulationSource(simulationSource);
  useNetworkStatus();
  useProductParam();
  useAgentFocus();

  return (
    <>
      <main className="viewport relative">
        <StoreScene />
        <SimulationBanner reviewer={reviewer} />
        <TwinStatusOverlay />
        {/* TODO(BE): apps/api does not serve GET /revenue and GET /promotions yet; until it does the
          Revenue and Promotions lenses show their empty report and a toast, or the demo data under ?twin=demo. */}
        <div className="lens-switcher">
          <LensSwitcher />
          <ViewModeSwitch />
        </div>
        <KpiStrip />
        <div className="absolute bottom-4 left-4 z-10">
          <CameraHelp />
        </div>
        <AgentFocusCaption />
        <AgentActivityOpenButton />
        <EntityInspector />
        <ProductDetailsDialog />
        <TwinIssuesNotice />
        <BuildBadge />
      </main>
      <AgentActivityPanel />
    </>
  );
}
