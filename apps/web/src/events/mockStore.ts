import { AgentEvent } from "./types";

export const mockEvents: AgentEvent[] = [
  {
    eventId: "event-1",
    correlationId: "corr-1",
    agentId: "agent-a",
    storeId: "store-001",
    contextVersion: "1.0",
    overallStatus: "active",
    startedAt: "2026-10-09T08:00:00Z",
    stages: [
      { stage: "trigger", status: "completed", timestamp: "2026-10-09T08:00:01Z", summary: "Triggered by alert" },
      { stage: "evidence", status: "completed", timestamp: "2026-10-09T08:00:05Z", summary: "Collected metrics" },
      { stage: "diagnosis", status: "completed", timestamp: "2026-10-09T08:00:10Z", summary: "Diagnosed issue" },
      { stage: "alternatives", status: "active", timestamp: "2026-10-09T08:00:15Z", summary: "Exploring alternatives" }
    ]
  },
  {
    eventId: "event-2",
    correlationId: "corr-2",
    agentId: "agent-a",
    storeId: "store-001",
    contextVersion: "1.0",
    overallStatus: "completed",
    startedAt: "2026-10-09T07:00:00Z",
    completedAt: "2026-10-09T07:30:00Z",
    stages: [
      { stage: "trigger", status: "completed", timestamp: "2026-10-09T07:00:01Z", summary: "Automated trigger" },
      { stage: "evidence", status: "completed", timestamp: "2026-10-09T07:05:00Z", summary: "Log dump analysis" },
      { stage: "diagnosis", status: "completed", timestamp: "2026-10-09T07:10:00Z", summary: "Diagnosis complete" },
      { stage: "alternatives", status: "completed", timestamp: "2026-10-09T07:15:00Z", summary: "Alternative options mapped" },
      { stage: "selected-plan", status: "completed", timestamp: "2026-10-09T07:20:00Z", summary: "Plan selected" },
      { stage: "simulation", status: "completed", timestamp: "2026-10-09T07:22:00Z", summary: "Simulation passed" },
      { stage: "guard", status: "completed", timestamp: "2026-10-09T07:25:00Z", summary: "Guard rails intact" },
      { stage: "action", status: "completed", timestamp: "2026-10-09T07:28:00Z", summary: "Action applied" },
      { stage: "verification", status: "completed", timestamp: "2026-10-09T07:30:00Z", summary: "Verification confirmed" }
    ]
  },
  {
    eventId: "event-3",
    correlationId: "corr-3",
    agentId: "agent-a",
    storeId: "store-001",
    contextVersion: "1.0",
    overallStatus: "failed",
    startedAt: "2026-10-09T06:00:00Z",
    stages: [
      { stage: "trigger", status: "completed", timestamp: "2026-10-09T06:00:01Z", summary: "Manual trigger" },
      { stage: "evidence", status: "failed", timestamp: "2026-10-09T06:05:00Z", summary: "Failed log retrieval", failureReason: "Timeout on log server" }
    ]
  }
];
