import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";

const MAP_LABEL_ZOOM_RESOURCE = 1.6;
const MAP_LABEL_ZOOM_CONTEXT = 2.4;
const MAP_LABEL_ZOOM_IMPORTANT = 3.0;
const LABEL_MAX_LENGTH = 14;
const LABEL_CAP_L1 = 40;
const LABEL_CAP_L2 = 80;
const LABEL_CAP_L3 = 140;

function shortenLabel(raw = "") {
  const text = String(raw || "").trim();
  if (!text) {
    return "";
  }
  return text.length > LABEL_MAX_LENGTH ? `${text.slice(0, LABEL_MAX_LENGTH)}…` : text;
}

function nodeDisplayName(node) {
  return node.keyword_label || node.name || node.label || node.id || "节点";
}

function shouldShowLabel(node, globalScale, selectedNodeId, highlightNodeSet, importantSizeThreshold) {
  if (node.id === selectedNodeId || highlightNodeSet.has(node.id)) {
    return true;
  }
  if (globalScale < MAP_LABEL_ZOOM_RESOURCE) {
    return false;
  }
  if (globalScale < MAP_LABEL_ZOOM_CONTEXT) {
    return node.node_type === "resource";
  }
  if (globalScale < MAP_LABEL_ZOOM_IMPORTANT) {
    return ["resource", "chapter", "section"].includes(node.node_type);
  }
  const nodeSize = sizeForNode(node);
  const isImportantLargeNode = nodeSize >= importantSizeThreshold;
  return ["resource", "chapter", "section"].includes(node.node_type) || isImportantLargeNode;
}

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
  const base = node.node_type === "resource" ? 4.5 : node.node_type === "format" ? 6.5 : 8;
  const difficulty = node.meta?.difficulty || "";
  if (difficulty.includes("挑战")) return base + 2.5;
  if (difficulty.includes("进阶")) return base + 1.5;
  if (difficulty.includes("基础")) return base + 0.8;
  return base;
}

export default function RagGraph2DCanvas({
  graph,
  fitTrigger = 0,
  selectedNodeId,
  onSelectNode,
  highlightNodes = [],
  highlightEdges = []
}) {
  const graphRef = useRef(null);
  const hasFittedRef = useRef(false);
  const labelBudgetRef = useRef({ frameKey: "", count: 0 });
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
      name: node.keyword_label || node.label || node.id,
      shortName: shortenLabel(node.keyword_label || node.label || node.id)
    }));
    const links = (graph?.edges || []).map((edge) => ({
      ...edge,
      source: edge.source,
      target: edge.target,
      edgeKey: `${edge.source}->${edge.target}:${edge.edge_type}`
    }));
    return { nodes, links };
  }, [graph]);

  const importantSizeThreshold = useMemo(() => {
    const sizeValues = (graphData.nodes || [])
      .map((node) => sizeForNode(node))
      .sort((a, b) => b - a);
    if (!sizeValues.length) {
      return Number.POSITIVE_INFINITY;
    }
    const index = Math.max(0, Math.floor(sizeValues.length * 0.3) - 1);
    return sizeValues[index];
  }, [graphData.nodes]);

  function labelCapForScale(globalScale) {
    if (globalScale >= MAP_LABEL_ZOOM_IMPORTANT) {
      return LABEL_CAP_L3;
    }
    if (globalScale >= MAP_LABEL_ZOOM_CONTEXT) {
      return LABEL_CAP_L2;
    }
    if (globalScale >= MAP_LABEL_ZOOM_RESOURCE) {
      return LABEL_CAP_L1;
    }
    return 0;
  }

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
    <section className="card rag-graph-canvas rag-graph-canvas-2d">
      <h3>知识图谱画布（2D Canvas）</h3>
      {!graphData.nodes.length ? (
        <div className="rag-empty-canvas">当前筛选条件下暂无节点</div>
      ) : null}
      <div className="rag-2d-wrap">
        <ForceGraph2D
          ref={graphRef}
          graphData={graphData}
          width={size.width}
          height={size.height}
          backgroundColor="#f8fafc"
          nodeLabel={(node) => `${nodeDisplayName(node)}\n类型：${node.node_type || "-"}`}
          nodeColor={(node) => {
            if (node.id === selectedNodeId) return "#f59e0b";
            if (highlightNodeSet.has(node.id)) return "#22c55e";
            return colorForNode(node);
          }}
          nodeRelSize={sizeForNode({ node_type: "resource" })}
          nodeVal={(node) => sizeForNode(node)}
          linkColor={(link) => {
            if (highlightEdgeSet.has(link.edgeKey)) return "#22c55e";
            return link.edge_type === "contains" ? "rgba(59,130,246,0.34)" : "rgba(100,116,139,0.65)";
          }}
          linkWidth={(link) => {
            if (highlightEdgeSet.has(link.edgeKey)) return 2.6;
            return link.edge_type === "contains" ? 0.8 : Math.max(0.8, Math.min(2.2, (link.weight || 1) * 1.8));
          }}
          linkDirectionalParticles={(link) => (highlightEdgeSet.has(link.edgeKey) ? 1 : 0)}
          linkDirectionalParticleWidth={1.4}
          enableNodeDrag
          enablePanInteraction
          enableZoomInteraction
          enablePointerInteraction
          nodeCanvasObjectMode={() => "after"}
          nodeCanvasObject={(node, ctx, globalScale) => {
            const pinnedLabel = node.id === selectedNodeId || highlightNodeSet.has(node.id);
            const shouldShow = shouldShowLabel(
              node,
              globalScale,
              selectedNodeId,
              highlightNodeSet,
              importantSizeThreshold
            );
            if (!shouldShow) {
              return;
            }
            const label = shortenLabel(nodeDisplayName(node));
            if (!label) {
              return;
            }

            if (!pinnedLabel) {
              const bucket = globalScale >= MAP_LABEL_ZOOM_IMPORTANT
                ? "L3"
                : globalScale >= MAP_LABEL_ZOOM_CONTEXT
                  ? "L2"
                  : globalScale >= MAP_LABEL_ZOOM_RESOURCE
                    ? "L1"
                    : "L0";
              const frameKey = `${bucket}:${globalScale.toFixed(2)}`;
              if (labelBudgetRef.current.frameKey !== frameKey) {
                labelBudgetRef.current = { frameKey, count: 0 };
              }
              const cap = labelCapForScale(globalScale);
              if (labelBudgetRef.current.count >= cap) {
                return;
              }
              labelBudgetRef.current.count += 1;
            }

            const fontSize = Math.max(10, Math.min(16, 12 / globalScale));
            ctx.font = `600 ${fontSize}px "SF Pro Display", "PingFang SC", "Helvetica Neue", sans-serif`;
            const textWidth = ctx.measureText(label).width;
            const bgX = node.x + sizeForNode(node) + 2;
            const bgY = node.y - fontSize * 0.75;
            const bgW = textWidth + 10;
            const bgH = fontSize + 6;

            ctx.fillStyle = "rgba(255,255,255,0.78)";
            ctx.fillRect(bgX, bgY, bgW, bgH);
            ctx.fillStyle = "#1f2937";
            ctx.fillText(label, bgX + 5, node.y + fontSize * 0.2);
          }}
          onNodeClick={(node) => onSelectNode?.(node.id)}
          onNodeDragEnd={(node) => {
            node.fx = undefined;
            node.fy = undefined;
          }}
          cooldownTicks={110}
        />
      </div>
    </section>
  );
}
