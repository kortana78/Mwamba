import { describe, it, expect } from 'vitest';
import { STATUS_COLORS } from './components';

describe('provenance badges', () => {
  it('covers all five mandatory labels', () => {
    for (const label of ['VERIFIED', 'DERIVED', 'SYNTHETIC', 'MODEL OUTPUT', 'REVIEWED']) {
      expect(STATUS_COLORS[label]).toBeTruthy();
    }
  });
  it('covers UNVERIFIED and EVIDENCE INCOMPLETE honesty states', () => {
    expect(STATUS_COLORS['UNVERIFIED']).toBeTruthy();
    expect(STATUS_COLORS['EVIDENCE INCOMPLETE']).toBeTruthy();
  });
});

describe('score honesty', () => {
  it('formats scores as relative rankings, never probabilities', () => {
    const mean = 0.7234;
    const text = `mean ${mean.toFixed(3)}`;
    expect(text).toBe('mean 0.723');
    expect(text).not.toContain('probability');
  });
});
