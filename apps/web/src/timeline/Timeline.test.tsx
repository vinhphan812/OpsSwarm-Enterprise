import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Timeline } from './Timeline';
import { AgentEvent } from '../events/types';

describe('Timeline', () => {
  it('renders with empty events array', () => {
    const { container } = render(<Timeline events={[]} />);
    expect((container.firstChild as Element | null)?.className).toBe('agent-timeline');
    expect(container.firstChild?.childNodes).toHaveLength(0);
  });

  it('renders 1 agent event with correct info', () => {
    const event: AgentEvent = {
        eventId: 'evt-1',
        correlationId: 'corr-1',
        agentId: 'a1',
        storeId: 's1',
        contextVersion: '1',
        overallStatus: 'active',
        startedAt: '2026-10-09T08:00:00Z',
        stages: [{
            stage: 'trigger',
            status: 'completed',
            timestamp: '2026-10-09T08:00:01Z',
            summary: 'Summary'
        }]
    };
    render(<Timeline events={[event]} />);
    expect(screen.getByText('evt-1')).toBeTruthy();
    expect(screen.getByText('active')).toBeTruthy();
    expect(screen.getByText('trigger')).toBeTruthy();
    expect(screen.getByText('Summary')).toBeTruthy();
  });
});
