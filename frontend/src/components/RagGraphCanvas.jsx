import { useMemo } from "react";

function colorForNodeType(type) {
  if (type === "chapter") return "#0f766e";
  if (type === "section") return "#0369a1";
  if (type === "format") return "#334155";
  if (type === "resource") return "#2563eb";
  if (type === "knowledge_point") return "#7c3aed";
  if (type === "formula") return "#c2410c";
  if (type === "experiment") return "#0f766e";
  if (type === "problem_type") return "#334155";
  return "#475569";
}

function columnForNode(node) {
  if (node.node_type === "chapter") return 0;
  if (node.node_type === "section") return 1;
  if (node.node_type === "format") return 2;
  if (node.node_type === "resource") return 3;
  return 3;
}

function sortByNodeLabel(a, b) {
  return (a.keyword_label || a.label || "").localeCompare((b.keyword_label || b.label || ""), "zh-CN");
}

function shortLabel(text) {
  const value = (text || "").trim();
  if (!value) return "节点";
  return value.length > 8 ? `${value.slice(0, 8)}…` : value;
}

function buildLayeredLayout(nodes, edges) {
  const columns = [[], [], [], []];
  for (const node of nodes) {
    columns[columnForNode(node)].push(node);
  }
  columns.forEach((items) => items.sort(sortByNodeLabel));

  const positions = {};
  const xMap = [140, 380, 620, 940];
  const lineHeight = 74;

  columns.forEach((items, column) => {
    let y = 70;
    for (const node of items) {
      positions[node.id] = { x: xMap[column], y };
      y += lineHeight;
    }
  });

  const height = Math.max(680, ...Object.values(positions).map((item) => item.y + 78));
  const width = 1140;
  const visibleEdges = edges
    .map((edge) => {
      const sourcePos = positions[edge.source];
      const targetPos = positions[edge.target];
      return sourcePos && targetPos ? { ...edge, sourcePos, targetPos } : null;
    })
    .filter(Boolean);

  return { nodes, edges: visibleEdges, positions, width, height };
}

function buildRadialLayout(nodes, edges) {
  const center = { x: 620, y: 400 };
  const groups = {
    center: [],
    mid: [],
    outer: [],
    far: []
  };
  for (const node of nodes) {
    if (node.node_type === "chapter") groups.center.push(node);
    else if (node.node_type === "section") groups.mid.push(node);
    else if (node.node_type === "format") groups.outer.push(node);
    else if (node.node_type === "resource") groups.far.push(node);
    else groups.far.push(node);
  }
  Object.values(groups).forEach((items) => items.sort(sortByNodeLabel));

  const positions = {};
  const placeGroup = (items, radius) => {
    if (!items.length) return;
    const step = (Math.PI * 2) / items.length;
    items.forEach((node, index) => {
      const angle = step * index - Math.PI / 2;
      positions[node.id] = {
        x: center.x + Math.cos(angle) * radius,
        y: center.y + Math.sin(angle) * radius
      };
    });
  };

  if (groups.center.length === 1) {
    positions[groups.center[0].id] = { x: center.x, y: center.y };
  } else {
    placeGroup(groups.center, 82);
  }
  placeGroup(groups.mid, 210);
  placeGroup(groups.outer, 320);
  placeGroup(groups.far, 470);

  const visibleEdges = edges
    .map((edge) => {
      const sourcePos = positions[edge.source];
      const targetPos = positions[edge.target];
      return sourcePos && targetPos ? { ...edge, sourcePos, targetPos } : null;
    })
    .filter(Boolean);

  return {
    nodes,
    edges: visibleEdges,
    positions,
    width: 1260,
    height: 860
  };
}

export default function RagGraphCanvas({
  graph,
  selectedNodeId,
  onSelectNode,
  layoutMode = "layered",
  highlightNodes = [],
  highlightEdges = []
}) {
  const layout = useMemo(() => {
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    if (layoutMode === "radial") {
      return buildRadialLayout(nodes, edges);
    }
    return buildLayeredLayout(nodes, edges);
  }, [graph, layoutMode]);

  const highlightNodeSet = useMemo(() => new Set(highlightNodes), [highlightNodes]);
  const highlightEdgeSet = useMemo(() => new Set(highlightEdges), [highlightEdges]);

  return (
    <section className="card rag-graph-canvas">
      <h3>知识图谱画布</h3>
      <div className="rag-canvas-scroll">
        {!(layout.nodes || []).length ? (
          <div className="rag-empty-canvas">当前筛选条件下暂无节点</div>
        ) : null}
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} preserveAspectRatio="xMinYMin meet">
          {layout.edges.map((edge, index) => {
            const edgeKey = `${edge.source}->${edge.target}:${edge.edge_type}`;
            const highlighted = highlightEdgeSet.has(edgeKey);
            return (
              <line
                key={`edge-${index}`}
                x1={edge.sourcePos.x + 52}
                y1={edge.sourcePos.y}
                x2={edge.targetPos.x - 52}
                y2={edge.targetPos.y}
                className={`rag-edge ${edge.edge_type === "contains" ? "rag-edge-contains" : "rag-edge-rel"} ${highlighted ? "is-highlight" : ""}`}
                strokeWidth={edge.edge_type === "contains" ? 1.6 : Math.max(1.4, Math.min(3.4, (edge.weight || 1) * 3.2))}
              />
            );
          })}

          {layout.nodes.map((node) => {
            const pos = layout.positions[node.id];
            if (!pos) return null;
            const selected = selectedNodeId === node.id;
            const highlighted = highlightNodeSet.has(node.id);
            return (
              <g
                key={node.id}
                transform={`translate(${pos.x},${pos.y})`}
                className={`rag-node ${selected ? "is-selected" : ""} ${highlighted ? "is-highlight" : ""}`}
                onClick={() => onSelectNode(node.id)}
              >
                <rect x={-52} y={-22} width={104} height={44} rx={10} fill={colorForNodeType(node.node_type)} />
                <title>{node.label}</title>
                <text textAnchor="middle" y="5">{shortLabel(node.keyword_label || node.label)}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}
