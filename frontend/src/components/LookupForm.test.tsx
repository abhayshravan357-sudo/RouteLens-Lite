import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import LookupForm from './LookupForm';

describe('LookupForm', () => {
  let onSubmit: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    onSubmit = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('accepts valid IPv4 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: '192.168.1.1' } });
    fireEvent.click(button);

    expect(onSubmit).toHaveBeenCalledWith('192.168.1.1');
  });

  it('accepts valid IPv6 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: '2001:db8::1' } });
    fireEvent.click(button);

    expect(onSubmit).toHaveBeenCalledWith('2001:db8::1');
  });

  it('accepts compressed IPv6 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: '::1' } });
    fireEvent.click(button);

    expect(onSubmit).toHaveBeenCalledWith('::1');
  });

  it('accepts full IPv6 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: '2001:0db8:85a3:0000:0000:8a2e:0370:7334' } });
    fireEvent.click(button);

    expect(onSubmit).toHaveBeenCalledWith('2001:0db8:85a3:0000:0000:8a2e:0370:7334');
  });

  it('rejects empty input - button is disabled', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    expect(button).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('rejects invalid IPv4 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: '256.1.1.1' } });
    fireEvent.click(button);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText('Please enter a valid IPv4 or IPv6 address')).toBeInTheDocument();
  });

  it('rejects invalid IPv6 addresses', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: 'not:an:ip:address' } });
    fireEvent.click(button);

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText('Please enter a valid IPv4 or IPv6 address')).toBeInTheDocument();
  });

  it('clears error on input change', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    const input = screen.getByLabelText('Destination IP Address');
    const button = screen.getByRole('button', { name: 'Analyze Route' });

    fireEvent.change(input, { target: { value: 'invalid' } });
    fireEvent.click(button);
    expect(screen.getByText('Please enter a valid IPv4 or IPv6 address')).toBeInTheDocument();

    fireEvent.change(input, { target: { value: '10.0.0.1' } });
    expect(screen.queryByText('Please enter a valid IPv4 or IPv6 address')).not.toBeInTheDocument();
  });

  it('displays neutral IP address wording', () => {
    render(<LookupForm onSubmit={onSubmit} />);
    expect(screen.getByLabelText('Destination IP Address')).toBeInTheDocument();
    expect(screen.getByText('Enter an IPv4 or IPv6 address to find the best matching route')).toBeInTheDocument();
  });
});
