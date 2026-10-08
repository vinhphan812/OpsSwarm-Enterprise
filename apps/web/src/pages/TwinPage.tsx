import { AgentActivityOpenButton, AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { CameraHelp } from "@/components/layout/CameraHelp";
import { LensSwitcher } from "@/components/layout/LensSwitcher";
import { ProductInspector } from "@/components/twin/ProductInspector";
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
        <div className="lens-switcher">
          <LensSwitcher />
        </div>
        <div className="absolute bottom-4 left-4 z-10">
          <CameraHelp />
        </div>
        <AgentActivityOpenButton />
        <ProductInspector />
        <TwinIssuesNotice />
      </main>
      <AgentActivityPanel />
    </>
  );
}
