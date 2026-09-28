// Erstellt mit Unterstuetzung von Claude Code (Anthropic).
"use client";

import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MarkerType,
  Position,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "@dagrejs/dagre";
import type { ChainFlow, ChainNode } from "@/lib/types";

const TASK_BREITE = 260;
const GATEWAY_BREITE = 240;
const GATEWAY_HOEHE = 150;
const CONTAINER_MAX_HOEHE = 1000;

// Grobe Hoehenschaetzung eines Knotens aus seiner Textlaenge, damit dagre die
// vertikalen Abstaende realistisch plant und sich Knoten mit langen,
// mehrzeiligen action-Texten nicht ueberlappen.
function schaetzeHoehe(n: ChainNode): number {
  if (n.type === "gateway") return GATEWAY_HOEHE;
  const text = n.action ?? n.label ?? "";
  const zeichenProZeile = Math.max(1, Math.floor((TASK_BREITE - 24) / 7.2));
  const zeilen = Math.max(1, Math.ceil(text.length / zeichenProZeile));
  const actorZeile = n.actor ? 18 : 0;
  return Math.max(64, zeilen * 19 + actorZeile + 24);
}

function berechneLayout(nodes: ChainNode[], flows: ChainFlow[]) {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: "TB", nodesep: 70, ranksep: 100 });

  const groessen = new Map<string, { width: number; height: number }>();
  for (const n of nodes) {
    const width = n.type === "gateway" ? GATEWAY_BREITE : TASK_BREITE;
    const height = schaetzeHoehe(n);
    groessen.set(n.id, { width, height });
    graph.setNode(n.id, { width, height });
  }
  for (const f of flows) {
    if (graph.hasNode(f.from) && graph.hasNode(f.to)) {
      graph.setEdge(f.from, f.to);
    }
  }

  dagre.layout(graph);

  const positionen = new Map<string, { x: number; y: number }>();
  for (const n of nodes) {
    const p = graph.node(n.id);
    const g = groessen.get(n.id)!;
    if (p) {
      positionen.set(n.id, { x: p.x - g.width / 2, y: p.y - g.height / 2 });
    }
  }

  const { width = 0, height = 0 } = graph.graph();
  return { positionen, groessen, graphBreite: width, graphHoehe: height };
}

export default function ChainFlowDiagram({
  nodes,
  flows,
}: {
  nodes: ChainNode[];
  flows: ChainFlow[];
}) {
  const { rfNodes, rfEdges, containerHoehe } = useMemo(() => {
    const { positionen, groessen, graphHoehe } = berechneLayout(nodes, flows);

    const rfNodes: Node[] = nodes.map((n) => {
      const istGateway = n.type === "gateway";
      const g = groessen.get(n.id)!;
      return {
        id: n.id,
        position: positionen.get(n.id) ?? { x: 0, y: 0 },
        data: {
          label: istGateway ? (
            <div className="px-2 text-center text-xs font-medium leading-tight">
              {n.label ?? "?"}
            </div>
          ) : (
            <div className="text-left text-sm leading-tight">
              <div className="font-medium">{n.action ?? n.label}</div>
              {n.actor && (
                <div className="mt-1 text-xs text-gray-500">
                  {n.actor}
                  {n.recipient ? ` → ${n.recipient}` : ""}
                </div>
              )}
            </div>
          ),
        },
        style: {
          width: g.width,
          height: g.height,
          borderRadius: istGateway ? 0 : 10,
          clipPath: istGateway
            ? "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)"
            : undefined,
          background: istGateway ? "#fef3c7" : "#eef2ff",
          border: istGateway ? "2px solid #d97706" : "1px solid #4f46e5",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: istGateway ? 24 : 12,
          boxSizing: "border-box",
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
      };
    });

    const rfEdges: Edge[] = flows
      .filter((f) => nodes.some((n) => n.id === f.from) && nodes.some((n) => n.id === f.to))
      .map((f, i) => ({
        id: `e${i}-${f.from}-${f.to}`,
        source: f.from,
        target: f.to,
        label: f.condition,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#6366f1" },
        labelStyle: { fontSize: 11, fill: "#4b5563" },
        labelBgStyle: { fill: "#f9fafb" },
      }));

    const containerHoehe = Math.min(
      CONTAINER_MAX_HOEHE,
      Math.max(360, graphHoehe + 80)
    );

    return { rfNodes, rfEdges, containerHoehe };
  }, [nodes, flows]);

  if (nodes.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-gray-300 text-gray-500">
        Keine Knoten in dieser Aktionskette (kein erkennbarer Ablauf).
      </div>
    );
  }

  return (
    <div
      style={{ height: containerHoehe }}
      className="rounded-lg border border-gray-200 bg-white"
    >
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
