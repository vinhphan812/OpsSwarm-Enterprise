import {
  AgentActivityOpenButton,
  AgentActivityPanel,
} from "@/components/layout/AgentActivityPanel";
import { BuildBadge } from "@/components/layout/BuildBadge";
import { CameraHelp } from "@/components/layout/CameraHelp";
import { KpiStrip } from "@/components/layout/KpiStrip";
import { AgentFocusCaption } from "@/components/twin/AgentFocusCaption";
import { AiImpactDialog } from "@/components/twin/AiImpactDialog";
import { AiImpactToast } from "@/components/twin/AiImpactToast";
import { LensSwitcher } from "@/components/layout/LensSwitcher";
import { RunDemoButton } from "@/components/layout/RunDemoButton";
import { ViewModeSwitch } from "@/components/layout/ViewModeSwitch";
import { OverlayLegend } from "@/components/layout/OverlayLegend";
import { OverlayToggles } from "@/components/layout/OverlayToggles";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { ProductDetailsDialog } from "@/components/twin/ProductDetailsDialog";
import { SimulationBanner } from "@/components/twin/SimulationBanner";
import { TwinIssuesNotice } from "@/components/twin/TwinIssuesNotice";
import { TwinStatusOverlay } from "@/components/twin/TwinStatusOverlay";
import { TwinDemoBanner } from "@/components/layout/TwinDemoBanner";
import { TwinFooter } from "@/components/layout/TwinFooter";
import { TwinHeader } from "@/components/layout/TwinHeader";
import {
  isApiTwin,
  pickDemoRunner,
  pickSimulationReviewer,
  pickSimulationSource,
  pickSource,
} from "@/core/twin/devSources";
import { useAgentFocus } from "@/hooks/agentFocus.hook";
import { useDemoDirector } from "@/hooks/demoDirector.hook";
import { useAnomalyPolling } from "@/hooks/anomalyPolling.hook";
import { useFlagshipStatus } from "@/hooks/flagshipStatus.hook";
import { useNetworkStatus } from "@/hooks/networkStatus.hook";
import { useProductParam } from "@/hooks/productParam.hook";
import { useSimulationSource } from "@/hooks/simulationSource.hook";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { StoreScene } from "@/scene/StoreScene";

const source = pickSource();
const simulationSource = pickSimulationSource();
// After pickSource: under ?twin=memory|demo it reviews on the twin pickSource made.
const reviewer = pickSimulationReviewer();
// After pickSource too: under ?twin=demo the demo fixtures stand in for the flagship controller.
const demoRunner = pickDemoRunner();

export function TwinPage() {
  useTwinSource(source);
  useSimulationSource(simulationSource);
  useNetworkStatus();
  useProductParam();
  useAgentFocus();
  useDemoDirector();
  useAnomalyPolling();
  useFlagshipStatus(isApiTwin());

  return (
    <>
      {/* Above .twin-body, not in it: the viewport fills .twin-body, so a bar inside would push
      its bottom edge (and the bottom-left controls) out of the window. */}
      <TwinHeader />
      <TwinDemoBanner />
      <div className="twin-body">
        <main className="viewport relative">
          <StoreScene />
          <SimulationBanner reviewer={reviewer} />
          <TwinStatusOverlay />
          {/* TODO(BE): apps/api does not serve GET /revenue and GET /promotions yet; until it does the
          Revenue and Promotions lenses show their empty report and a toast, or the demo data under ?twin=demo. */}
          <div className="lens-switcher">
            <LensSwitcher />
            <ViewModeSwitch />
            <RunDemoButton runner={demoRunner} />
          </div>
          <KpiStrip />
          {/* Bottom left: the overlay legend over the camera help and the Overlays toggles. */}
          <div className="absolute bottom-4 left-4 z-10 flex flex-col items-start gap-2">
            <OverlayLegend />
            <div className="flex items-center gap-2">
              <CameraHelp />
              <OverlayToggles />
            </div>
          </div>
          <AgentFocusCaption />
          <AiImpactToast />
          <AgentActivityOpenButton />
          <EntityInspector />
          <ProductDetailsDialog />
          <TwinIssuesNotice />
          <BuildBadge />
          <AiImpactDialog />
        </main>
        <AgentActivityPanel />
      </div>
      <TwinFooter />
    </>
  );
}
