import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ConnectivityPanel from './ConnectivityPanel';

describe('ConnectivityPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to the DNS tab', () => {
    render(<ConnectivityPanel />);
    expect(screen.getByText('DNS Resolution')).toBeInTheDocument();
  });

  it('accepts initialTab prop', () => {
    render(<ConnectivityPanel initialTab="connectivity" />);
    expect(screen.getByText('Connectivity Check')).toBeInTheDocument();
  });

  it('accepts initialTab prop for traceroute', () => {
    render(<ConnectivityPanel initialTab="traceroute" />);
    expect(screen.getByText('Traceroute')).toBeInTheDocument();
  });
});
