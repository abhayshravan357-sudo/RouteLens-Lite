/**
 * CountUp
 *
 * A number that counts up to its value when it first appears.
 *
 * This is a reveal, not a claim. It is only used for figures that were
 * measured and are already on screen when the animation starts — never for
 * anything that implies traffic happened or a measurement is running.
 *
 * Readers who ask for reduced motion get the final value immediately.
 */

import { useEffect, useRef, useState } from 'react';

interface CountUpProps {
  value: number;
  /** How long the count takes, in milliseconds. */
  duration?: number;
  /** Rendered instead of the number when there is no value. */
  fallback?: string;
  className?: string;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  );
}

export default function CountUp({
  value,
  duration = 620,
  fallback = '—',
  className,
}: CountUpProps) {
  const [display, setDisplay] = useState(() => (prefersReducedMotion() ? value : 0));
  const frame = useRef<number | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    if (prefersReducedMotion() || !Number.isFinite(value)) {
      setDisplay(value);
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const elapsed = now - start;
      const progress = Math.min(1, elapsed / duration);
      // Ease out, so the number settles rather than stopping dead.
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(value * eased));
      if (progress < 1) {
        frame.current = requestAnimationFrame(tick);
      }
    };

    frame.current = requestAnimationFrame(tick);
    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [value, duration]);

  if (!Number.isFinite(value)) {
    return <span className={className}>{fallback}</span>;
  }

  return (
    <span className={className} aria-label={String(value)}>
      {display.toLocaleString()}
    </span>
  );
}
