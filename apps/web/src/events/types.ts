export type AgentEventStage = 'trigger' | 'evidence' | 'diagnosis' | 'alternatives' | 'selected-plan' | 'simulation' | 'guard' | 'action' | 'verification';
export type StageStatus = 'pending' | 'active' | 'completed' | 'failed' | 'skipped';

export interface AgentStage {
  stage: AgentEventStage;
  status: StageStatus;
  timestamp: string;
  summary: string;
  failureReason?: string;
  evidenceId?: string;
  planId?: string;
  simulationId?: string;
  decisionId?: string;
  actionId?: string;
  verificationId?: string;
}

export interface AgentEvent {
  eventId: string;
  correlationId: string;
  agentId: string;
  storeId: string;
  contextVersion: string;
  overallStatus: 'pending' | 'active' | 'completed' | 'failed';
  startedAt: string;
  completedAt?: string;
  stages: AgentStage[];
}
