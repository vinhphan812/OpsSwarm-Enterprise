import { useEffect, useState } from "react";
import { StoreStatus } from "../components/status/StoreStatus";
import { AgentEvent } from "../events/types";
import { createAgentEventStore } from "../events/store";
import { Timeline } from "../timeline/Timeline";

const store = createAgentEventStore();

export function AgentActivityPanel() {
  const [events, setEvents] = useState<AgentEvent[]>([]);

  useEffect(() => {
    store.subscribe(setEvents);
  }, []);

  return (
    <aside className="agent-activity" data-testid="agent-activity">
      <h1>Agent Activity</h1>
      <StoreStatus />
      {events.length > 0 ? (
        <Timeline events={events} />
      ) : (
        <p className="empty">No agent activity yet.</p>
      )}
    </aside>
  );
}
