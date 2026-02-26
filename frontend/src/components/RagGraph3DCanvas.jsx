import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D from "react-force-graph-3d";

function colorForNode(node) {
  if (node.node_type === "chapter") return "#0f766e";
  if (node.node_type === "section") return "#0369a1";
  if (node.node_type === "format") return "#334155";
  if (node.node_type === "resource") {
    const formatGroup = node.meta?.format_group;
    if (formatGroup === "ppt") return "#2563eb";
    if (formatGroup === "exercise") return "#ea580c";
    if (formatGroup === "simulation") return "#7c3aed";
    if (formatGroup === "video") return "#0f766e";
    if (formatGroup === "document") return "#475569";
    if (formatGroup === "image") return "#db2777";
    if (formatGroup === "audio") return "#0284c7";
    return "#2563eb";
  }
  if (node.node_type === "knowledge_point") return "#7c3aed";
  if (node.node_type === "formula") return "#c2410c";
  if (node.node_type === "experiment") return "#0f766e";
  if (node.node_type === "problem_type") return "#334155";
  return "#64748b";
}

function sizeForNode(node) {
  const base = node.node_type === "resource" ? 5 : node.node_type === "format" ? 7 : 9;
  const difficulty = node.meta?.difficulty || "";
  if (difficulty.includes("挑战")) return base + 3;
  if (difficulty.includes("进阶")) return base + 2;
  if (difficulty.includes("基础")) return base + 1;
  return base;
}

export default function RagGraph3DCanvas({
  graph,
  fitTrigger = 0,
  selectedNodeId,
  onSelectNode,
  highlightNodes = [],
  highlightEdges = []
}) {
  const graphRef = useRef(null);
  const hasFittedRef = useRef(false);
  const [size, setSize] = useState({ width: 960, height: 660 });
  const highlightNodeSet = useMemo(() => new Set(highlightNodes), [highlightNodes]);
  const highlightEdgeSet = useMemo(() => new Set(highlightEdges), [highlightEdges]);

  useEffect(() => {
    function resize() {
      const width = Math.max(760, Math.min(1360, window.innerWidth - 380));
      const height = Math.max(560, Math.min(880, window.innerHeight - 250));
      setSize({ width, height });
    }
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);

  const graphData = useMemo(() => {
    const nodes = (graph?.nodes || []).map((node) => ({
      ...node,
      id: node.id,
      name: node.keyword_label || node.label || node.id
    }));
    const links = (graph?.edges || []).map((edge) => ({
      ...edge,
      source: edge.source,
      target: edge.target,
      edgeKey: `${edge.source}->${edge.target}:${edge.edge_type}`
    }));
    return { nodes, links };
  }, [graph]);

  useEffect(() => {
    if (!graphData.nodes.length) {
      hasFittedRef.current = false;
      return;
    }
    if (!graphRef.current || hasFittedRef.current) {
      return;
    }
    graphRef.current.zoomToFit(450, 60);
    hasFittedRef.current = true;
  }, [graphData.nodes.length]);

  useEffect(() => {
    if (!fitTrigger || !graphRef.current || !graphData.nodes.length) {
      return;
    }
    graphRef.current.zoomToFit(450, 60);
  }, [fitTrigger, graphData.nodes.length]);

  return (
    <section className="card rag-graph-canvas rag-graph-canvas-3d">
      <h3>知识图谱画布（3D）</h3>
      {!graphData.nodes.length ? (
        <div className="rag-empty-canvas">当前筛选条件下暂无节点</div>
      ) : null}
      <div className="rag-3d-wrap">
        <ForceGraph3D
          ref={graphRef}
          graphData={graphData}
          width={size.width}
          height={size.height}
          backgroundColor="#f8fafc"
          nodeLabel={(node) => `${node.keyword_label || node.label || node.id}\n类型：${node.node_type || "-"}`}
          nodeColor={(node) => {
            if (node.id === selectedNodeId) return "#f59e0b";
            if (highlightNodeSet.has(node.id)) return "#22c55e";
            return colorForNode(node);
          }}
          nodeVal={(node) => sizeForNode(node)}
          linkColor={(link) => {
            if (highlightEdgeSet.has(link.edgeKey)) return "#22c55e";
            return link.edge_type === "contains" ? "rgba(59,130,246,0.35)" : "rgba(100,116,139,0.65)";
          }}
          linkWidth={(link) => {
            if (highlightEdgeSet.has(link.edgeKey)) return 2.8;
            return link.edge_type === "contains" ? 0.8 : Math.max(0.8, Math.min(2.2, (link.weight || 1) * 1.8));
          }}
          linkDirectionalParticles={(link) => (highlightEdgeSet.has(link.edgeKey) ? 2 : 0)}
          linkDirectionalParticleWidth={1.4}
          enableNodeDrag
          enableNavigationControls
          showNavInfo={false}
          onNodeClick={(node) => onSelectNode?.(node.id)}
          onNodeDragEnd={(node) => {
            node.fx = undefined;
            node.fy = undefined;
            node.fz = undefined;
          }}
        />
      </div>
    </section>
  );
}
