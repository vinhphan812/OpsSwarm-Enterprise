import { AgentEvent } from "./types";
import { mockEvents } from "./mockStore";

export interface AgentEventStore {
  getEvents(): AgentEvent[];
  subscribe(callback: (events: AgentEvent[]) => void): () => void;
}

class MockAgentEventStore implements AgentEventStore {
  getEvents(): AgentEvent[] {
    return mockEvents;
  }
  subscribe(callback: (events: AgentEvent[]) => void): () => void {
    // Mock: just call back once with current data
    callback(mockEvents);
    return () => {};
  }
}

export function createAgentEventStore(): AgentEventStore {
  return new MockAgentEventStore();
}
