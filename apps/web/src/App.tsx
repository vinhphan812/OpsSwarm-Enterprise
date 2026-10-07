import { AgentActivityPanel } from "./layout/AgentActivityPanel";
import { StoreScene } from "./scene/StoreScene";
import "./App.css";

export function App() {
  return (
    <div className="app">
      <main className="viewport">
        <StoreScene />
      </main>
      <AgentActivityPanel />
    </div>
  );
}
