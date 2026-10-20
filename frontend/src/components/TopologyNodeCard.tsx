/**
 * TopologyNodeCard
 *
 * A node in the topology graph. One component covers every device kind,
 * because what makes a node different from its neighbour is its kind and
 * its provenance, not its shape.
 *
 * The provenance badge is always present. A node that was simulated must
 * never be able to pass for a node that was observed.
 */

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { TopologyNode } from '../types/routing';

const KIND_LABELS: Record<TopologyNode['kind'], string> = {
  interface: 'Interface',
  gateway: 'Gateway',
  neighbor: 'Neighbour',
  router: 'Router',
  host: 'Host',
  unknown: 'Unknown',
};

const KIND_GLYPH: Record<TopologyNode['kind'], string> = {
  interface: '▤',
  gateway: '⇥',
  neighbor: '◉',
  router: '⬢',
  host: '▣',
  unknown: '○',
};

function TopologyNodeCard({ data, selected }: NodeProps) {
  const node = data.node as TopologyNode;
  const dimmed = Boolean(data.dimmed);
  const onPath = Boolean(data.onPath);

  return (
    <div
      className={`tnode tnode-${node.kind} prov-${node.provenance} ${
        selected ? 'selected' : ''
      } ${dimmed ? 'dimmed' : ''} ${onPath ? 'on-path' : ''}`}
    >
      <Handle type="target" position={Position.Left} className="tnode-handle" />
      <Handle type="source" position={Position.Right} className="tnode-handle" />

      <div className="tnode-head">
        <span className="tnode-glyph" aria-hidden="true">
          {KIND_GLYPH[node.kind]}
        </span>
        <span className="tnode-kind">{KIND_LABELS[node.kind]}</span>
        {onPath && (
          <span className="tnode-onpath" title="The traced packet passed through this device">
            on path
          </span>
        )}
      </div>

      <div className="tnode-label" title={node.label}>
        {node.label}
      </div>

      {node.addresses.length > 0 && (
        <div className="tnode-addresses">
          {node.addresses.slice(0, 2).map((address) => (
            <span className="tnode-address" key={address}>
              {address}
            </span>
          ))}
          {node.addresses.length > 2 && (
            <span className="tnode-address tnode-address-more">
              +{node.addresses.length - 2}
            </span>
          )}
        </div>
      )}

      <span className={`tnode-prov prov-${node.provenance}`}>
        {node.provenance}
      </span>
    </div>
  );
}

export default memo(TopologyNodeCard);
