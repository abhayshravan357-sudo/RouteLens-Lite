/**
 * DecisionChain
 *
 * The route lookup, drawn as a signal path: the address you asked about,
 * the prefix that won, the next hop it forwards to, the interface it
 * leaves by, and what the router finally does.
 *
 * Every node is a real value from the lookup response. If a value is
 * missing, the node says so rather than being hidden.
 */

import type { RouteLookupResult } from '../types/routing';
import './DecisionChain.css';

interface DecisionChainProps {
  result: RouteLookupResult | null;
  /** The address the student typed, which may differ from the matched prefix. */
  queriedAddress: string | null;
}

interface ChainNode {
  key: string;
  label: string;
  value: string;
  /** The final node is the outcome rather than another hop. */
  terminal?: boolean;
  failed?: boolean;
}

export default function DecisionChain({
  result,
  queriedAddress,
}: DecisionChainProps) {
  if (!result) return null;

  const route = result.route;

  const nodes: ChainNode[] = [
    {
      key: 'queried',
      label: 'Queried',
      value: queriedAddress ?? '—',
    },
  ];

  if (result.matched && route) {
    nodes.push({
      key: 'prefix',
      label: 'Winning prefix',
      value: route.destination,
    });
    nodes.push({
      key: 'nexthop',
      label: 'Next hop',
      value: route.next_hop ?? 'directly connected',
    });
    nodes.push({
      key: 'interface',
      label: 'Out interface',
      value: route.interface,
    });
    nodes.push({
      key: 'action',
      label: 'Action',
      value:
        route.next_hop_type === 'direct'
          ? 'Deliver locally'
          : 'Forward to next hop',
      terminal: true,
    });
  } else {
    nodes.push({
      key: 'action',
      label: 'Action',
      value: 'No route covers this address',
      terminal: true,
      failed: true,
    });
  }

  return (
    <div className="decision-chain" role="group" aria-label="Routing decision path">
      <div className="eyebrow eyebrow-lit decision-chain-eyebrow">
        Decision chain
      </div>

      <ol className="decision-chain-track">
        {nodes.map((node, index) => (
          <li
            key={node.key}
            className={`chain-node ${node.terminal ? 'terminal' : ''} ${
              node.failed ? 'failed' : ''
            } ${index === nodes.length - 1 ? 'last' : ''}`}
          >
            <span className="chain-node-label">{node.label}</span>
            <span className="chain-node-value">{node.value}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
