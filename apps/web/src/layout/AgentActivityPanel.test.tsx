import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AgentActivityPanel } from './AgentActivityPanel';

describe('AgentActivityPanel', () => {
  it('renders correctly', () => {
    render(<AgentActivityPanel />);
    expect(screen.getByTestId('agent-activity')).toBeTruthy();
  });
});
