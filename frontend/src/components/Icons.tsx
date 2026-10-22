/**
 * Icons
 *
 * A small inline SVG icon set. The project has no icon library and adding
 * one would be a dependency for a handful of glyphs, so these are drawn
 * here. They are all decorative by default: every icon sits next to a text
 * label, or carries its own aria-label.
 */

interface IconProps {
  size?: number;
  className?: string;
}

const base = (size: number) => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  focusable: false,
});

export function IconOverview({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="3" y="3" width="7" height="8" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="11" width="7" height="10" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

export function IconRoutes({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="5" cy="6" r="2.2" />
      <circle cx="19" cy="12" r="2.2" />
      <circle cx="5" cy="18" r="2.2" />
      <path d="M7.2 6.8 16.8 11M7.2 17.2 16.8 13" />
    </svg>
  );
}

export function IconJourney({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="5" cy="12" r="2.4" />
      <circle cx="19" cy="12" r="2.4" />
      <path d="M7.4 12h9.2" />
      <path d="m14.4 9.6 2.2 2.4-2.2 2.4" />
    </svg>
  );
}

export function IconLab({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M9 3h6" />
      <path d="M10 3v6.2L5.4 17.4A2 2 0 0 0 7.1 20.5h9.8a2 2 0 0 0 1.7-3.1L14 9.2V3" />
      <path d="M7.6 14.5h8.8" />
    </svg>
  );
}

export function IconDiagnostics({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M3 12h3.5l2.2-6 3.6 12 2.4-8 1.6 4H21" />
    </svg>
  );
}

export function IconLearning({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M12 4 2.8 8.6 12 13.2l9.2-4.6L12 4Z" />
      <path d="M6.5 10.6v4.9c0 1.6 2.5 2.9 5.5 2.9s5.5-1.3 5.5-2.9v-4.9" />
      <path d="M21.2 8.6v5.2" />
    </svg>
  );
}

export function IconMenu({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </svg>
  );
}

export function IconChevronLeft({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m14.5 5-7 7 7 7" />
    </svg>
  );
}

export function IconRefresh({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="M20 11a8 8 0 1 0-1.9 6.2" />
      <path d="M20 4.5V11h-6.2" />
    </svg>
  );
}

export function IconSearch({ size = 16, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m15.5 15.5 4 4" />
    </svg>
  );
}

export function IconCopy({ size = 13, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5" />
    </svg>
  );
}

export function IconCheck({ size = 13, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <path d="m4.5 12.5 5 5 10-11" />
    </svg>
  );
}

export function IconKernel({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className}>
      <rect x="3" y="3" width="18" height="6" rx="1.5" />
      <rect x="3" y="15" width="18" height="6" rx="1.5" />
      <path d="M7 6h.01M7 18h.01" />
      <path d="M12 9v6" />
      <path d="m9.6 12.6 2.4 2.4 2.4-2.4" />
    </svg>
  );
}

export function IconMark({ size = 18, className }: IconProps) {
  return (
    <svg {...base(size)} className={className} strokeWidth={2}>
      <circle cx="12" cy="4" r="2" />
      <circle cx="4" cy="18" r="2" />
      <circle cx="20" cy="18" r="2" />
      <path d="M11 6 5.5 16M13 6l5.5 10M6 18h12" />
    </svg>
  );
}
