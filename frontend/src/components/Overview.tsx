/**
 * Overview
 *
 * The first thing a student sees, answering the questions they would
 * otherwise have to hunt for:
 *
 *   1. What network am I exploring?
 *   2. Which devices and routes are involved?
 *   3. Was my last packet journey successful?
 *   4. If it failed, where and why?
 *   5. What can I try next?
 *
 * Every figure here comes from a real measurement or a real
 * simulation, and says which. Nothing is decorative.
 */

import { useEffect, useState } from 'react';
import {
  fetchInterfaces,
  fetchNetworkRoutes,
  fetchNeighbors,
  fetchScenarioTopology,
} from '../api/routing';
import type {
  NetworkInterface,
  NetworkRoute,
  NetworkNeighbor,
  Scenario,
  ScenarioTrace,
  TopologyGraph,
} from '../types/routing';
import ProvenanceBadge from './ProvenanceBadge';
import './Overview.css';

interface OverviewProps {
  /** The scenario the student is working in, if any. */
  scenario: Scenario | null;
  /** The most recent scenario trace, if any. */
  trace: ScenarioTrace | null;
  /** The most recent legacy packet journey, if any. */
  legacyJourney: { success: boolean; hops: unknown[] } | null;
  /** The route the student last looked up. */
  lookupResult: { route: { destination: string } | null } | null;
  /** Navigation handler to jump directly to a view and optional scenario. */
  onNavigate?: (
    view: 'journey' | 'routing' | 'kernel' | 'diagnostics' | 'discovery' | 'learning',
    scenarioId?: string
  ) => void;
}

interface HostSnapshot {
  interfaces: NetworkInterface[];
  routes: NetworkRoute[];
  neighbors: NetworkNeighbor[];
  topology: TopologyGraph | null;
  error: string | null;
}

export default function Overview({
  scenario,
  trace,
  legacyJourney,
  lookupResult,
  onNavigate,
}: OverviewProps) {
  const [host, setHost] = useState<HostSnapshot>({
    interfaces: [],
    routes: [],
    neighbors: [],
    topology: null,
    error: null,
  });

  // Take one reading of the host, so the numbers are a snapshot with a
  // time attached rather than a running count that drifts.
  useEffect(() => {
    let cancelled = false;

    const read = async () => {
      try {
        const [interfaces, routes, neighbors] = await Promise.all([
          fetchInterfaces(),
          fetchNetworkRoutes(),
          fetchNeighbors(),
        ]);
        if (cancelled) return;
        setHost({
          interfaces: interfaces.data ?? [],
          routes: routes.data ?? [],
          neighbors: neighbors.data ?? [],
          topology: null,
          error: null,
        });
      } catch (err) {
        if (!cancelled) {
          setHost((prev) => ({
            ...prev,
            error: err instanceof Error ? err.message : 'Could not read the host',
          }));
        }
      }
    };

    read();

    if (scenario) {
      fetchScenarioTopology(scenario.id)
        .then((topology) => {
          if (!cancelled) setHost((prev) => ({ ...prev, topology }));
        })
        .catch(() => {
          /* The topology is a bonus; the rest still stands without it. */
        });
    }

    return () => {
      cancelled = true;
    };
  }, [scenario]);

  // Which network is this?
  const primaryInterface = host.interfaces.find(
    (i) => i.state === 'UP' && i.ipv4_addresses.length > 0
  );
  const primaryAddress = primaryInterface?.ipv4_addresses[0] ?? null;
  const primaryNetwork = primaryInterface?.ipv4_networks[0] ?? null;

  const gateway = host.routes.find((r) => r.destination === '0.0.0.0/0');
  const defaultRoute = host.routes.find((r) => r.destination === '::/0');

  // What happened on the last journey?
  const lastOutcome = trace
    ? { kind: 'trace' as const, status: trace.status, hops: trace.hops.length }
    : legacyJourney
    ? {
        kind: 'legacy' as const,
        status: legacyJourney.success ? 'delivered' : 'failed',
        hops: legacyJourney.hops.length,
      }
    : null;

  const failed = lastOutcome && lastOutcome.status !== 'delivered';

  // Where did it stop?
  const failureHop =
    failed && trace
      ? trace.hops[trace.hops.length - 1]
      : failed && legacyJourney
      ? null
      : null;

  return (
    <div className="overview">
      {/* ─── Clear Starting Point Hub ─── */}
      <section className="overview-hub" aria-label="Starting Points">
        <div className="overview-hub-header">
          <span className="hub-tag">Interactive Networking Workbench</span>
          <h2>What would you like to do?</h2>
          <p className="hub-subtitle">
            Choose a starting point below. The first two paths use a safe simulation; the last reads the machine running this backend.
          </p>
        </div>

        <div className="overview-hub-cards">
          {/* Card 1: Explore a Network */}
          <div
            className="hub-card explore"
            onClick={() => onNavigate?.('journey', 'client-router-server')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') onNavigate?.('journey', 'client-router-server');
            }}
          >
            <div className="hub-card-icon" aria-hidden="true">🌐</div>
            <div className="hub-card-badge simulated">Network Lab • Explore</div>
            <h3>Explore a Network</h3>
            <p>
              Start with a sample network, enter a destination IP, then inspect the route selected at every hop. No real packet is sent.
            </p>
            <div className="hub-card-action">
              <span>Start Exploring</span> ➔
            </div>
          </div>

          {/* Card 2: Troubleshoot a Broken Network */}
          <div
            className="hub-card troubleshoot"
            onClick={() => onNavigate?.('journey', 'challenge-broken-gateway')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') onNavigate?.('journey', 'challenge-broken-gateway');
            }}
          >
            <div className="hub-card-icon" aria-hidden="true">🛠️</div>
            <div className="hub-card-badge challenge">Network Lab • Hands-On</div>
            <h3>Troubleshoot a Broken Network</h3>
            <p>
              Try a prepared broken scenario, trace where delivery stops, then use the lab to test a change separately from your host.
            </p>
            <div className="hub-card-action">
              <span>Start Troubleshooting</span> ➔
            </div>
          </div>

          {/* Card 3: Inspect My Real Network */}
          <div
            className="hub-card live"
            onClick={() => onNavigate?.('kernel')}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') onNavigate?.('kernel');
            }}
          >
            <div className="hub-card-icon" aria-hidden="true">🖥️</div>
            <div className="hub-card-badge live">Live Host • Read-Only</div>
            <h3>Inspect My Real Network</h3>
            <p>
              Read routes, interfaces, and neighbours from the machine running the backend. It cannot automatically inspect this browser’s computer when hosted remotely.
            </p>
            <div className="hub-card-action">
              <span>View Host Routes</span> ➔
            </div>
          </div>
        </div>
      </section>

      <div className="overview-grid">
        {/* 1. What network am I exploring? */}
        <section className="overview-card">
          <h3>What am I looking at?</h3>
          {host.error ? (
            <p className="overview-error">Could not read this machine: {host.error}</p>
          ) : primaryAddress ? (
            <dl className="overview-facts">
              <div>
                <dt>This machine</dt>
                <dd className="mono">{primaryAddress}</dd>
              </div>
              {primaryNetwork && (
                <div>
                  <dt>Its network</dt>
                  <dd className="mono">{primaryNetwork}</dd>
                </div>
              )}
              {primaryInterface && (
                <div>
                  <dt>Interface</dt>
                  <dd className="mono">
                    {primaryInterface.name} (MTU {primaryInterface.mtu})
                  </dd>
                </div>
              )}
              {gateway && (
                <div>
                  <dt>Default gateway</dt>
                  <dd className="mono">
                    {gateway.gateway ?? 'none'} via {gateway.interface}
                  </dd>
                </div>
              )}
              {defaultRoute && (
                <div>
                  <dt>IPv6 default route</dt>
                  <dd className="mono">
                    {defaultRoute.gateway ?? 'none'} via {defaultRoute.interface}
                  </dd>
                </div>
              )}
            </dl>
          ) : (
            <p className="overview-muted">
              No interface with an address was found on this machine.
            </p>
          )}
          <p className="overview-source">
            <ProvenanceBadge provenance="observed" size="small" /> read from this
            machine
          </p>
        </section>

        {/* 2. Which devices and routes are involved? */}
        <section className="overview-card">
          <h3>What is on this network?</h3>
          <dl className="overview-facts">
            <div>
              <dt>Interfaces</dt>
              <dd>{host.interfaces.length}</dd>
            </div>
            <div>
              <dt>Routes</dt>
              <dd>{host.routes.length}</dd>
            </div>
            <div>
              <dt>Neighbours seen</dt>
              <dd>{host.neighbors.length}</dd>
            </div>
            {host.topology && (
              <div>
                <dt>Scenario devices</dt>
                <dd>
                  {host.topology.nodes.filter((n) => n.provenance === 'simulated').length}
                </dd>
              </div>
            )}
          </dl>

          {host.neighbors.length > 0 && (
            <div className="overview-neighbors">
              <h4>Neighbours that answered</h4>
              <ul>
                {host.neighbors.slice(0, 6).map((neighbor) => (
                  <li key={`${neighbor.ip_address}-${neighbor.interface}`}>
                    <span className="mono">{neighbor.ip_address}</span>
                    <span className="overview-neighbor-meta">
                      {neighbor.state}
                      {neighbor.is_router ? ' · router' : ''}
                    </span>
                  </li>
                ))}
              </ul>
              {host.neighbors.length > 6 && (
                <p className="overview-muted">
                  and {host.neighbors.length - 6} more
                </p>
              )}
            </div>
          )}

          <p className="overview-source">
            <ProvenanceBadge provenance="observed" size="small" /> measured ·{' '}
            <ProvenanceBadge provenance="inferred" size="small" /> relationships
            worked out from it
          </p>
        </section>

        {/* 3, 4. Was the last journey successful, and if not where? */}
        <section className="overview-card">
          <h3>How did the last packet go?</h3>
          {!lastOutcome ? (
            <p className="overview-muted">
              No packet has been traced yet. Open <strong>Packet Journey</strong>{' '}
              and send one.
            </p>
          ) : (
            <>
              <div
                className={`overview-outcome ${failed ? 'failed' : 'succeeded'}`}
              >
                <span className="overview-outcome-label">
                  {failed ? 'Did not arrive' : 'Arrived'}
                </span>
                <span className="overview-outcome-detail">
                  {lastOutcome.hops} hop{lastOutcome.hops === 1 ? '' : 's'} ·{' '}
                  {lastOutcome.status}
                </span>
              </div>

              {failureHop && (
                <div className="overview-failure">
                  <h4>It stopped at {failureHop.node}</h4>
                  <p>{failureHop.explanation}</p>
                </div>
              )}

              <p className="overview-source">
                <ProvenanceBadge provenance="simulated" size="small" /> the engine
                traced this path
              </p>
            </>
          )}
        </section>

        {/* 5. What can I try next? */}
        <section className="overview-card overview-card-wide">
          <h3>What can I try next?</h3>
          <ul className="overview-next">
            {lookupResult?.route ? (
              <li>
                You looked up <code>{lookupResult.route.destination}</code>. Trace
                that same address in <strong>Packet Journey</strong> to watch a
                router make that decision step by step.
              </li>
            ) : (
              <li>
                Look up an address in <strong>Routing Analyzer</strong>, then
                trace it in <strong>Packet Journey</strong> to see which route
                wins and why.
              </li>
            )}
            {failed && (
              <li>
                Your last packet was dropped. The Learning Lab has an
                exercise for exactly this: remove the route and watch it
                fail, then put a more specific one in and watch it work.
              </li>
            )}
            {host.neighbors.length === 0 && (
              <li>
                No neighbours are visible. Check <strong>Network Diagnostics</strong>;
                a silent network is a normal result, not an error.
              </li>
            )}
            {host.routes.length > 0 && host.routes.length < 3 && (
              <li>
                Only {host.routes.length} route
                {host.routes.length === 1 ? '' : 's'} on this machine. The
                Routes tab shows which ones.
              </li>
            )}
            <li>
              The Discovery tab finds hosts on a network you have permission
              to scan. It asks you to confirm the scope first.
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
