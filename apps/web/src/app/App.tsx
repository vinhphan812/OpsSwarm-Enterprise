import { AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { ProductInspector } from "@/components/twin/ProductInspector";
import { TwinIssuesNotice } from "@/components/twin/TwinIssuesNotice";
import { TwinStatusOverlay } from "@/components/twin/TwinStatusOverlay";
import { pickSource } from "@/core/twin/devSources";
import { useProductParam } from "@/hooks/productParam.hook";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { StoreScene } from "@/scene/StoreScene";
import { Providers } from "./Providers";
import "./App.css";

const source = pickSource();

function TwinView() {
  useTwinSource(source);
  useProductParam();

  return (
    <div className="app">
      <main className="viewport relative">
        <StoreScene />
        <TwinStatusOverlay />
        <ProductInspector />
        <TwinIssuesNotice />
      </main>
      <AgentActivityPanel />
    </div>
  );
}

export function App() {
  return (
    <Providers>
      <TwinView />
    </Providers>
  );
}
