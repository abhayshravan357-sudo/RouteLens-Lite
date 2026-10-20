import { useState, FormEvent } from 'react';

interface LookupFormProps {
  onSubmit: (destination: string) => void;
  disabled?: boolean;
  defaultValue?: string;
}

export default function LookupForm({ onSubmit, disabled = false, defaultValue = '' }: LookupFormProps) {
  const [destination, setDestination] = useState(defaultValue);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = destination.trim();
    if (!trimmed) {
      setError('Please enter a destination IPv4 address');
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
        <label htmlFor="destination">Destination IPv4 Address</label>
        <input
          id="destination"
          type="text"
          value={destination}
          onChange={handleChange}
          placeholder="e.g., 192.168.1.50"
          disabled={disabled}
          aria-describedby={error ? 'destination-error' : 'destination-hint'}
          aria-invalid={!!error}
        />
        <span id="destination-hint" style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
          Enter an IPv4 address to find the best matching route
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