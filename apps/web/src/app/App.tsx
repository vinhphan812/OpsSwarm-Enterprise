import { AgentActivityPanel } from "@/components/layout/AgentActivityPanel";
import { TwinStatusOverlay } from "@/components/twin/TwinStatusOverlay";
import { pickSource } from "@/core/twin/devSources";
import { useTwinSource } from "@/hooks/twinSource.hook";
import { StoreScene } from "@/scene/StoreScene";
import "./App.css";

const source = pickSource();

export function App() {
  useTwinSource(source);

  return (
    <div className="app">
      <main className="viewport relative">
        <StoreScene />
        <TwinStatusOverlay />
      </main>
      <AgentActivityPanel />
    </div>
  );
}
