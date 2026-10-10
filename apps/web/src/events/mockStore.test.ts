import { describe, it, expect } from 'vitest';
import { mockEvents } from './mockStore';

describe('mockStore', () => {
  it('contains at least 1 completed, 1 in-flight, 1 failed event', () => {
    const completed = mockEvents.filter(e => e.overallStatus === 'completed');
    const active = mockEvents.filter(e => e.overallStatus === 'active');
    const failed = mockEvents.filter(e => e.overallStatus === 'failed');
    
    expect(completed.length).toBeGreaterThanOrEqual(1);
    expect(active.length).toBeGreaterThanOrEqual(1);
    expect(failed.length).toBeGreaterThanOrEqual(1);
  });

  it('failed event has failureReason', () => {
    const failedEvent = mockEvents.find(e => e.overallStatus === 'failed');
    expect(failedEvent).toBeDefined();
    const failedStage = failedEvent?.stages.find(s => s.status === 'failed');
    expect(failedStage?.failureReason).toBeDefined();
  });

  it('no event contains sensitive fields', () => {
    const forbiddenFields = ["token", "secret", "apiKey", "password", "reasoning", "cot", "thought", "chain"];
    
    const checkObject = (obj: any) => {
      Object.keys(obj).forEach(key => {
        expect(forbiddenFields).not.toContain(key.toLowerCase());
        if (typeof obj[key] === 'object' && obj[key] !== null) {
          checkObject(obj[key]);
        }
      });
    };
    
    mockEvents.forEach(checkObject);
  });
});
