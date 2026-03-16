import { useEffect, useMemo, useRef, useState } from "react";

const ZOOM_LABELS = ["总览", "板块", "章节", "知识点"];
const CAMERA_SCALE = [1, 1.14, 1.36, 1.72];
const VIEW_CENTER = { x: 0, y: 10 };
const PAN_STEP = 28;

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
  if (node.node_type === "knowledge_point") {
    return "";
  }
  if (node.meta?.path) {
    return node.meta.path;
  }
  const groups = [
    ...(node.meta?.knowledge_tags || []),
    ...(node.meta?.exam_tags || []),
    ...(node.meta?.focus_tags || []),
  ];
  return groups.slice(0, 2).join(" · ");
}

function nodeRadius(node) {
  if (node.node_type === "root") return 42;
  if (node.node_type === "sector") return 34;
  if (node.node_type === "chapter") return 20;
  if (node.node_type === "knowledge_point") return 14;
  if (node.node_type === "resource") return 9;
  return 12;
}

function isLabelVisible(node, zoomLevel, selectedNodeId, activeMarkerId) {
  if (node.id === selectedNodeId || node.id === activeMarkerId) return true;
  if (node.node_type === "root" || node.node_type === "sector") return true;
  if (zoomLevel >= 2 && node.node_type === "chapter") return true;
  if (zoomLevel >= 3 && node.node_type === "knowledge_point") return true;
  return false;
}

function markerForNode(activeMarker, nodeMap) {
  if (!activeMarker?.node_id) return null;
  const node = nodeMap.get(activeMarker.node_id);
  if (!node) return null;
  return {
    ...activeMarker,
    x: node.position.x,
    y: node.position.y,
    node,
  };
}

function nextZoomForNode(node, currentZoom) {
  if (!node) return currentZoom;
  if (node.node_type === "root") return 0;
  return Math.max(currentZoom, Math.min(3, Number(node.layer || 0) + 1));
}

export default function RagKnowledgeMapCanvas({
  mapData,
  loading = false,
  selectedNodeId = "",
  centerNodeId = "",
  navigationState = "idle",
  zoomLevel = 0,
  activeMarker = null,
  highlightPathNodes = [],
  onZoomChange,
  onSelectNode,
  onFocusNode,
  onBackTrack,
  onResetView,
}) {
  const [panOffset, setPanOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const sectionRef = useRef(null);
  const stageRef = useRef(null);
  const dragRef = useRef({
    pointerId: null,
    lastX: 0,
    lastY: 0,
  });
  const nodes = mapData?.visible_nodes || [];
  const edges = mapData?.visible_edges || [];
  const nodeMap = useMemo(() => {
    const next = new Map();
    nodes.forEach((node) => next.set(node.id, node));
    return next;
  }, [nodes]);
  const highlightSet = useMemo(() => new Set(highlightPathNodes || []), [highlightPathNodes]);
  const centerNode = nodeMap.get(centerNodeId || selectedNodeId || mapData?.focus_id || "") || null;
  const scale = CAMERA_SCALE[Math.max(0, Math.min(3, zoomLevel))] || 1;
  const marker = markerForNode(activeMarker, nodeMap);
  const activeMarkerId = marker?.node_id || "";

  useEffect(() => {
    setPanOffset({ x: 0, y: 0 });
  }, [centerNodeId, mapData?.focus_id, zoomLevel]);

  useEffect(() => {
    function handleFullscreenChange() {
      setIsFullscreen(document.fullscreenElement === sectionRef.current);
    }

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, []);

  function movePan(dx, dy) {
    setPanOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
  }

  function resetPan() {
    setPanOffset({ x: 0, y: 0 });
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === sectionRef.current) {
        await document.exitFullscreen();
        return;
      }
      if (sectionRef.current?.requestFullscreen) {
        await sectionRef.current.requestFullscreen();
        stageRef.current?.focus();
      }
    } catch {}
  }

  function handlePointerDown(event) {
    if (event.target.closest("button")) return;
    if (event.target.closest(".rag-map-node")) return;
    dragRef.current = {
      pointerId: event.pointerId,
      lastX: event.clientX,
      lastY: event.clientY,
    };
    setIsDragging(true);
    stageRef.current?.focus();
    if (event.currentTarget.setPointerCapture) {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  }

  function handlePointerMove(event) {
    if (!isDragging || dragRef.current.pointerId !== event.pointerId) return;
    const dx = event.clientX - dragRef.current.lastX;
    const dy = event.clientY - dragRef.current.lastY;
    dragRef.current.lastX = event.clientX;
    dragRef.current.lastY = event.clientY;
    setPanOffset((prev) => ({ x: prev.x + dx, y: prev.y + dy }));
  }

  function handlePointerEnd(event) {
    if (dragRef.current.pointerId !== event.pointerId) return;
    if (event.currentTarget.releasePointerCapture) {
      try {
        event.currentTarget.releasePointerCapture(event.pointerId);
      } catch {}
    }
    dragRef.current = {
      pointerId: null,
      lastX: 0,
      lastY: 0,
    };
    setIsDragging(false);
  }

  function handleKeyDown(event) {
    if (event.key === "ArrowUp") {
      event.preventDefault();
      movePan(0, PAN_STEP);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      movePan(0, -PAN_STEP);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      movePan(PAN_STEP, 0);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      movePan(-PAN_STEP, 0);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      resetPan();
      return;
    }
    if (event.key === "Escape" && document.fullscreenElement === sectionRef.current) {
      document.exitFullscreen?.();
    }
  }

  function handleNodeClick(node) {
    if (!node) return;
    if (node.node_type === "resource") {
      onSelectNode?.(node);
      return;
    }
    if (node.is_expandable || node.node_type === "sector" || node.node_type === "chapter" || node.node_type === "knowledge_point") {
      onFocusNode?.(node.id, nextZoomForNode(node, zoomLevel));
      return;
    }
    onSelectNode?.(node);
  }

  const cameraTransform = centerNode
    ? `translate(${VIEW_CENTER.x + panOffset.x},${VIEW_CENTER.y + panOffset.y}) scale(${scale}) translate(${-centerNode.position.x},${-centerNode.position.y})`
    : `translate(${VIEW_CENTER.x + panOffset.x},${VIEW_CENTER.y + panOffset.y}) scale(${scale})`;

  return (
    <section ref={sectionRef} className={`card rag-knowledge-map is-${navigationState} ${isFullscreen ? "is-fullscreen" : ""}`}>
      <div className="rag-knowledge-map-head">
        <div>
          <h3>GraphRAG 星图导航</h3>
          <p className="hint">默认只显示高中物理与五大板块。拖动画布或使用方向键，可以像地图软件一样平移视野。</p>
        </div>
        <div className="rag-map-head-actions">
          <div className="rag-map-level-box">
            <button type="button" onClick={() => onZoomChange?.(Math.max(0, zoomLevel - 1))}>
              -
            </button>
            <strong>{ZOOM_LABELS[zoomLevel] || `L${zoomLevel}`}</strong>
            <button type="button" onClick={() => onZoomChange?.(Math.min(3, zoomLevel + 1))}>
              +
            </button>
          </div>
          <button type="button" className="ghost rag-map-fullscreen-btn" onClick={toggleFullscreen}>
            {isFullscreen ? "退出全屏" : "全屏显示"}
          </button>
        </div>
      </div>

      <div className="rag-map-breadcrumbs">
        <button
          type="button"
          className="ghost"
          onClick={() => {
            resetPan();
            onResetView?.();
          }}
        >
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

      <div
        ref={stageRef}
        className={`rag-map-stage ${isDragging ? "is-dragging" : ""}`}
        tabIndex={0}
        role="application"
        aria-label="GraphRAG knowledge map"
        onKeyDown={handleKeyDown}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerEnd}
        onPointerCancel={handlePointerEnd}
        onPointerLeave={handlePointerEnd}
      >
        {loading ? <div className="rag-map-loading">星图载入中...</div> : null}
        <button type="button" className="ghost rag-map-floating-fullscreen" onClick={toggleFullscreen}>
          {isFullscreen ? "退出全屏" : "全屏显示"}
        </button>
        <div className="rag-map-pan-controls" aria-label="地图平移控件">
          <button type="button" className="ghost rag-map-pan-up" onClick={() => movePan(0, PAN_STEP)}>
            ↑
          </button>
          <div className="rag-map-pan-row">
            <button type="button" className="ghost" onClick={() => movePan(PAN_STEP, 0)}>
              ←
            </button>
            <button type="button" className="ghost rag-map-pan-center" onClick={resetPan}>
              居中
            </button>
            <button type="button" className="ghost" onClick={() => movePan(-PAN_STEP, 0)}>
              →
            </button>
          </div>
          <button type="button" className="ghost rag-map-pan-down" onClick={() => movePan(0, -PAN_STEP)}>
            ↓
          </button>
        </div>
        <svg viewBox="-420 -320 840 640" className="rag-map-svg">
          <defs>
            <filter id="ragMapGlow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          <g className="rag-map-camera" transform={cameraTransform}>
            {edges.map((edge) => {
              const source = nodeMap.get(edge.source);
              const target = nodeMap.get(edge.target);
              if (!source || !target) return null;
              const isPrimary = edge.edge_type === "contains";
              const isPath = highlightSet.has(edge.source) && highlightSet.has(edge.target);
              return (
                <line
                  key={`${edge.source}-${edge.target}-${edge.edge_type}`}
                  x1={source.position.x}
                  y1={source.position.y}
                  x2={target.position.x}
                  y2={target.position.y}
                  className={`rag-map-edge ${isPrimary ? "is-primary" : "is-related"} ${isPath ? "is-path" : ""}`}
                  strokeWidth={isPath ? 2.8 : (isPrimary ? 1.6 : Math.max(1, Math.min(2.8, edge.weight || 1)))}
                />
              );
            })}

            {nodes.map((node) => {
              const radius = nodeRadius(node);
              const selected = selectedNodeId === node.id;
              const markerTarget = activeMarkerId === node.id;
              const clickable = node.is_expandable || node.node_type === "resource";
              const subtitle = subtitleForNode(node);
              const isPathNode = highlightSet.has(node.id);
              return (
                <g
                  key={node.id}
                  transform={`translate(${node.position.x},${node.position.y})`}
                  className={`rag-map-node rag-map-node-${node.node_type} ${selected ? "is-selected" : ""} ${clickable ? "is-clickable" : ""} ${markerTarget ? "is-marker-target" : ""} ${isPathNode ? "is-path-node" : ""}`}
                  onClick={() => handleNodeClick(node)}
                >
                  {node.node_type === "sector" ? (
                    <circle r={radius + 16} className="rag-map-sector-halo" style={{ fill: colorForSector(node) }} />
                  ) : null}
                  {markerTarget ? <circle r={radius + 14} className="rag-map-marker-pulse" /> : null}
                  <circle
                    r={radius}
                    className="rag-map-node-core"
                    style={{ fill: node.node_type === "root" ? "#0f172a" : colorForSector(node) }}
                    filter={selected || markerTarget ? "url(#ragMapGlow)" : undefined}
                  />
                  {node.node_type === "resource" ? <circle r={radius + 4} className="rag-map-resource-ring" /> : null}
                  {isLabelVisible(node, zoomLevel, selectedNodeId, activeMarkerId) ? (
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

            {marker ? (
              <g className="rag-map-marker-callout" transform={`translate(${marker.x},${marker.y})`}>
                <line x1="14" y1="-14" x2="90" y2="-74" className="rag-map-marker-line" />
                <g transform="translate(92,-116)">
                  <rect className="rag-map-marker-card" width="192" height="74" rx="18" />
                  <text x="18" y="26" className="rag-map-marker-title">{marker.label}</text>
                  <text x="18" y="48" className="rag-map-marker-subtitle">
                    {marker.subtitle || marker.path || subtitleForNode(marker.node)}
                  </text>
                  {marker.path ? <text x="18" y="66" className="rag-map-marker-path">{marker.path}</text> : null}
                </g>
              </g>
            ) : null}
          </g>
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
          <button type="button" className="ghost" onClick={() => onBackTrack?.()}>
            返回上一级
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              resetPan();
              onResetView?.();
            }}
          >
            返回全貌
          </button>
        </div>
      </div>
    </section>
  );
}
