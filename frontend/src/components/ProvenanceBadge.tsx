/**
 * ProvenanceBadge
 *
 * Shows where a piece of information came from. This is the core of the
 * project's honesty rule: the user must always be able to tell whether
 * something was measured on this machine, worked out from other data,
 * produced by a simulation, or is simply unknown.
 */

export type Provenance = 'observed' | 'inferred' | 'simulated' | 'unknown';

const LABELS: Record<Provenance, string> = {
  observed: 'Observed',
  inferred: 'Inferred',
  simulated: 'Simulated',
  unknown: 'Unknown',
};

const DESCRIPTIONS: Record<Provenance, string> = {
  observed: 'Measured directly on this machine.',
  inferred: 'Worked out from other measured data.',
  simulated: 'Produced by the RouteLens simulator, not measured.',
  unknown: 'Not enough evidence to say.',
};

const CLASS_NAMES: Record<Provenance, string> = {
  observed: 'provenance-observed',
  inferred: 'provenance-inferred',
  simulated: 'provenance-simulated',
  unknown: 'provenance-unknown',
};

const ICONS: Record<Provenance, string> = {
  observed: '●', // filled circle: measured
  inferred: '◐', // half circle: deduced
  simulated: '◇', // diamond: modelled
  unknown: '○', // empty circle: no evidence
};

interface ProvenanceBadgeProps {
  provenance: Provenance;
  /** Override the default label, e.g. "Simulated (lab)". */
  label?: string;
  /** Show the longer explanation underneath. */
  showDescription?: boolean;
  size?: 'small' | 'medium';
}

export default function ProvenanceBadge({
  provenance,
  label,
  showDescription = false,
  size = 'medium',
}: ProvenanceBadgeProps) {
  const text = label ?? LABELS[provenance];

  return (
    <span
      className={`provenance-badge ${CLASS_NAMES[provenance]} provenance-${size}`}
      title={DESCRIPTIONS[provenance]}
    >
      <span className="provenance-icon" aria-hidden="true">
        {ICONS[provenance]}
      </span>
      <span className="provenance-label">{text}</span>
      {showDescription && (
        <span className="provenance-description">{DESCRIPTIONS[provenance]}</span>
      )}
    </span>
  );
}

export { LABELS as PROVENANCE_LABELS, DESCRIPTIONS as PROVENANCE_DESCRIPTIONS };
