import { describe, it, expect } from 'vitest';
import { AgentEventStage, StageStatus, AgentStage, AgentEvent } from './types';

describe('AgentEvent Types', () => {
  it('covers all 9 stages', () => {
    const stages: AgentEventStage[] = [
      'trigger', 'evidence', 'diagnosis', 'alternatives', 'selected-plan',
      'simulation', 'guard', 'action', 'verification'
    ];
    expect(stages).toHaveLength(9);
  });

  it('covers all 5 statuses', () => {
    const statuses: StageStatus[] = [
      'pending', 'active', 'completed', 'failed', 'skipped'
    ];
    expect(statuses).toHaveLength(5);
  });

  it('AgentStage has correct shape', () => {
    const stage: AgentStage = {
      stage: 'trigger',
      status: 'completed',
      timestamp: '2026-10-09T00:00:00Z',
      summary: 'Triggered'
    };
    expect(stage).toBeDefined();
    
    // Test optional fields
    const fullStage: AgentStage = {
      ...stage,
      failureReason: 'Error',
      evidenceId: 'e1',
      planId: 'p1',
      simulationId: 's1',
      decisionId: 'd1',
      actionId: 'a1',
      verificationId: 'v1'
    };
    expect(fullStage.failureReason).toBe('Error');
  });

  it('AgentEvent has correct shape', () => {
    const event: AgentEvent = {
        eventId: 'e1',
        correlationId: 'c1',
        agentId: 'a1',
        storeId: 's1',
        contextVersion: 'v1',
        overallStatus: 'completed',
        startedAt: '2026-10-09T00:00:00Z',
        stages: []
    };
    expect(event).toBeDefined();
    expect(event.completedAt).toBeUndefined();
  });
});
