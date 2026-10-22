/**
 * AppShell
 *
 * The frame around the whole application: a navigation sidebar, a top bar
 * that says where you are and whether the backend is answering, and the
 * scrolling workspace.
 *
 * Navigation entries map to real features. There are no decorative links.
 */

import { useEffect, useState } from 'react';
import {
  IconOverview,
  IconRoutes,
  IconJourney,
  IconLab,
  IconDiagnostics,
  IconLearning,
  IconMenu,
  IconChevronLeft,
  IconRefresh,
  IconMark,
  IconKernel,
} from './Icons';
import './AppShell.css';

export type ViewId =
  | 'overview'
  | 'routing'
  | 'kernel'
  | 'journey'
  | 'lab'
  | 'diagnostics'
  | 'discovery'
  | 'learning';

/**
 * The mark for the router map: three devices joined by two links.
 *
 * It lives here rather than in the shared Icons module because this view
 * owns it, and the two features — the ICMP host sweep and the router map —
 * must not be mistaken for one another.
 */
function IconRouterMap({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
    >
      <rect x="1.8" y="3.5" width="6" height="5" rx="1.2" />
      <rect x="1.8" y="15.5" width="6" height="5" rx="1.2" />
      <rect x="16.2" y="9.5" width="6" height="5" rx="1.2" />
      <path d="M7.8 6h3.4a2 2 0 0 1 2 2v1.5" />
      <path d="M7.8 18h3.4a2 2 0 0 0 2-2v-1.5" />
    </svg>
  );
}

export interface ViewDefinition {
  id: ViewId;
  label: string;
  title: string;
  description: string;
  icon: (props: { size?: number }) => React.ReactElement;
}

export const VIEWS: ViewDefinition[] = [
  {
    id: 'overview',
    label: 'Overview',
    title: 'Overview',
    description: 'What this machine is on, what it can see, and what to try next.',
    icon: IconOverview,
  },
  {
    id: 'routing',
    label: 'Routing Analyzer',
    title: 'Routing Analyzer',
    description: 'Inspect the routing table and look up the best route for an address.',
    icon: IconRoutes,
  },
  {
    id: 'kernel',
    label: 'Kernel Table',
    title: 'Kernel Table',
    description: 'The routing table this machine actually holds, and what it would do.',
    icon: IconKernel,
  },
  {
    id: 'journey',
    label: 'Packet Journey',
    title: 'Packet Journey',
    description: 'Send a packet through a network and watch every forwarding decision.',
    icon: IconJourney,
  },
  {
    id: 'lab',
    label: 'Virtual Lab',
    title: 'Virtual Lab',
    description: 'The isolated client, router and server, and what the lab reports.',
    icon: IconLab,
  },
  {
    id: 'diagnostics',
    label: 'Network Diagnostics',
    title: 'Network Diagnostics',
    description: 'Read the live state of this host: interfaces, routes, neighbours, DNS, traceroute.',
    icon: IconDiagnostics,
  },
  {
    id: 'discovery',
    label: 'Router Discovery',
    title: 'Router Discovery',
    description:
      'Walk a network of routers, read their tables, and see which links were observed and which were deduced.',
    icon: IconRouterMap,
  },
  {
    id: 'learning',
    label: 'Learning Lab',
    title: 'Learning Lab',
    description: 'Guided exercises checked against the real routing engine.',
    icon: IconLearning,
  },
];

interface AppShellProps {
  activeView: ViewId;
  onViewChange: (view: ViewId) => void;
  /** null while the first health check is still in flight. */
  backendOnline: boolean | null;
  /** Human-readable reason the backend could not be reached. */
  backendError: string | null;
  onRefresh: () => void;
  refreshing: boolean;
  /** Live readings shown in the instrument strip, all from real API data. */
  readouts?: InstrumentReading[];
  children: React.ReactNode;
}

export interface InstrumentReading {
  label: string;
  value: string;
  /** 'live' highlights the value; 'off' means the source is unavailable. */
  tone?: 'normal' | 'live' | 'off';
}

export default function AppShell({
  activeView,
  onViewChange,
  backendOnline,
  backendError,
  onRefresh,
  refreshing,
  readouts = [],
  children,
}: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const active = VIEWS.find((v) => v.id === activeView) ?? VIEWS[0];

  // Close the mobile drawer whenever the view changes.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [activeView]);

  // Escape closes the mobile drawer.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMobileNavOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [mobileNavOpen]);

  const healthLabel =
    backendOnline === null
      ? 'Checking'
      : backendOnline
      ? 'Backend online'
      : 'Backend offline';

  const healthClass =
    backendOnline === null
      ? 'checking'
      : backendOnline
      ? 'connected'
      : 'disconnected';

  return (
    <div className={`app ${collapsed ? 'sidebar-collapsed' : ''} ${mobileNavOpen ? 'mobile-nav-open' : ''}`}>
      <div
        className="sidebar-backdrop"
        onClick={() => setMobileNavOpen(false)}
        aria-hidden="true"
      />

      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">
            <IconMark size={17} />
            <span className="brand-pulse" />
          </span>
          <span className="brand-text">
            <span className="brand-name">RouteLens Lite</span>
            <span className="brand-tagline">Network analysis workbench</span>
          </span>
        </div>

        <nav className="sidebar-nav" aria-label="Sections">
          <span className="nav-section-label">Routing</span>
          {VIEWS.filter((v) =>
            ['overview', 'routing', 'kernel'].includes(v.id)
          ).map((view) => {
            const Icon = view.icon;
            return (
              <button
                key={view.id}
                type="button"
                className={`nav-item ${activeView === view.id ? 'active' : ''}`}
                onClick={() => {
                  // Always close the drawer, even when this view was already
                  // active, so tapping the current item is not a dead end.
                  setMobileNavOpen(false);
                  onViewChange(view.id);
                }}
                aria-current={activeView === view.id ? 'page' : undefined}
                title={collapsed ? view.label : undefined}
              >
                <span className="nav-item-icon">
                  <Icon size={17} />
                </span>
                <span className="nav-item-label">{view.label}</span>
              </button>
            );
          })}

          <span className="nav-section-label">Network</span>
          {VIEWS.filter((v) =>
            ['journey', 'lab', 'diagnostics', 'discovery'].includes(v.id)
          ).map((view) => {
            const Icon = view.icon;
            return (
              <button
                key={view.id}
                type="button"
                className={`nav-item ${activeView === view.id ? 'active' : ''}`}
                onClick={() => {
                  setMobileNavOpen(false);
                  onViewChange(view.id);
                }}
                aria-current={activeView === view.id ? 'page' : undefined}
                title={collapsed ? view.label : undefined}
              >
                <span className="nav-item-icon">
                  <Icon size={17} />
                </span>
                <span className="nav-item-label">{view.label}</span>
              </button>
            );
          })}

          <span className="nav-section-label">Practice</span>
          {VIEWS.filter((v) => v.id === 'learning').map((view) => {
            const Icon = view.icon;
            return (
              <button
                key={view.id}
                type="button"
                className={`nav-item ${activeView === view.id ? 'active' : ''}`}
                onClick={() => {
                  setMobileNavOpen(false);
                  onViewChange(view.id);
                }}
                aria-current={activeView === view.id ? 'page' : undefined}
                title={collapsed ? view.label : undefined}
              >
                <span className="nav-item-icon">
                  <Icon size={17} />
                </span>
                <span className="nav-item-label">{view.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-footer">
          <button
            type="button"
            className="sidebar-toggle"
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <IconChevronLeft size={16} />
            <span>Collapse</span>
          </button>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <button
            type="button"
            className="mobile-nav-toggle"
            onClick={() => setMobileNavOpen((o) => !o)}
            aria-label="Open navigation"
            aria-expanded={mobileNavOpen}
          >
            <IconMenu size={17} />
          </button>

          <div className="topbar-heading">
            <h1 className="topbar-title">{active.title}</h1>
            <p className="topbar-description">{active.description}</p>
          </div>

          <div className="topbar-actions">
            {readouts.length > 0 && (
              <div className="instrument-readout" aria-label="Live readings">
                {readouts.map((reading) => (
                  <span
                    key={reading.label}
                    className={`instrument-reading ${reading.tone ?? 'normal'}`}
                  >
                    <span className="instrument-reading-label">
                      {reading.label}
                    </span>
                    <span className="instrument-reading-value">
                      {reading.value}
                    </span>
                  </span>
                ))}
              </div>
            )}

            <span
              className={`status-badge ${healthClass}`}
              title={backendError ?? undefined}
              role="status"
            >
              <span className="dot" aria-hidden="true" />
              {healthLabel}
            </span>

            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={onRefresh}
              disabled={refreshing}
              aria-busy={refreshing}
              aria-label="Refresh data"
            >
              <IconRefresh size={14} />
              <span className="topbar-refresh-text">
                {refreshing ? 'Refreshing' : 'Refresh'}
              </span>
            </button>
          </div>
        </header>

        <main className="content">
          <div className="content-inner">{children}</div>
        </main>
      </div>
    </div>
  );
}
