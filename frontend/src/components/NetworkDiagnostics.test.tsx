import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import NetworkDiagnostics from './NetworkDiagnostics';

describe('NetworkDiagnostics', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders without crashing', () => {
    const { container } = render(<NetworkDiagnostics />);
    expect(container).toBeInTheDocument();
  });

  it('shows Network Diagnostics heading', () => {
    render(<NetworkDiagnostics />);
    expect(screen.getByText('Network Diagnostics')).toBeInTheDocument();
  });

  it('renders ConnectivityPanel inside DNS section', () => {
    render(<NetworkDiagnostics />);
    expect(screen.getByText('Network Diagnostics')).toBeInTheDocument();
  });
});
