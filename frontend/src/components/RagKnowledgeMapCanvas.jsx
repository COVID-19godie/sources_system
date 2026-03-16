import { useMemo } from "react";

const ZOOM_LABELS = ["总览", "章节", "知识点", "资源"];

function colorForSector(node) {
  return node?.meta?.color || "#64748b";
}

function labelForNode(node) {
  return node.keyword_label || node.label || node.id;
}

function subtitleForNode(node) {
  if (node.node_type === "sector") {
    return `${node.meta?.exam_point_count || 0} 考点 / ${node.meta?.experiment_count || 0} 实验`;
  }
  const groups = [
    ...(node.meta?.knowledge_tags || []),
    ...(node.meta?.exam_tags || []),
    ...(node.meta?.focus_tags || []),
  ];
  return groups.slice(0, 2).join(" · ");
}

function nodeRadius(node) {
  if (node.node_type === "root") return 44;
  if (node.node_type === "sector") return 34;
  if (node.node_type === "chapter") return 22;
  if (node.node_type === "knowledge_point") return 15;
  if (node.node_type === "resource") return 10;
  return 12;
}

function isLabelVisible(node, zoomLevel, selectedNodeId) {
  if (node.id === selectedNodeId) return true;
  if (node.node_type === "root" || node.node_type === "sector") return true;
  if (zoomLevel >= 2 && node.node_type === "chapter") return true;
  if (zoomLevel >= 3 && node.node_type === "knowledge_point") return true;
  return false;
}

export default function RagKnowledgeMapCanvas({
  mapData,
  loading = false,
  selectedNodeId = "",
  zoomLevel = 0,
  onZoomChange,
  onSelectNode,
  onFocusNode,
}) {
  const nodes = mapData?.visible_nodes || [];
  const edges = mapData?.visible_edges || [];
  const nodeMap = useMemo(() => {
    const next = new Map();
    nodes.forEach((node) => next.set(node.id, node));
    return next;
  }, [nodes]);

  return (
    <section className="card rag-knowledge-map">
      <div className="rag-knowledge-map-head">
        <div>
          <h3>GraphRAG 知识地图</h3>
          <p className="hint">默认只显示高中物理和五大板块，继续放大或聚焦后才展开章节、知识点与资源。</p>
        </div>
        <div className="rag-map-level-box">
          <button type="button" onClick={() => onZoomChange?.(Math.max(0, zoomLevel - 1))}>
            -
          </button>
          <strong>{ZOOM_LABELS[zoomLevel] || `L${zoomLevel}`}</strong>
          <button type="button" onClick={() => onZoomChange?.(Math.min(3, zoomLevel + 1))}>
            +
          </button>
        </div>
      </div>

      <div className="rag-map-breadcrumbs">
        <button type="button" className="ghost" onClick={() => onFocusNode?.(null, 0)}>
          高中物理
        </button>
        {(mapData?.breadcrumbs || []).map((item) => (
          <button
            key={item.id}
            type="button"
            className="ghost"
            onClick={() => onFocusNode?.(item.id, Number(item.layer || 0) + 1)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="rag-map-stage">
        {loading ? <div className="rag-map-loading">地图加载中...</div> : null}
        <svg viewBox="-420 -320 840 640" className="rag-map-svg" role="img" aria-label="GraphRAG knowledge map">
          <defs>
            <filter id="ragMapGlow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {edges.map((edge) => {
            const source = nodeMap.get(edge.source);
            const target = nodeMap.get(edge.target);
            if (!source || !target) return null;
            const isPrimary = edge.edge_type === "contains";
            return (
              <line
                key={`${edge.source}-${edge.target}-${edge.edge_type}`}
                x1={source.position.x}
                y1={source.position.y}
                x2={target.position.x}
                y2={target.position.y}
                className={`rag-map-edge ${isPrimary ? "is-primary" : "is-related"}`}
                strokeWidth={isPrimary ? 1.6 : Math.max(1, Math.min(2.8, edge.weight || 1))}
              />
            );
          })}

          {nodes.map((node) => {
            const radius = nodeRadius(node);
            const selected = selectedNodeId === node.id;
            const clickable = node.is_expandable || node.node_type === "resource";
            const subtitle = subtitleForNode(node);
            return (
              <g
                key={node.id}
                transform={`translate(${node.position.x},${node.position.y})`}
                className={`rag-map-node rag-map-node-${node.node_type} ${selected ? "is-selected" : ""} ${clickable ? "is-clickable" : ""}`}
                onClick={() => onSelectNode?.(node)}
              >
                {node.node_type === "sector" ? (
                  <circle r={radius + 14} className="rag-map-sector-halo" style={{ fill: colorForSector(node) }} />
                ) : null}
                <circle
                  r={radius}
                  className="rag-map-node-core"
                  style={{ fill: node.node_type === "root" ? "#0f172a" : colorForSector(node) }}
                  filter={selected ? "url(#ragMapGlow)" : undefined}
                />
                {node.node_type === "resource" ? <circle r={radius + 4} className="rag-map-resource-ring" /> : null}
                {isLabelVisible(node, zoomLevel, selectedNodeId) ? (
                  <>
                    <text className={`rag-map-label rag-map-label-${node.node_type}`} textAnchor="middle" y={radius + 22}>
                      {labelForNode(node)}
                    </text>
                    {subtitle ? (
                      <text className="rag-map-subtitle" textAnchor="middle" y={radius + 38}>
                        {subtitle}
                      </text>
                    ) : null}
                  </>
                ) : null}
                {node.node_type === "sector" ? (
                  <text className="rag-map-count" textAnchor="middle" y="6">
                    {(node.meta?.chapter_count || 0) + " 章"}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>

      <div className="rag-map-footer">
        <div className="rag-map-legend">
          {nodes
            .filter((node) => node.node_type === "sector")
            .map((node) => (
              <button key={node.id} type="button" className="rag-map-legend-item" onClick={() => onFocusNode?.(node.id, 1)}>
                <span className="rag-map-legend-dot" style={{ background: colorForSector(node) }}></span>
                <span>{node.label}</span>
                <small>{node.meta?.exam_point_count || 0} 考点 / {node.meta?.experiment_count || 0} 实验</small>
                <strong>{node.meta?.resource_count || 0}</strong>
              </button>
            ))}
        </div>
        <div className="rag-map-actions">
          <button type="button" className="ghost" onClick={() => onFocusNode?.(null, 0)}>
            重置视图
          </button>
        </div>
      </div>
    </section>
  );
}
