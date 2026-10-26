import { useState, FormEvent } from 'react';

interface LookupFormProps {
  onSubmit: (destination: string) => void;
  disabled?: boolean;
  defaultValue?: string;
}

/**
 * Validate an IPv4 address.
 * 4 octets separated by dots, each 0-255, no leading zeros (except "0" itself).
 */
function isValidIPv4(ip: string): boolean {
  const parts = ip.split('.');
  if (parts.length !== 4) return false;
  return parts.every((part) => {
    if (part.length === 0 || part.length > 3) return false;
    if (part.length > 1 && part[0] === '0') return false;
    const num = Number(part);
    return Number.isInteger(num) && num >= 0 && num <= 255;
  });
}

/**
 * Validate an IPv6 address.
 * 8 groups of 1-4 hex digits separated by colons.
 * Supports :: zero compression (at most one).
 */
function isValidIPv6(ip: string): boolean {
  // More than one :: is invalid
  if (ip.split('::').length > 2) return false;

  const groups = ip.split(':');

  if (ip.includes('::')) {
    // With ::, we can have at most 7 non-empty groups (one position is compressed)
    const nonEmptyGroups = groups.filter((g) => g.length > 0);
    if (nonEmptyGroups.length > 7) return false;
    return nonEmptyGroups.every((g) => /^[0-9a-fA-F]{1,4}$/.test(g));
  }

  // Without ::, must have exactly 8 groups
  if (groups.length !== 8) return false;
  return groups.every((g) => /^[0-9a-fA-F]{1,4}$/.test(g));
}

/**
 * Validate an IP address (IPv4 or IPv6).
 */
function isValidIPAddress(ip: string): boolean {
  const trimmed = ip.trim();
  if (!trimmed) return false;
  return isValidIPv4(trimmed) || isValidIPv6(trimmed);
}

export default function LookupForm({ onSubmit, disabled = false, defaultValue = '' }: LookupFormProps) {
  const [destination, setDestination] = useState(defaultValue);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = destination.trim();
    if (!trimmed) {
      setError('Please enter an IP address');
      return;
    }
    if (!isValidIPAddress(trimmed)) {
      setError('Please enter a valid IPv4 or IPv6 address');
      return;
    }
    setError(null);
    onSubmit(trimmed);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setDestination(e.target.value);
    if (error) setError(null);
  };

  return (
    <form className="lookup-form" onSubmit={handleSubmit} noValidate>
      <div className="input-group">
        <label htmlFor="destination">Destination IP Address</label>
        <input
          id="destination"
          type="text"
          value={destination}
          onChange={handleChange}
          placeholder="e.g., 192.168.1.50 or 2001:db8::1"
          disabled={disabled}
          aria-describedby={error ? 'destination-error' : 'destination-hint'}
          aria-invalid={!!error}
        />
        <span id="destination-hint" style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
          Enter an IPv4 or IPv6 address to find the best matching route
        </span>
        {error && (
          <span id="destination-error" style={{ fontSize: '0.75rem', color: 'var(--color-error)' }}>
            {error}
          </span>
        )}
      </div>
      <button
        type="submit"
        className="btn btn-primary"
        disabled={disabled || !destination.trim()}
      >
        {disabled ? 'Analyzing...' : 'Analyze Route'}
      </button>
    </form>
  );
}
