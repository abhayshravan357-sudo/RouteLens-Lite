/**
 * TopologyCanvas
 *
 * The graph half of the topology view, rendered with React Flow.
 *
 * It is loaded on demand: the renderer is a large dependency, and a reader
 * who stays on the list view should never pay for it.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  type Node,
  type Edge,
  type NodeTypes,
  type ReactFlowInstance,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';
import type {
  TopologyGraph as TopologyGraphData,
  TopologyNode,
  TopologyEdge,
  TopologyProvenance,
} from '../types/routing';
import TopologyNodeCard from './TopologyNodeCard';

const NODE_TYPES: NodeTypes = { topology: TopologyNodeCard };

export const PROVENANCE_COLORS: Record<TopologyProvenance, string> = {
  observed: '#48D597',
  inferred: '#F6C76A',
  simulated: '#9B8CFF',
  unknown: '#94A3B8',
};

/**
 * Lay the topology out in layers, left to right.
 *
 * dagre ranks the nodes so a device sits to the left of the things it
 * points at, which is the direction traffic travels. The layout is
 * deterministic: the same graph always draws the same way, so two readings
 * can be compared.
 */
export function layoutGraph(
  nodes: TopologyNode[],
  edges: TopologyEdge[]
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return positions;

  const dagreGraph = new dagre.graphlib.Graph();
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  dagreGraph.setGraph({
    rankdir: 'LR',
    nodesep: 28,
    ranksep: 90,
    marginx: 24,
    marginy: 24,
  });

  for (const node of nodes) {
    dagreGraph.setNode(node.id, { width: 190, height: 92 });
  }
  // Only relationships the backend reported constrain the layout. A
  // self-loop cannot be expressed in a layered graph, so it is skipped
  // here rather than invented away.
  for (const edge of edges) {
    if (edge.source === edge.target) continue;
    dagreGraph.setEdge(edge.source, edge.target);
  }

  dagre.layout(dagreGraph);

  for (const node of nodes) {
    const laid = dagreGraph.node(node.id);
    if (laid) {
      positions.set(node.id, { x: laid.x, y: laid.y });
    }
  }

  // A node dagre could not place still has to appear. It is given its own
  // row rather than dropped.
  let orphanY = 0;
  for (const node of nodes) {
    if (positions.has(node.id)) continue;
    positions.set(node.id, { x: 120, y: orphanY });
    orphanY += 130;
  }

  return positions;
}

interface TopologyCanvasProps {
  graph: TopologyGraphData;
  selectedNodeId: string | null;
  selectedEdgeKey: string | null;
  /** Node and edge ids that belong to the current selection. */
  highlightedIds: Set<string>;
  highlightedEdgeKeys: Set<string>;
  /** The devices the traced packet actually visited. */
  pathNodeIds: Set<string>;
  pathEdgeKeys: Set<string>;
  onNodeSelect: (nodeId: string) => void;
  onEdgeSelect: (edgeKey: string) => void;
  onPaneClick: () => void;
}

export default function TopologyCanvas({
  graph,
  selectedNodeId,
  selectedEdgeKey,
  highlightedIds,
  highlightedEdgeKeys,
  pathNodeIds,
  pathEdgeKeys,
  onNodeSelect,
  onEdgeSelect,
  onPaneClick,
}: TopologyCanvasProps) {
  const container = useRef<HTMLDivElement>(null);
  const instance = useRef<ReactFlowInstance | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);

  // The canvas is measured so the whole graph is only fitted when there is
  // room for it. On a narrow screen the graph is shown at a readable zoom
  // and the reader pans, rather than being shrunk until the labels are
  // unreadable.
  useEffect(() => {
    const element = container.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width ?? 0;
      setContainerWidth((current) =>
        Math.abs(current - width) > 8 ? width : current
      );
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Once the width is known, fit the whole graph if it can be shown at a
  // readable size. Fitting happens here rather than through the `fitView`
  // prop because that prop applies on first render, before the canvas has
  // been measured.
  useEffect(() => {
    if (containerWidth === 0) return;
    if (containerWidth >= 720) {
      instance.current?.fitView({ padding: 0.2, maxZoom: 1 });
    } else {
      instance.current?.setViewport({ x: 12, y: 12, zoom: 0.78 });
    }
  }, [containerWidth]);

  const positions = useMemo(
    () => layoutGraph(graph.nodes, graph.edges),
    [graph]
  );

  const nodes: Node[] = useMemo(
    () =>
      graph.nodes.map((node) => {
        const highlighted = highlightedIds.has(node.id);
        const onPath = pathNodeIds.has(node.id);
        // A path node is never dimmed by a selection elsewhere, because
        // the path is the answer to a different question.
        const dimmed =
          highlightedIds.size > 0 && !highlighted && !onPath;
        return {
          id: node.id,
          type: 'topology',
          position: positions.get(node.id) ?? { x: 0, y: 0 },
          data: { node, dimmed, onPath },
          selected: selectedNodeId === node.id,
          draggable: true,
        };
      }),
    [graph, positions, highlightedIds, pathNodeIds, selectedNodeId]
  );

  const edges: Edge[] = useMemo(
    () =>
      graph.edges.map((edge, index) => {
        const key = `${edge.source}-${edge.target}-${index}`;
        const highlighted = highlightedEdgeKeys.has(key);
        const onPath = pathEdgeKeys.has(key);
        const dimmed = highlightedIds.size > 0 && !highlighted && !onPath;
        const isSelected = selectedEdgeKey === key;
        return {
          id: key,
          source: edge.source,
          target: edge.target,
          label: edge.label,
          className: `tedge prov-${edge.provenance} ${
            dimmed ? 'dimmed' : ''
          } ${isSelected ? 'selected' : ''} ${onPath ? 'on-path' : ''}`,
          style: {
            stroke: PROVENANCE_COLORS[edge.provenance],
            strokeWidth: onPath ? 3.5 : isSelected ? 3 : 2,
            strokeDasharray:
              edge.provenance === 'inferred'
                ? '8 4'
                : edge.provenance === 'simulated'
                ? '3 4'
                : undefined,
            opacity: dimmed ? 0.18 : 1,
          },
          labelStyle: {
            fill: onPath ? 'var(--shining)' : 'var(--color-text-muted)',
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            fontWeight: onPath ? 700 : 400,
          },
          labelBgStyle: { fill: 'var(--color-bg)', fillOpacity: 0.9 },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 3,
        };
      }),
    [graph, highlightedIds, highlightedEdgeKeys, pathEdgeKeys, selectedEdgeKey]
  );

  return (
    <div className="topology-canvas" ref={container}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodeClick={(_, node) => onNodeSelect(node.id)}
        onEdgeClick={(_, edge) => onEdgeSelect(edge.id)}
        onPaneClick={onPaneClick}
        onInit={(flow) => {
          instance.current = flow;
        }}
        defaultViewport={{ x: 12, y: 12, zoom: 0.78 }}
        minZoom={0.25}
        maxZoom={2}
        nodesDraggable
        nodesConnectable={false}
        elementsSelectable
        aria-label="Network topology graph"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={22}
          size={1}
          color="rgba(138, 216, 255, 0.12)"
        />
        <Controls showInteractive={false} className="topology-controls" />
        <MiniMap
          pannable
          zoomable
          className="topology-minimap"
          nodeColor={(node) => {
            const topologyNode = node.data?.node as TopologyNode | undefined;
            return topologyNode
              ? PROVENANCE_COLORS[topologyNode.provenance]
              : '#94A3B8';
          }}
          maskColor="rgba(11, 16, 32, 0.72)"
        />
      </ReactFlow>
    </div>
  );
}
