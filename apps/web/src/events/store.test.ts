import { describe, it, expect, vi } from 'vitest';
import { createAgentEventStore } from './store';
import { mockEvents } from './mockStore';

describe('AgentEventStore', () => {
    it('implements AgentEventStore interface and returns mock events', () => {
        const store = createAgentEventStore();
        expect(store.getEvents()).toEqual(mockEvents);
    });

    it('subscribe calls callback immediately', () => {
        const store = createAgentEventStore();
        const callback = vi.fn();
        store.subscribe(callback);
        expect(callback).toHaveBeenCalledWith(mockEvents);
    });

    it('subscribe returns an unsubscribe function', () => {
        const store = createAgentEventStore();
        const callback = vi.fn();
        const unsubscribe = store.subscribe(callback);
        
        expect(typeof unsubscribe).toBe('function');
        // No-op verification
        expect(() => unsubscribe()).not.toThrow();
    });
});
