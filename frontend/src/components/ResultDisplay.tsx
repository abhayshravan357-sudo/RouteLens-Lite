import type { RouteLookupResult } from '../types/routing';

interface ResultDisplayProps {
  result: RouteLookupResult;
}

export default function ResultDisplay({ result }: ResultDisplayProps) {
  if (result.error) {
    return (
      <div className="result-card">
        <div className="result-header">
          <span className="result-status error" aria-label="Error">
            Error
          </span>
        </div>
        <div className="error-message" role="alert">
          <span aria-hidden="true">⚠</span>
          {result.error}
        </div>
      </div>
    );
  }

  if (!result.matched || !result.route) {
    return (
      <div className="result-card">
        <div className="result-header">
          <span className="result-status none" aria-label="No route found">
            No Matching Route
          </span>
        </div>
        <div className="explanation" role="alert">
          {result.explanation || 'No route matches the destination address.'}
        </div>
      </div>
    );
  }

  const { route, explanation } = result;

  return (
    <div className="result-card" role="region" aria-label="Route lookup result">
      <div className="result-header">
        <span className="result-status success" aria-label="Route found">
          Route Found
        </span>
        <span style={{ fontSize: '0.875rem', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)' }}>
          {route.destination}
        </span>
      </div>

      <div className="result-details">
        <div className="detail-item">
          <span className="detail-label">Selected Network</span>
          <span className="detail-value">{route.destination}</span>
        </div>
        <div className="detail-item">
          <span className="detail-label">Next Hop</span>
          <span className={`detail-value ${route.next_hop_type === 'direct' ? 'direct' : ''}`}>
            {route.next_hop || 'Directly connected'}
          </span>
        </div>
        <div className="detail-item">
          <span className="detail-label">Interface</span>
          <span className="detail-value">{route.interface}</span>
        </div>
        <div className="detail-item">
          <span className="detail-label">Metric</span>
          <span className="detail-value">{route.metric}</span>
        </div>
        <div className="detail-item">
          <span className="detail-label">Type</span>
          <span className="detail-value" style={{ textTransform: 'capitalize' }}>{route.next_hop_type}</span>
        </div>
      </div>

      <div className="explanation" role="region" aria-label="Route selection explanation">
        <strong>Why this route?</strong> {explanation}
      </div>
    </div>
  );
}