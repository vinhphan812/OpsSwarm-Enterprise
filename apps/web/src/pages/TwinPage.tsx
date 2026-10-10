import {
  AgentActivityOpenButton,
  AgentActivityPanel,
} from "@/components/layout/AgentActivityPanel";
import { CameraHelp } from "@/components/layout/CameraHelp";
import { LensSwitcher } from "@/components/layout/LensSwitcher";
import { EntityInspector } from "@/components/twin/EntityInspector";
import { ProductDetailsDialog } from "@/components/twin/ProductDetailsDialog";
import { TwinIssuesNotice } from "@/components/twin/TwinIssuesNotice";
import { TwinStatusOverlay } from "@/components/twin/TwinStatusOverlay";
import { pickSource } from "@/core/twin/devSources";
import { useNetworkStatus } from "@/hooks/networkStatus.hook";
import { useProductParam } from "@/hooks/productParam.hook";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { StoreScene } from "@/scene/StoreScene";

const source = pickSource();

export function TwinPage() {
  useTwinSource(source);
  useNetworkStatus();
  useProductParam();

  return (
    <>
      <main className="viewport relative">
        <StoreScene />
        <TwinStatusOverlay />
        {/* TODO(BE): apps/api does not serve GET /revenue and GET /promotions yet; until it does the
          Revenue and Promotions lenses show their empty report and a toast, or the demo data under ?twin=demo. */}
        <div className="lens-switcher">
          <LensSwitcher />
        </div>
        <div className="absolute bottom-4 left-4 z-10">
          <CameraHelp />
        </div>
        <AgentActivityOpenButton />
        <EntityInspector />
        <ProductDetailsDialog />
        <TwinIssuesNotice />
      </main>
      <AgentActivityPanel />
    </>
  );
}
