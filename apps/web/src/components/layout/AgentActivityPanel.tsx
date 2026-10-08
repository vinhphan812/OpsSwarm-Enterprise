import { StoreStatus } from "@/components/status/StoreStatus";

export function AgentActivityPanel() {
  return (
    <aside className="agent-activity" data-testid="agent-activity">
      <h1>Agent Activity</h1>
      <p className="fixture-note">Fixture scene for store-001. Not bound to the Live Twin.</p>
      <StoreStatus />
      <p className="empty">No agent activity yet.</p>
    </aside>
  );
}
