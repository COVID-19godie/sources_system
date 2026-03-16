import { Component, useEffect, useMemo, useRef, useState } from "react";
import RagSourcePanel from "../components/RagSourcePanel";
import RagGraph3DCanvas from "../components/RagGraph3DCanvas";
import RagKnowledgeMapCanvas from "../components/RagKnowledgeMapCanvas";
import RagNodeInspector from "../components/RagNodeInspector";
import {
  apiRequest,
  askRagWorkspace,
  bindRagResources,
  createRagWorkspace,
  extractRagWorkspace,
  fetchUploadOptions,
  getNodeLinkedResources,
  getRagBootstrapJob,
  getRagNodeVariants,
  getRagWorkspaceGraph,
  getRagWorkspaceMap,
  listKnowledgePoints,
  listRagJobs,
  listRagSources,
  listRagWorkspaces,
  publishRagSource,
  quickBootstrapRag,
  semanticSearchWorkspace,
  uploadRagSourceWithProgress
} from "../lib/api";

function taxonomySectionsFromNode(node, knowledgePoints = []) {
  if (!node?.meta) {
    return [];
  }
  const groups = [
    { key: "knowledge_tags", label: "知识点", items: node.meta.knowledge_tags || [] },
    { key: "focus_tags", label: "重难点", items: node.meta.focus_tags || [] },
    { key: "exam_tags", label: "考点", items: node.meta.exam_tags || [] },
    { key: "problem_tags", label: "题组", items: node.meta.problem_tags || [] },
    { key: "experiment_tags", label: "实验", items: node.meta.experiment_tags || [] }
  ];

  return groups
    .filter((group) => group.items.length)
    .map((group) => ({
      ...group,
      knowledgePoints: knowledgePoints.filter((point) => {
        const tags = [
          ...(point.meta?.knowledge_tags || []),
          ...(point.meta?.focus_tags || []),
          ...(point.meta?.exam_tags || []),
          ...(point.meta?.problem_tags || []),
          ...(point.meta?.experiment_tags || [])
        ];
        if (!tags.length) {
          return true;
        }
        return group.items.some((item) => tags.includes(item));
      })
    }));
}

const NODE_TYPE_LABELS = {
  chapter: "章节",
  section: "板块",
  format: "格式层",
  resource: "资源",
  knowledge_point: "知识点",
  formula: "公式",
  experiment: "实验",
  problem_type: "题型"
};

const EDGE_TYPE_LABELS = {
  contains: "包含",
  related_to: "关联",
  appears_in: "出现于"
};

const FORMAT_GROUP_LABELS = {
  ppt: "课件",
  exercise: "题目",
  simulation: "仿真",
  video: "视频",
  document: "文档",
  image: "图片",
  audio: "音频",
  other: "其他"
};

function labelForNodeType(type) {
  return NODE_TYPE_LABELS[type] || type || "节点";
}

function labelForEdgeType(type) {
  return EDGE_TYPE_LABELS[type] || type || "关系";
}

function mergeFilterState(previous, keys) {
  const next = {};
  for (const key of keys) {
    next[key] = previous[key] ?? true;
  }
  return next;
}

const SEARCH_TYPE_PRIORITY = {
  sector: 160,
  chapter: 130,
  knowledge_point: 120,
  resource: 80
};

function normalizeSearchText(value) {
  return String(value || "").trim().toLowerCase().replace(/\s+/g, "");
}

function mapNodeIdForSearch(id, nodeType) {
  if (!id && nodeType === "chapter") {
    return "";
  }
  if (nodeType === "chapter" && String(id).startsWith("chapter:")) {
    return String(id).replace("chapter:", "map-chapter:");
  }
  return String(id || "");
}

function zoomForNodeType(nodeType) {
  if (nodeType === "root") return 0;
  if (nodeType === "sector") return 1;
  if (nodeType === "chapter") return 2;
  if (nodeType === "knowledge_point" || nodeType === "resource") return 3;
  return 0;
}

function scoreSearchEntry(entry, keyword) {
  const normalizedKeyword = normalizeSearchText(keyword);
  if (!normalizedKeyword) return 0;
  const fields = [
    entry.label,
    entry.keyword_label,
    ...(entry.search_keywords || []),
    entry.path,
    entry.chapter_title,
    entry.sector_label
  ].filter(Boolean);

  let score = SEARCH_TYPE_PRIORITY[entry.node_type] || 0;
  for (const raw of fields) {
    const normalized = normalizeSearchText(raw);
    if (!normalized) continue;
    if (normalized === normalizedKeyword) {
      score += 220;
      continue;
    }
    if (normalized.startsWith(normalizedKeyword)) {
      score += 140;
      continue;
    }
    if (normalized.includes(normalizedKeyword)) {
      score += 90;
    }
  }
  return score;
}

function buildMarkerPayload(entry, fallbackPath = "") {
  return {
    node_id: entry.id,
    label: entry.keyword_label || entry.label,
    subtitle: entry.sector_label || entry.node_type,
    path: entry.path || fallbackPath || "",
    marker_type: "search_result"
  };
}

function nodeTypeFromLayer(layer = 0) {
  const numericLayer = Number(layer || 0);
  if (numericLayer < 0) return "root";
  if (numericLayer <= 0) return "sector";
  if (numericLayer === 1) return "chapter";
  if (numericLayer >= 2) return "knowledge_point";
  return "resource";
}

function nodeTypeFromId(id = "", fallbackLayer = 0) {
  const value = String(id || "");
  if (value === "root" || value.startsWith("root:")) return "root";
  if (value.startsWith("sector:")) return "sector";
  if (value.startsWith("map-chapter:")) return "chapter";
  if (value.startsWith("kp:")) return "knowledge_point";
  if (value.startsWith("resource:")) return "resource";
  return nodeTypeFromLayer(fallbackLayer);
}

function mapNodeIdToGraphNodeId(id = "") {
  const value = String(id || "");
  if (value.startsWith("map-chapter:")) {
    return value.replace("map-chapter:", "chapter:");
  }
  return value;
}

function collectMapSubtreeIds(nodes = [], rootId = "") {
  if (!rootId) {
    return new Set(nodes.map((node) => node.id));
  }
  const byParent = new Map();
  for (const node of nodes) {
    const parentKey = node.parent_id || "__root__";
    const current = byParent.get(parentKey) || [];
    current.push(node.id);
    byParent.set(parentKey, current);
  }
  const allowed = new Set();
  const stack = [rootId];
  while (stack.length) {
    const currentId = stack.pop();
    if (!currentId || allowed.has(currentId)) continue;
    allowed.add(currentId);
    for (const childId of byParent.get(currentId) || []) {
      stack.push(childId);
    }
  }
  return allowed;
}

function filterMapPayloadToSubtree(payload, rootId = "") {
  if (!payload?.visible_nodes?.length || !rootId) {
    return payload;
  }
  const allowed = collectMapSubtreeIds(payload.visible_nodes, rootId);
  if (!allowed.size || !allowed.has(rootId)) {
    return payload;
  }
  return {
    ...payload,
    visible_nodes: (payload.visible_nodes || []).filter((node) => allowed.has(node.id)),
    visible_edges: (payload.visible_edges || []).filter((edge) => allowed.has(edge.source) && allowed.has(edge.target))
  };
}

function filterGraphToSubtree(graphPayload, mapPayload, rootId = "") {
  if (!graphPayload?.nodes?.length || !mapPayload?.visible_nodes?.length || !rootId) {
    return graphPayload;
  }
  const subtreePayload = filterMapPayloadToSubtree(mapPayload, rootId);
  const graphNodeIds = new Set((graphPayload.nodes || []).map((node) => node.id));
  const seedIds = new Set(
    (subtreePayload.visible_nodes || [])
      .map((node) => mapNodeIdToGraphNodeId(node.id))
      .filter((id) => graphNodeIds.has(id))
  );
  if (!seedIds.size) {
    return graphPayload;
  }
  return {
    ...graphPayload,
    nodes: (graphPayload.nodes || []).filter((node) => seedIds.has(node.id)),
    edges: (graphPayload.edges || []).filter((edge) => seedIds.has(edge.source) && seedIds.has(edge.target))
  };
}

class GraphRenderBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error) {
    if (typeof this.props.onCrash === "function") {
      this.props.onCrash(error);
    }
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback || null;
    }
    return this.props.children;
  }
}

export default function RagWorkspacePage({ token, onLogin, role, setGlobalMessage }) {
  const graphViewportRef = useRef(null);
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });

  const [workspaces, setWorkspaces] = useState([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("");
  const [workspaceMeta, setWorkspaceMeta] = useState(null);

  const [availableResources, setAvailableResources] = useState([]);
  const [selectedResourceIds, setSelectedResourceIds] = useState([]);

  const [sources, setSources] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [chapterGroups, setChapterGroups] = useState([]);
  const [knowledgePointsByChapter, setKnowledgePointsByChapter] = useState({});
  const [chapterTreeState, setChapterTreeState] = useState({});
  const [newWorkspace, setNewWorkspace] = useState({ name: "", description: "" });
  const [uploadState, setUploadState] = useState({ file: null, title: "", tags: "", progress: 0 });

  const [graph, setGraph] = useState({ nodes: [], edges: [], stats: null });
  const [mapData, setMapData] = useState(null);
  const [mapZoomLevel, setMapZoomLevel] = useState(0);
  const [targetZoomLevel, setTargetZoomLevel] = useState(0);
  const [mapFocusId, setMapFocusId] = useState("");
  const [focusedSubtreeRootId, setFocusedSubtreeRootId] = useState("");
  const [focusedSubtreeRootType, setFocusedSubtreeRootType] = useState("");
  const [centerNodeId, setCenterNodeId] = useState("");
  const [navigationState, setNavigationState] = useState("idle");
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [graphLimit, setGraphLimit] = useState(200);
  const [graphFitTick, setGraphFitTick] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [highlightNodes, setHighlightNodes] = useState([]);
  const [highlightEdges, setHighlightEdges] = useState([]);
  const [highlightPathNodes, setHighlightPathNodes] = useState([]);
  const [activeMarker, setActiveMarker] = useState(null);
  const [searchCandidates, setSearchCandidates] = useState([]);

  const [graphViewMode, setGraphViewMode] = useState(() => {
    if (typeof window === "undefined") {
      return "map";
    }
    const stored = window.localStorage.getItem("rag_graph_view_mode");
    if (stored === "3d") {
      return "3d";
    }
    return "map";
  });
  const [graph3DFullscreenTick, setGraph3DFullscreenTick] = useState(0);
  const [webglSupported, setWebglSupported] = useState(false);
  const [graphScope, setGraphScope] = useState("public");
  const [includeFormatNodes, setIncludeFormatNodes] = useState(true);
  const [graphQuery, setGraphQuery] = useState("");
  const [nodeTypeFilter, setNodeTypeFilter] = useState({});
  const [edgeTypeFilter, setEdgeTypeFilter] = useState({});
  const [difficultyFilter, setDifficultyFilter] = useState({});
  const [formatFilter, setFormatFilter] = useState({});

  const [linkedResources, setLinkedResources] = useState([]);
  const [loadingLinked, setLoadingLinked] = useState(false);
  const [nodeVariants, setNodeVariants] = useState([]);
  const [nodeVariantsMeta, setNodeVariantsMeta] = useState(null);
  const [loadingVariants, setLoadingVariants] = useState(false);

  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticResults, setSemanticResults] = useState([]);
  const [semanticThreshold, setSemanticThreshold] = useState(0);

  const [qaQuestion, setQaQuestion] = useState("");
  const [qaLoading, setQaLoading] = useState(false);
  const [qaAnswer, setQaAnswer] = useState("");
  const [qaCitations, setQaCitations] = useState([]);
  const [bootstrapJob, setBootstrapJob] = useState(null);
  const bootstrapPollerRef = useRef(null);

  const canManage = role === "admin" || role === "teacher";

  const allNodeTypes = useMemo(
    () => Array.from(new Set((graph.nodes || []).map((item) => item.node_type).filter(Boolean))),
    [graph.nodes]
  );
  const allEdgeTypes = useMemo(
    () => Array.from(new Set((graph.edges || []).map((item) => item.edge_type).filter(Boolean))),
    [graph.edges]
  );
  const allDifficulties = useMemo(
    () => Array.from(new Set(
      (graph.nodes || [])
        .filter((item) => item.node_type === "resource")
        .map((item) => item.meta?.difficulty || "未标注")
        .filter(Boolean)
    )),
    [graph.nodes]
  );
  const allFormatGroups = useMemo(
    () => Array.from(new Set(
      (graph.nodes || [])
        .filter((item) => item.node_type === "resource" || item.node_type === "format")
        .map((item) => item.meta?.format_group || "other")
        .filter(Boolean)
    )),
    [graph.nodes]
  );

  const filteredGraph = useMemo(() => {
    const allowedNodeTypes = new Set(
      allNodeTypes.filter((type) => nodeTypeFilter[type] ?? true)
    );
    const allowedDifficulties = new Set(
      allDifficulties.filter((value) => difficultyFilter[value] ?? true)
    );
    const allowedFormats = new Set(
      allFormatGroups.filter((value) => formatFilter[value] ?? true)
    );
    const nodes = (graph.nodes || []).filter((item) => {
      if (!allowedNodeTypes.has(item.node_type)) {
        return false;
      }
      if (item.node_type === "resource") {
        const difficulty = item.meta?.difficulty || "未标注";
        const formatGroup = item.meta?.format_group || "other";
        return allowedDifficulties.has(difficulty) && allowedFormats.has(formatGroup);
      }
      if (item.node_type === "format") {
        const formatGroup = item.meta?.format_group || "other";
        return allowedFormats.has(formatGroup);
      }
      return true;
    });
    const nodeIds = new Set(nodes.map((item) => item.id));

    const allowedEdgeTypes = new Set(
      allEdgeTypes.filter((type) => edgeTypeFilter[type] ?? true)
    );
    const edges = (graph.edges || []).filter((edge) => (
      nodeIds.has(edge.source)
      && nodeIds.has(edge.target)
      && allowedEdgeTypes.has(edge.edge_type)
    ));

    return { nodes, edges, stats: graph.stats || null };
  }, [
    graph,
    allNodeTypes,
    allEdgeTypes,
    nodeTypeFilter,
    edgeTypeFilter,
    allDifficulties,
    difficultyFilter,
    allFormatGroups,
    formatFilter
  ]);

  const focusedMapData = useMemo(
    () => filterMapPayloadToSubtree(mapData, focusedSubtreeRootId),
    [mapData, focusedSubtreeRootId]
  );

  const focusedGraph = useMemo(
    () => filterGraphToSubtree(filteredGraph, focusedMapData || mapData, focusedSubtreeRootId),
    [filteredGraph, focusedMapData, mapData, focusedSubtreeRootId]
  );

  const selectedNode = useMemo(() => {
    const mapMatch = (focusedMapData?.visible_nodes || []).find((item) => item.id === selectedNodeId);
    if (mapMatch) {
      return mapMatch;
    }
    return (focusedGraph.nodes || []).find((item) => item.id === selectedNodeId) || null;
  }, [focusedGraph.nodes, focusedMapData, selectedNodeId]);

  const selectedChapterId = useMemo(() => {
    if (selectedNodeId?.startsWith("map-chapter:")) {
      return Number(String(selectedNodeId).replace("map-chapter:", ""));
    }
    if (selectedNodeId?.startsWith("kp:")) {
      const rows = Object.values(knowledgePointsByChapter || []).flat();
      const match = rows.find((item) => item.id === Number(String(selectedNodeId).replace("kp:", "")));
      return match?.chapter_id || null;
    }
    return null;
  }, [selectedNodeId, knowledgePointsByChapter]);

  const focusedKnowledgePoints = useMemo(() => {
    if (selectedChapterId) {
      return knowledgePointsByChapter[String(selectedChapterId)] || [];
    }
    const firstChapter = chapterGroups.flatMap((group) => group.chapters || [])[0];
    return firstChapter ? (knowledgePointsByChapter[String(firstChapter.id)] || []) : [];
  }, [selectedChapterId, chapterGroups, knowledgePointsByChapter]);

  const mapSearchIndex = useMemo(() => {
    const entries = [];
    const seen = new Set();
    const pushEntry = (entry) => {
      if (!entry?.id || seen.has(`${entry.node_type}:${entry.id}`)) {
        return;
      }
      seen.add(`${entry.node_type}:${entry.id}`);
      entries.push(entry);
    };

    for (const node of mapData?.visible_nodes || []) {
      pushEntry({
        id: mapNodeIdForSearch(node.id, node.node_type),
        label: node.label,
        keyword_label: node.keyword_label,
        node_type: node.node_type,
        search_keywords: node.search_keywords || [],
        path: node.meta?.path || "",
        sector_label: node.meta?.sector_label || "",
        chapter_title: node.meta?.chapter_title || "",
        breadcrumbs_path: node.breadcrumbs_path || []
      });
    }

    for (const node of graph.nodes || []) {
      if (!["chapter", "resource"].includes(node.node_type)) {
        continue;
      }
      pushEntry({
        id: mapNodeIdForSearch(node.id, node.node_type),
        label: node.label,
        keyword_label: node.keyword_label,
        node_type: node.node_type,
        search_keywords: [
          ...(node.meta?.tags || []),
          ...(node.meta?.knowledge_tags || []),
          ...(node.meta?.focus_tags || []),
          ...(node.meta?.exam_tags || []),
          ...(node.meta?.problem_tags || []),
          ...(node.meta?.experiment_tags || []),
          ...(node.meta?.aliases || [])
        ],
        path: node.meta?.path || "",
        sector_label: node.meta?.sector_label || "",
        chapter_title: node.meta?.chapter_title || ""
      });
    }

    for (const group of chapterGroups || []) {
      for (const chapter of group.chapters || []) {
        pushEntry({
          id: `map-chapter:${chapter.id}`,
          label: `${chapter.chapter_code} ${chapter.title}`.trim(),
          keyword_label: chapter.title,
          node_type: "chapter",
          search_keywords: [chapter.chapter_code, ...(chapter.chapter_keywords || []), group.volume?.volume_name || "", chapter.grade || ""],
          path: `${group.volume?.volume_name || ""} / ${chapter.title}`.trim(),
          chapter_title: chapter.title
        });
      }
    }

    for (const [chapterId, rows] of Object.entries(knowledgePointsByChapter || {})) {
      const chapterNode = entries.find((item) => item.id === `map-chapter:${chapterId}`);
      for (const kp of rows || []) {
        pushEntry({
          id: `kp:${kp.id}`,
          label: `${kp.kp_code} ${kp.name}`.trim(),
          keyword_label: kp.name,
          node_type: "knowledge_point",
          search_keywords: [...(kp.aliases || []), kp.description || "", chapterNode?.label || "", chapterNode?.path || ""],
          path: chapterNode ? `${chapterNode.path} / ${kp.name}` : kp.name,
          chapter_title: chapterNode?.label || ""
        });
      }
    }

    return entries;
  }, [mapData, graph.nodes, chapterGroups, knowledgePointsByChapter]);

  const nodeTypeCounts = useMemo(() => {
    const counts = {};
    for (const node of graph.nodes || []) {
      counts[node.node_type] = (counts[node.node_type] || 0) + 1;
    }
    return counts;
  }, [graph.nodes]);

  const edgeTypeCounts = useMemo(() => {
    const counts = {};
    for (const edge of graph.edges || []) {
      counts[edge.edge_type] = (counts[edge.edge_type] || 0) + 1;
    }
    return counts;
  }, [graph.edges]);

  async function navigateToMapEntry(entry, reason = "focused") {
    if (!entry) {
      return;
    }
    const desiredZoom = zoomForNodeType(entry.node_type);
    const desiredFocusId = entry.id;
    const fallbackPath = entry.path || entry.breadcrumbs_path?.map((item) => item.label).join(" / ") || "";

    setNavigationState(reason === "search_result" ? "search_result" : "flying");
    setTargetZoomLevel(desiredZoom);
    setMapFocusId(desiredFocusId);
    setMapZoomLevel(desiredZoom);
    setCenterNodeId(desiredFocusId);
    setSelectedNodeId(desiredFocusId);
    setHighlightNodes([desiredFocusId]);
    setHighlightEdges([]);
    setHighlightPathNodes(
      entry.breadcrumbs_path?.map((item) => item.id).filter(Boolean)
      || [desiredFocusId]
    );
    setActiveMarker(buildMarkerPayload(entry, fallbackPath));

    if (activeWorkspaceId) {
      try {
        const payload = await loadWorkspaceMap(activeWorkspaceId, desiredZoom, desiredFocusId);
        const visibleNodeIds = new Set((payload?.visible_nodes || []).map((item) => item.id));
        const resolvedId = visibleNodeIds.has(desiredFocusId) ? desiredFocusId : (payload?.focus_id || desiredFocusId);
        const focusedNode = (payload?.visible_nodes || []).find((item) => item.id === resolvedId);
        if (focusedNode && focusedNode.node_type !== "resource") {
          setFocusedSubtreeRootId(focusedNode.id);
          setFocusedSubtreeRootType(focusedNode.node_type);
        }
        setCenterNodeId(resolvedId);
        setSelectedNodeId(resolvedId);
        setHighlightNodes([resolvedId]);
        setHighlightPathNodes(
          focusedNode?.breadcrumbs_path?.map((item) => item.id).filter(Boolean)
          || entry.breadcrumbs_path?.map((item) => item.id).filter(Boolean)
          || [resolvedId]
        );
        setActiveMarker(
          focusedNode
            ? buildMarkerPayload(
                {
                  id: focusedNode.id,
                  label: focusedNode.label,
                  keyword_label: focusedNode.keyword_label,
                  node_type: focusedNode.node_type,
                  sector_label: focusedNode.meta?.sector_label || "",
                  path: focusedNode.meta?.path || fallbackPath,
                },
                fallbackPath
              )
            : buildMarkerPayload(entry, fallbackPath)
        );
      } finally {
        window.setTimeout(() => {
          setNavigationState(reason === "search_result" ? "search_result" : "focused");
        }, 220);
      }
    } else if (entry.node_type !== "resource") {
      setFocusedSubtreeRootId(entry.id);
      setFocusedSubtreeRootType(entry.node_type);
    }
  }

  function stopBootstrapPolling() {
    if (bootstrapPollerRef.current) {
      clearInterval(bootstrapPollerRef.current);
      bootstrapPollerRef.current = null;
    }
  }

  useEffect(() => () => {
    stopBootstrapPolling();
  }, []);

  async function pollBootstrapJob(workspaceId, jobId, notifyOnFinish = false) {
    try {
      const job = await getRagBootstrapJob(workspaceId, jobId, token);
      setBootstrapJob(job);
      if (["done", "partial_failed", "failed", "skipped"].includes(job.status)) {
        stopBootstrapPolling();
        await loadWorkspaceData(workspaceId);
        if (notifyOnFinish) {
          const failedCount = Number(job.failed_sources_count || 0);
          const statusText = failedCount > 0
            ? `完成（${failedCount} 条源失败，已跳过）`
            : "完成";
          setGlobalMessage(`图谱更新任务已${statusText}`);
        }
      }
    } catch (error) {
      stopBootstrapPolling();
      setGlobalMessage(error.message || "图谱任务轮询失败");
    }
  }

  function startBootstrapPolling(workspaceId, jobId, notifyOnFinish = false) {
    stopBootstrapPolling();
    void pollBootstrapJob(workspaceId, jobId, notifyOnFinish);
    bootstrapPollerRef.current = setInterval(() => {
      void pollBootstrapJob(workspaceId, jobId, notifyOnFinish);
    }, 2500);
  }

  useEffect(() => {
    setNodeTypeFilter((prev) => mergeFilterState(prev, allNodeTypes));
  }, [allNodeTypes]);

  useEffect(() => {
    setEdgeTypeFilter((prev) => mergeFilterState(prev, allEdgeTypes));
  }, [allEdgeTypes]);

  useEffect(() => {
    setDifficultyFilter((prev) => mergeFilterState(prev, allDifficulties));
  }, [allDifficulties]);

  useEffect(() => {
    setFormatFilter((prev) => mergeFilterState(prev, allFormatGroups));
  }, [allFormatGroups]);

  useEffect(() => {
    if (!(filteredGraph.nodes || []).length) {
      setSelectedNodeId("");
      return;
    }
    const exists = filteredGraph.nodes.some((item) => item.id === selectedNodeId);
    if (!exists) {
      setSelectedNodeId(filteredGraph.nodes[0].id);
    }
  }, [filteredGraph.nodes, selectedNodeId]);

  useEffect(() => {
    if (!mapData) {
      return;
    }
    if (mapData.focus_id) {
      setCenterNodeId(mapData.focus_id);
    }
    const focusedNode = (mapData.visible_nodes || []).find((item) => item.id === (mapData.focus_id || selectedNodeId));
    if (focusedNode && activeMarker) {
      setActiveMarker((prev) => {
        const next = {
          ...(prev || {}),
          node_id: focusedNode.id,
          label: prev?.label || focusedNode.keyword_label || focusedNode.label,
          subtitle: prev?.subtitle || focusedNode.meta?.sector_label || "",
          path: prev?.path || focusedNode.meta?.path || ""
        };
        if (
          prev
          && prev.node_id === next.node_id
          && prev.label === next.label
          && prev.subtitle === next.subtitle
          && prev.path === next.path
        ) {
          return prev;
        }
        return next;
      });
    }
  }, [mapData, selectedNodeId, activeMarker]);

  async function loadWorkspaces() {
    const rows = await listRagWorkspaces({ token, stage: "senior", subject: "物理" });
    setWorkspaces(rows || []);
    return rows || [];
  }

  async function loadResources() {
    const data = await apiRequest("/api/resources?subject=物理&page=1&page_size=120&legacy_flat=false", { token });
    const rows = Array.isArray(data) ? data : (data?.items || []);
    setAvailableResources((rows || []).slice(0, 120));
  }

  async function loadChapterDirectory() {
    const [optionsData, kpData] = await Promise.all([
      fetchUploadOptions({
        token,
        stage: "senior",
        subject: "物理"
      }),
      listKnowledgePoints({
        token,
        limit: 2000
      })
    ]);
    setChapterGroups(optionsData?.chapters_grouped || []);
    const expandedState = {};
    for (const group of optionsData?.chapters_grouped || []) {
      for (const chapter of group.chapters || []) {
        expandedState[String(chapter.id)] = { expanded: true };
      }
    }
    setChapterTreeState((prev) => ({ ...prev, ...expandedState }));
    const grouped = {};
    for (const item of kpData || []) {
      const key = String(item.chapter_id || "");
      if (!key) {
        continue;
      }
      if (!grouped[key]) {
        grouped[key] = [];
      }
      grouped[key].push(item);
    }
    setKnowledgePointsByChapter(grouped);
  }

  async function loadWorkspaceData(workspaceId) {
    if (!workspaceId) {
      setSources([]);
      setJobs([]);
      setGraph({ nodes: [], edges: [], stats: null });
      setMapData(null);
      setMapFocusId("");
      setFocusedSubtreeRootId("");
      setFocusedSubtreeRootType("");
      setMapZoomLevel(0);
      setTargetZoomLevel(0);
      setCenterNodeId("");
      setSelectedNodeId("");
      setActiveMarker(null);
      setSearchCandidates([]);
      setHighlightPathNodes([]);
      return;
    }

    const id = Number(workspaceId);
    setLoadingGraph(true);
    try {
      const [sourceRows, graphData, mapPayload, jobRows] = await Promise.all([
        listRagSources(id, token),
        getRagWorkspaceGraph(id, {
          token,
          limit: graphLimit,
          scope: graphScope,
          includeFormatNodes,
          dedupe: true,
          includeVariants: true
        }),
        getRagWorkspaceMap(id, {
          token,
          limit: Math.max(240, graphLimit),
          scope: graphScope,
          zoomLevel: mapZoomLevel,
          focusId: mapFocusId
        }),
        listRagJobs(id, token, 30)
      ]);
      setSources(sourceRows || []);
      setJobs(jobRows || []);
      setGraph(graphData || { nodes: [], edges: [], stats: null });
      setMapData(mapPayload || null);
      if (mapPayload?.focus_id !== undefined) {
        setMapFocusId(mapPayload.focus_id || "");
        setFocusedSubtreeRootId(mapPayload.focus_id || "");
        const initialFocusedNode = (mapPayload?.visible_nodes || []).find((item) => item.id === mapPayload?.focus_id);
        setFocusedSubtreeRootType(initialFocusedNode?.node_type || "");
      }
      if (typeof mapPayload?.zoom_level === "number") {
        setMapZoomLevel(mapPayload.zoom_level);
        setTargetZoomLevel(mapPayload.zoom_level);
      }
      const initialNode = mapPayload?.focus_id || mapPayload?.visible_nodes?.find((item) => item.node_type === "sector")?.id || graphData?.nodes?.[0]?.id || "";
      setSelectedNodeId((current) => current || initialNode);
      setCenterNodeId(mapPayload?.focus_id || initialNode);
    } finally {
      setLoadingGraph(false);
    }
  }

  async function loadWorkspaceMap(workspaceId, nextZoom = mapZoomLevel, nextFocus = mapFocusId) {
    if (!workspaceId) {
      setMapData(null);
      return;
    }
    const payload = await getRagWorkspaceMap(Number(workspaceId), {
      token,
      limit: Math.max(240, graphLimit),
      scope: graphScope,
      zoomLevel: nextZoom,
      focusId: nextFocus
    });
    setMapData(payload || null);
    setMapFocusId(payload?.focus_id || "");
    if (typeof payload?.zoom_level === "number") {
      setMapZoomLevel(payload.zoom_level);
      setTargetZoomLevel(payload.zoom_level);
    }
    if (payload?.focus_id) {
      setSelectedNodeId(payload.focus_id);
      setCenterNodeId(payload.focus_id);
    }
    return payload;
  }

  async function runQuickBootstrap(forceExtract = false, withMessage = false) {
    const data = await quickBootstrapRag({
      token,
      stage: "senior",
      subject: "物理",
      forceExtract
    });
    if (!data?.workspace?.id) {
      throw new Error(data?.detail || "工作台初始化失败");
    }
    setWorkspaceMeta(data);
    setActiveWorkspaceId(String(data.workspace.id));
    if (data.bootstrap_job_id && ["queued", "processing"].includes(data.bootstrap_status)) {
      startBootstrapPolling(data.workspace.id, data.bootstrap_job_id, withMessage);
      if (withMessage) {
        setGlobalMessage("图谱更新任务已开始，正在后台处理");
      }
    } else {
      stopBootstrapPolling();
      setBootstrapJob(null);
      if (withMessage) {
        setGlobalMessage(
          `图谱已更新：资源源 ${data.source_count}，新增绑定 ${data.bound_count}，剔除失效 ${data.pruned_count || 0}（${data.extract_reason}）`
        );
      }
    }
    return data.workspace.id;
  }

  useEffect(() => {
    async function bootstrapPage() {
      try {
        const workspaceId = await runQuickBootstrap(false, false);
        await Promise.all([loadWorkspaces(), loadResources(), loadChapterDirectory()]);
        await loadWorkspaceData(workspaceId);
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }
    bootstrapPage();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    const canvas = document.createElement("canvas");
    const hasWebgl = Boolean(
      canvas.getContext("webgl")
      || canvas.getContext("experimental-webgl")
      || canvas.getContext("webgl2")
    );
    setWebglSupported(hasWebgl);
    setGraphViewMode((prev) => (prev === "3d" && hasWebgl ? "3d" : "map"));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("rag_graph_view_mode", graphViewMode);
  }, [graphViewMode]);

  useEffect(() => {
    if (!activeWorkspaceId) {
      return;
    }
    loadWorkspaceData(activeWorkspaceId).catch((error) => setGlobalMessage(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspaceId, graphScope, includeFormatNodes, graphLimit]);

  useEffect(() => {
    if (!activeWorkspaceId) {
      return;
    }
    loadWorkspaceMap(activeWorkspaceId, mapZoomLevel, mapFocusId).catch((error) => setGlobalMessage(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspaceId, graphScope, graphLimit, mapZoomLevel, mapFocusId]);

  useEffect(() => {
    if (!token || !activeWorkspaceId || !selectedNodeId) {
      setLinkedResources([]);
      setNodeVariants([]);
      setNodeVariantsMeta(null);
      return;
    }
    async function fetchNodePayloads() {
      try {
        setLoadingLinked(true);
        setLoadingVariants(true);
        const data = await getNodeLinkedResources(Number(activeWorkspaceId), selectedNodeId, {
          token,
          limit: 5
        });
        setLinkedResources(data?.items || []);
        const variants = await getRagNodeVariants(Number(activeWorkspaceId), selectedNodeId, { token });
        setNodeVariants(variants?.variants || []);
        setNodeVariantsMeta({
          canonicalKey: variants?.canonical_key || null,
          autoOpenVariantKind: variants?.auto_open_variant_kind || null
        });
      } catch {
        setLinkedResources([]);
        setNodeVariants([]);
        setNodeVariantsMeta(null);
      } finally {
        setLoadingLinked(false);
        setLoadingVariants(false);
      }
    }
    fetchNodePayloads();
  }, [token, activeWorkspaceId, selectedNodeId]);

  async function handleLogin(event) {
    event.preventDefault();
    try {
      await onLogin(loginForm);
      setLoginForm({ email: "", password: "" });
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleQuickRefresh() {
    if (!activeWorkspaceId) {
      setGlobalMessage("暂无可更新的工作台");
      return;
    }
    try {
      const workspaceId = await runQuickBootstrap(true, true);
      await loadWorkspaceData(workspaceId);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function resetGraphFilters() {
    setNodeTypeFilter(() => {
      const next = {};
      for (const type of allNodeTypes) next[type] = true;
      return next;
    });
    setEdgeTypeFilter(() => {
      const next = {};
      for (const type of allEdgeTypes) next[type] = true;
      return next;
    });
    setDifficultyFilter(() => {
      const next = {};
      for (const value of allDifficulties) next[value] = true;
      return next;
    });
    setFormatFilter(() => {
      const next = {};
      for (const value of allFormatGroups) next[value] = true;
      return next;
    });
  }

  async function handleFitGraphView() {
    setGraphFitTick((prev) => prev + 1);
    setMapFocusId("");
    setFocusedSubtreeRootId("");
    setFocusedSubtreeRootType("");
    setMapZoomLevel(0);
    setTargetZoomLevel(0);
    setCenterNodeId("");
    setNavigationState("idle");
    setActiveMarker(null);
    setSearchCandidates([]);
    setHighlightPathNodes([]);
    if (activeWorkspaceId) {
      try {
        await loadWorkspaceMap(activeWorkspaceId, 0, "");
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }
  }

  async function locateGraphNode() {
    const keyword = graphQuery.trim();
    const ranked = mapSearchIndex
      .map((entry) => ({ ...entry, score: scoreSearchEntry(entry, keyword) }))
      .filter((entry) => entry.score > 0)
      .sort((left, right) => right.score - left.score || left.label.localeCompare(right.label, "zh-CN"))
      .slice(0, 8);
    if (!keyword) {
      setGlobalMessage("请输入要导航的板块、章节或知识点");
      return;
    }
    setSearchCandidates(ranked);
    if (!ranked.length) {
      setActiveMarker(null);
      setHighlightPathNodes([]);
      setGlobalMessage("当前地图里没有找到匹配位置");
      return;
    }
    await navigateToMapEntry(ranked[0], "search_result");
    return;
    if (!keyword) {
      setGlobalMessage("请输入节点关键词");
      return;
    }
    const match = (filteredGraph.nodes || []).find((node) => {
      const label = `${node.keyword_label || ""} ${node.label || ""}`.toLowerCase();
      return label.includes(keyword);
    });
    const mapMatch = (mapData?.visible_nodes || []).find((node) => {
      const label = `${node.keyword_label || ""} ${node.label || ""}`.toLowerCase();
      return label.includes(keyword);
    });
    const finalMatch = mapMatch || match;
    if (!finalMatch) {
      setGlobalMessage("当前筛选范围未找到匹配节点");
      return;
    }
    setSelectedNodeId(finalMatch.id);
    setHighlightNodes([finalMatch.id]);
    setHighlightEdges([]);
    if (finalMatch.node_type === "sector") {
      setMapFocusId(finalMatch.id);
      setMapZoomLevel(1);
    } else if (finalMatch.node_type === "chapter") {
      setMapFocusId(finalMatch.id);
      setMapZoomLevel(2);
    } else if (finalMatch.node_type === "knowledge_point") {
      setMapFocusId(finalMatch.id);
      setMapZoomLevel(3);
    }
  }

  async function handleSemanticSearch() {
    const query = semanticQuery.trim();
    if (!query || !activeWorkspaceId) {
      setGlobalMessage("请输入语义检索问题");
      return;
    }
    try {
      setSemanticLoading(true);
      const data = await semanticSearchWorkspace(Number(activeWorkspaceId), {
        query,
        top_k: 20,
        candidate_limit: 320,
        rerank_top_k: 20,
        dedupe: true,
        include_answer: false
      }, token);
      setSemanticResults(data?.results || []);
      setSemanticThreshold(data?.threshold || 0);
      if (data?.results?.length) {
        setHighlightNodes(data.results[0].highlight_nodes || []);
        setHighlightEdges(data.results[0].highlight_edges || []);
        if (data.results[0].highlight_nodes?.length) {
          const firstNodeId = mapNodeIdForSearch(data.results[0].highlight_nodes[0], "resource");
          await navigateToMapEntry({
            id: firstNodeId,
            label: data.results[0].target?.title || data.results[0].resource?.title || firstNodeId,
            keyword_label: data.results[0].target?.title || data.results[0].resource?.title || "",
            node_type: firstNodeId.startsWith("sector:") ? "sector" : (firstNodeId.startsWith("map-chapter:") ? "chapter" : (firstNodeId.startsWith("kp:") ? "knowledge_point" : "resource")),
            path: data.results[0].target?.summary || "",
            search_keywords: []
          }, "search_result");
        }
      }
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setSemanticLoading(false);
    }
  }

  async function handleAskQuestion() {
    const question = qaQuestion.trim();
    if (!question || !activeWorkspaceId) {
      setGlobalMessage("请输入问答问题");
      return;
    }
    try {
      setQaLoading(true);
      const data = await askRagWorkspace(Number(activeWorkspaceId), question, token);
      setQaAnswer(data?.answer || "");
      setQaCitations(data?.citations || []);
      setHighlightNodes(data?.highlight_nodes || []);
      setHighlightEdges(data?.highlight_edges || []);
      if (data?.highlight_nodes?.length) {
        const firstNodeId = mapNodeIdForSearch(data.highlight_nodes[0], "resource");
        await navigateToMapEntry({
          id: firstNodeId,
          label: firstNodeId,
          keyword_label: firstNodeId,
          node_type: firstNodeId.startsWith("sector:") ? "sector" : (firstNodeId.startsWith("map-chapter:") ? "chapter" : (firstNodeId.startsWith("kp:") ? "knowledge_point" : "resource")),
          path: question,
          search_keywords: []
        }, "search_result");
      }
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setQaLoading(false);
    }
  }

  async function handleSelectSemanticResult(item) {
    const nodes = item.highlight_nodes || [];
    const edges = item.highlight_edges || [];
    setHighlightNodes(nodes);
    setHighlightEdges(edges);
    if (nodes.length) {
      const firstNodeId = mapNodeIdForSearch(nodes[0], "resource");
      await navigateToMapEntry({
        id: firstNodeId,
        label: item.target?.title || item.resource?.title || firstNodeId,
        keyword_label: item.target?.title || item.resource?.title || "",
        node_type: firstNodeId.startsWith("sector:") ? "sector" : (firstNodeId.startsWith("map-chapter:") ? "chapter" : (firstNodeId.startsWith("kp:") ? "knowledge_point" : "resource")),
        path: item.target?.summary || "",
        search_keywords: []
      }, "search_result");
    }
  }

  function buildMapEntryFromNode(node) {
    if (!node) {
      return null;
    }
    return {
      id: node.id,
      label: node.label,
      keyword_label: node.keyword_label,
      node_type: node.node_type,
      path: node.meta?.path || "",
      sector_label: node.meta?.sector_label || "",
      search_keywords: node.search_keywords || [],
      breadcrumbs_path: node.breadcrumbs_path || []
    };
  }

  function buildBreadcrumbEntry(item, breadcrumbs = mapData?.breadcrumbs || []) {
    if (!item?.id) {
      return null;
    }
    const trail = [];
    for (const crumb of breadcrumbs) {
      trail.push({ id: crumb.id, label: crumb.label });
      if (crumb.id === item.id) break;
    }
    return {
      id: item.id,
      label: item.label,
      keyword_label: item.label,
      node_type: nodeTypeFromId(item.id, item.layer),
      path: trail.map((crumb) => crumb.label).join(" / "),
      breadcrumbs_path: trail
    };
  }

  function buildEntryFromGraphNode(node) {
    if (!node?.id) {
      return null;
    }
    const mappedId = mapNodeIdForSearch(node.id, node.node_type);
    const mapMatch = mapSearchIndex.find((entry) => entry.id === mappedId);
    if (mapMatch) {
      return mapMatch;
    }
    return {
      id: mappedId,
      label: node.label,
      keyword_label: node.keyword_label,
      node_type: node.node_type,
      path: node.meta?.path || "",
      sector_label: node.meta?.sector_label || "",
      search_keywords: [
        ...(node.aliases || []),
        ...(node.meta?.tags || []),
        node.meta?.summary || ""
      ].filter(Boolean),
      breadcrumbs_path: []
    };
  }

  function applyLeafSelection(entry, reason = "focused") {
    if (!entry?.id) {
      return;
    }
    const pathIds = entry.breadcrumbs_path?.map((item) => item.id).filter(Boolean) || [];
    setNavigationState(reason === "search_result" ? "search_result" : "focused");
    setSelectedNodeId(entry.id);
    setCenterNodeId(entry.id);
    setHighlightNodes([entry.id]);
    setHighlightEdges([]);
    setHighlightPathNodes(pathIds.length ? pathIds : [entry.id]);
    setActiveMarker(buildMarkerPayload(entry, entry.path || ""));
  }

  async function focusGraphEntry(entry, reason = "focused") {
    if (!entry) {
      return;
    }
    if (entry.node_type === "resource") {
      applyLeafSelection(entry, reason);
      return;
    }
    setFocusedSubtreeRootId(entry.id);
    setFocusedSubtreeRootType(entry.node_type);
    await navigateToMapEntry(entry, reason);
  }

  async function handleMapBackTrack() {
    const crumbs = mapData?.breadcrumbs || [];
    if (!crumbs.length || crumbs.length === 1) {
      handleFitGraphView();
      return;
    }
    const previous = crumbs[crumbs.length - 2];
    const previousEntry = buildBreadcrumbEntry(previous, crumbs);
    setActiveMarker(null);
    await focusGraphEntry(previousEntry, "focused");
  }

  async function handleMapNodeSelect(node) {
    if (!node) {
      return;
    }
    const entry = buildMapEntryFromNode(node);
    if (!entry) {
      return;
    }
    setSearchCandidates([]);
    if (entry.node_type !== "resource" && (focusedSubtreeRootId || mapData?.focus_id || mapFocusId) === entry.id) {
      await handleMapBackTrack();
      return;
    }
    await focusGraphEntry(entry, "focused");
  }

  async function handleMapFocusNode(nodeId, nextZoom) {
    if (!nodeId) {
      handleFitGraphView();
      return;
    }
    const visibleNode = (mapData?.visible_nodes || []).find((item) => item.id === nodeId);
    const breadcrumbNode = (mapData?.breadcrumbs || []).find((item) => item.id === nodeId);
    const entry = visibleNode
      ? buildMapEntryFromNode(visibleNode)
      : buildBreadcrumbEntry(
          breadcrumbNode || { id: nodeId, label: nodeId, layer: Math.max(0, Number(nextZoom || 1) - 1) },
          mapData?.breadcrumbs || []
        );
    if (entry?.node_type !== "resource" && (focusedSubtreeRootId || mapData?.focus_id || mapFocusId) === entry?.id) {
      await handleMapBackTrack();
      return;
    }
    await focusGraphEntry(
      entry || {
        id: nodeId,
        label: nodeId,
        keyword_label: nodeId,
        node_type: nodeTypeFromId(nodeId, Math.max(0, Number(nextZoom || 1) - 1)),
        path: ""
      },
      "focused"
    );
  }

  async function handleGraphNodeSelect(node) {
    if (!node) {
      return;
    }
    const entry = buildEntryFromGraphNode(node);
    if (!entry) {
      return;
    }
    setSearchCandidates([]);
    if (entry.node_type === "resource" || entry.node_type === "section" || entry.node_type === "format") {
      applyLeafSelection(entry, "focused");
      return;
    }
    if ((focusedSubtreeRootId || mapData?.focus_id || mapFocusId) === entry.id) {
      await handleMapBackTrack();
      return;
    }
    await focusGraphEntry(entry, "focused");
  }

  async function handleChapterDirectorySelect(chapter) {
    if (!chapter?.id) {
      return;
    }
    await navigateToMapEntry({
      id: `map-chapter:${chapter.id}`,
      label: `${chapter.chapter_code} ${chapter.title}`.trim(),
      keyword_label: chapter.title,
      node_type: "chapter",
      path: `${chapter.volume_name || ""} / ${chapter.title}`.trim(),
      chapter_title: chapter.title,
      search_keywords: [chapter.chapter_code, ...(chapter.chapter_keywords || [])]
    }, "focused");
  }

  async function handleChapterTreeToggle(chapter) {
    if (!chapter?.id) {
      return;
    }
    const nodeId = `map-chapter:${chapter.id}`;
    const stateKey = String(chapter.id);
    const nextExpanded = !chapterTreeState[stateKey]?.expanded;
    setChapterTreeState((prev) => ({
      ...prev,
      [stateKey]: {
        ...prev[stateKey],
        expanded: nextExpanded
      }
    }));
    if (!nextExpanded || !activeWorkspaceId) {
      return;
    }
    void handleChapterDirectorySelect(chapter);
    try {
      const payload = await getRagWorkspaceMap(Number(activeWorkspaceId), {
        token,
        limit: Math.max(240, graphLimit),
        scope: graphScope,
        zoomLevel: 2,
        focusId: nodeId
      });
      const chapterNode = (payload?.visible_nodes || []).find((item) => item.id === nodeId);
      const kpNodes = (payload?.visible_nodes || []).filter((item) => item.parent_id === nodeId && item.node_type === "knowledge_point");
      setChapterTreeState((prev) => ({
        ...prev,
        [stateKey]: {
          expanded: true,
          node: chapterNode || null,
          sections: taxonomySectionsFromNode(chapterNode, kpNodes)
        }
      }));
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleKnowledgePointSelect(chapterId, kpId) {
    const chapterEntry = chapterGroups.flatMap((group) => group.chapters || []).find((item) => item.id === chapterId);
    const kpEntry = (knowledgePointsByChapter[String(chapterId)] || []).find((item) => item.id === kpId);
    await navigateToMapEntry({
      id: `kp:${kpId}`,
      label: `${kpEntry?.kp_code || ""} ${kpEntry?.name || "知识点"}`.trim(),
      keyword_label: kpEntry?.name || "知识点",
      node_type: "knowledge_point",
      path: `${chapterEntry?.volume_name || ""} / ${chapterEntry?.title || ""} / ${kpEntry?.name || ""}`.trim(),
      chapter_title: chapterEntry?.title || "",
      search_keywords: [...(kpEntry?.aliases || []), kpEntry?.description || ""]
    }, "focused");
    setChapterTreeState((prev) => ({
      ...prev,
      [String(chapterId)]: {
        ...prev[String(chapterId)],
        expanded: true
      }
    }));
  }

  function scrollToGraphViewport() {
    graphViewportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function switchGraphViewMode(nextMode) {
    setGraphViewMode(nextMode);
    window.setTimeout(() => {
      scrollToGraphViewport();
    }, 40);
  }

  function open3DFullscreen() {
    if (!webglSupported) {
      setGlobalMessage("当前设备不支持 3D 图谱");
      return;
    }
    setGraphViewMode("3d");
    window.setTimeout(() => {
      scrollToGraphViewport();
      window.setTimeout(() => {
        setGraph3DFullscreenTick((prev) => prev + 1);
      }, 160);
    }, 40);
  }

  function toggleBindResource(resourceId) {
    setSelectedResourceIds((prev) => (
      prev.includes(resourceId)
        ? prev.filter((item) => item !== resourceId)
        : [...prev, resourceId]
    ));
  }

  async function handleCreateWorkspace() {
    if (!newWorkspace.name.trim()) {
      setGlobalMessage("请填写工作台名称");
      return;
    }
    try {
      const row = await createRagWorkspace(
        {
          name: newWorkspace.name.trim(),
          description: newWorkspace.description.trim(),
          stage: "senior",
          subject: "物理"
        },
        token
      );
      setNewWorkspace({ name: "", description: "" });
      setGlobalMessage("工作台创建成功");
      await loadWorkspaces();
      setActiveWorkspaceId(String(row.id));
      await loadWorkspaceData(row.id);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleBindResources() {
    if (!activeWorkspaceId || !selectedResourceIds.length) {
      setGlobalMessage("请先选择要绑定的资源");
      return;
    }
    try {
      const data = await bindRagResources(Number(activeWorkspaceId), selectedResourceIds, token);
      setGlobalMessage(`绑定完成：新增 ${data.created}，跳过 ${data.skipped}`);
      setSelectedResourceIds([]);
      await loadWorkspaceData(activeWorkspaceId);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleUploadSource() {
    if (!activeWorkspaceId || !uploadState.file) {
      return;
    }
    try {
      setUploadState((prev) => ({ ...prev, progress: 0 }));
      await uploadRagSourceWithProgress({
        workspaceId: Number(activeWorkspaceId),
        token,
        file: uploadState.file,
        title: uploadState.title,
        tags: uploadState.tags,
        onProgress: (progress) => {
          setUploadState((prev) => ({ ...prev, progress }));
        }
      });
      setGlobalMessage("工作台源上传成功");
      setUploadState({ file: null, title: "", tags: "", progress: 100 });
      await loadWorkspaceData(activeWorkspaceId);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleExtract(modeValue) {
    if (!activeWorkspaceId) {
      return;
    }
    try {
      const data = await extractRagWorkspace(Number(activeWorkspaceId), { mode: modeValue, source_ids: [] }, token);
      setGlobalMessage(`建图完成：源 ${data.processed_sources}，实体+${data.entities_created}，关系+${data.relations_created}`);
      await loadWorkspaceData(activeWorkspaceId);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handlePublishSource(sourceId) {
    if (!activeWorkspaceId) {
      return;
    }
    try {
      const data = await publishRagSource(Number(activeWorkspaceId), sourceId, token);
      setGlobalMessage(`已发布到资源库：${data.resource.title}`);
      await loadWorkspaceData(activeWorkspaceId);
      window.dispatchEvent(new Event("resources-changed"));
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  if (false && !token) {
    return (
      <section className="card">
        <h2>GraphRAG 工作台</h2>
        <p className="hint">请登录后使用</p>
        <form onSubmit={handleLogin}>
          <input
            type="text"
            placeholder="账号"
            value={loginForm.email}
            onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
            required
          />
          <input
            type="password"
            placeholder="密码"
            value={loginForm.password}
            onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
            required
          />
          <button type="submit">登录</button>
        </form>
      </section>
    );
  }

  return (
    <section className="rag-lite-page">
      {!token ? (
        <section className="card discover-preview-login">
          <h2>GraphRAG 工作台</h2>
          <p className="hint">当前是本地预览模式，可以直接浏览高中物理图谱、章节树和知识点；登录后再进行上传和管理。</p>
          <form onSubmit={handleLogin} className="discover-inline-login">
            <input
              type="text"
              placeholder="账号"
              value={loginForm.email}
              onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
              required
            />
            <input
              type="password"
              placeholder="密码"
              value={loginForm.password}
              onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
              required
            />
            <button type="submit">登录</button>
          </form>
        </section>
      ) : null}
      <section className="card rag-lite-hero">
        <div className="rag-lite-head-row">
          <div>
            <h2>GraphRAG（即拆即用）</h2>
            <p className="hint">1. 输入问题 2. 选中节点 3. 直接打开资源</p>
          </div>
          <div className="rag-lite-actions">
            <button type="button" onClick={handleQuickRefresh}>一键更新图谱</button>
            <button
              type="button"
              className="ghost"
              onClick={() => loadWorkspaceData(activeWorkspaceId)}
              disabled={!activeWorkspaceId}
            >
              刷新画布
            </button>
          </div>
        </div>

        <div className="rag-lite-stat-grid">
          <article>
            <span>节点</span>
            <strong>{(filteredGraph.nodes || []).length}</strong>
          </article>
          <article>
            <span>关系</span>
            <strong>{(filteredGraph.edges || []).length}</strong>
          </article>
          <article>
            <span>资源源</span>
            <strong>{workspaceMeta?.source_count ?? graph?.stats?.total_resources ?? 0}</strong>
          </article>
          <article>
            <span>公开/私有</span>
            <strong>{graph?.stats ? `${graph.stats.public_sources || 0}/${graph.stats.private_sources || 0}` : "0/0"}</strong>
          </article>
          <article>
            <span>语义命中</span>
            <strong>{semanticResults.length}</strong>
          </article>
        </div>

        <div className="rag-lite-input-grid">
          <div className="rag-lite-input-box">
            <label>语义搜索（Top20 概率）</label>
            <div className="row-inline">
              <input
                type="text"
                placeholder="例如：电磁感应中的楞次定律"
                value={semanticQuery}
                onChange={(event) => setSemanticQuery(event.target.value)}
              />
              <button type="button" onClick={handleSemanticSearch} disabled={semanticLoading}>
                {semanticLoading ? "检索中..." : "搜索"}
              </button>
            </div>
            <p className="hint">阈值：{(Number(semanticThreshold || 0) * 100).toFixed(2)}%</p>
          </div>

          <div className="rag-lite-input-box">
            <label>图谱问答（证据驱动）</label>
            <div className="row-inline">
              <input
                type="text"
                placeholder="例如：楞次定律怎么判断方向？"
                value={qaQuestion}
                onChange={(event) => setQaQuestion(event.target.value)}
              />
              <button type="button" onClick={handleAskQuestion} disabled={qaLoading}>
                {qaLoading ? "回答中..." : "提问"}
              </button>
            </div>
          </div>
        </div>

        {workspaceMeta ? (
          <p className="hint">
            当前工作台：{workspaceMeta.workspace?.name} · 新增绑定 {workspaceMeta.bound_count} ·
            最近任务 {workspaceMeta.bootstrap_status || "skipped"}
          </p>
        ) : null}
        {bootstrapJob ? (
          <p className="hint">
            后台建图任务 #{bootstrapJob.job_id}：{bootstrapJob.status} · 成功 {bootstrapJob.succeeded_sources || 0} ·
            失败 {bootstrapJob.failed_sources_count || 0}
          </p>
        ) : null}
      </section>

      {!loadingGraph && !(graph?.nodes || []).length ? (
        <section className="card">
          <p className="hint">当前还没有可展示的图谱节点。你可以先上传资源，再返回此页自动建图。</p>
          <a className="button-link" href="/upload">去上传页</a>
        </section>
      ) : null}

      <section className="card rag-lite-controls">
        <div className="rag-lite-controls-top">
          <label htmlFor="rag-view-mode">画布</label>
          <select
            id="rag-view-mode"
            value={graphViewMode}
            onChange={(event) => setGraphViewMode(event.target.value)}
          >
            <option value="map">地图</option>
            <option value="3d" disabled={!webglSupported}>3D</option>
          </select>
          {!webglSupported ? <span className="hint">当前设备不支持 WebGL，已自动回退 2D</span> : null}
          {webglSupported && graphViewMode === "3d" && (filteredGraph.nodes || []).length > 260 ? (
            <span className="hint">节点较多时如出现卡顿，可手动切换到 2D</span>
          ) : null}
          {graphViewMode === "map" ? (
            <span className="hint">2D 地图模式：缩放后将逐级显示资源/章节命名</span>
          ) : null}

          <label htmlFor="rag-scope-mode">数据范围</label>
          <select
            id="rag-scope-mode"
            value={graphScope}
            onChange={(event) => setGraphScope(event.target.value)}
          >
            <option value="public">公开模式</option>
            <option value="mixed">混合模式</option>
          </select>

          <label htmlFor="rag-graph-limit">节点上限</label>
          <select
            id="rag-graph-limit"
            value={String(graphLimit)}
            onChange={(event) => setGraphLimit(Number(event.target.value))}
          >
            <option value="200">200（默认）</option>
            <option value="400">400</option>
            <option value="800">800</option>
          </select>

          <label className="inline-check">
            <input
              type="checkbox"
              checked={includeFormatNodes}
              onChange={(event) => setIncludeFormatNodes(event.target.checked)}
            />
            启用格式分层
          </label>

          <label htmlFor="rag-node-search">定位节点</label>
          <input
            id="rag-node-search"
            type="text"
            placeholder="输入关键词快速定位"
            value={graphQuery}
            onChange={(event) => setGraphQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void locateGraphNode();
              }
            }}
          />
          <button type="button" onClick={() => void locateGraphNode()}>定位</button>
          <button type="button" className="ghost" onClick={handleFitGraphView}>适配视图</button>
          <button type="button" className="ghost" onClick={resetGraphFilters}>重置筛选</button>
        </div>

        {searchCandidates.length ? (
          <div className="rag-search-candidate-list">
            {searchCandidates.map((item, index) => (
              <button
                key={`${item.id}-${index}`}
                type="button"
                className={`rag-search-candidate ${index === 0 ? "is-primary" : ""}`}
                onClick={() => void navigateToMapEntry(item, "search_result")}
              >
                <strong>{item.keyword_label || item.label}</strong>
                <span>{labelForNodeType(item.node_type)}</span>
                <small>{item.path || item.chapter_title || item.sector_label || "地图位置"}</small>
              </button>
            ))}
          </div>
        ) : null}

        <div className="rag-filter-block">
          <strong>节点筛选</strong>
          <div className="rag-chip-row">
            {allNodeTypes.map((type) => (
              <button
                key={type}
                type="button"
                className={`rag-chip ${(nodeTypeFilter[type] ?? true) ? "is-active" : ""}`}
                onClick={() => setNodeTypeFilter((prev) => ({ ...prev, [type]: !(prev[type] ?? true) }))}
              >
                {labelForNodeType(type)} ({nodeTypeCounts[type] || 0})
              </button>
            ))}
          </div>
        </div>

        <div className="rag-filter-block">
          <strong>关系筛选</strong>
          <div className="rag-chip-row">
            {allEdgeTypes.map((type) => (
              <button
                key={type}
                type="button"
                className={`rag-chip ${(edgeTypeFilter[type] ?? true) ? "is-active" : ""}`}
                onClick={() => setEdgeTypeFilter((prev) => ({ ...prev, [type]: !(prev[type] ?? true) }))}
              >
                {labelForEdgeType(type)} ({edgeTypeCounts[type] || 0})
              </button>
            ))}
          </div>
        </div>

        <div className="rag-filter-block">
          <strong>难度筛选（第4维）</strong>
          <div className="rag-chip-row">
            {allDifficulties.map((value) => (
              <button
                key={value}
                type="button"
                className={`rag-chip ${(difficultyFilter[value] ?? true) ? "is-active" : ""}`}
                onClick={() => setDifficultyFilter((prev) => ({ ...prev, [value]: !(prev[value] ?? true) }))}
              >
                {value}
              </button>
            ))}
          </div>
        </div>

        <div className="rag-filter-block">
          <strong>格式筛选（第5维）</strong>
          <div className="rag-chip-row">
            {allFormatGroups.map((value) => (
              <button
                key={value}
                type="button"
                className={`rag-chip ${(formatFilter[value] ?? true) ? "is-active" : ""}`}
                onClick={() => setFormatFilter((prev) => ({ ...prev, [value]: !(prev[value] ?? true) }))}
              >
                {FORMAT_GROUP_LABELS[value] || value}
              </button>
            ))}
          </div>
        </div>
      </section>

<section className="card rag-graph-access-bar">
        <div>
          <h3>图谱操作栏</h3>
          <p className="hint">先在这里切到 2D 或 3D，再进入图谱。点击节点后只保留该节点以下子树，平行节点会自动隐藏。</p>
        </div>
        <div className="rag-graph-access-actions">
          <button type="button" className="ghost" onClick={open3DFullscreen} disabled={!webglSupported}>3D 全屏</button>
          <button
            type="button"
            className={`rag-graph-mode-hero ${graphViewMode === "map" ? "is-active" : ""}`}
            onClick={() => switchGraphViewMode("map")}
          >
            查看 2D 地图
          </button>
          <button
            type="button"
            className={`rag-graph-mode-hero ${graphViewMode === "3d" ? "is-active" : ""}`}
            onClick={() => switchGraphViewMode("3d")}
            disabled={!webglSupported}
          >
            查看 3D 图谱
          </button>
          <button type="button" className="ghost" onClick={scrollToGraphViewport}>跳到图谱</button>
          <button type="button" className="ghost" onClick={handleFitGraphView}>返回全貌</button>
        </div>
      </section>

      <div ref={graphViewportRef} className="rag-lite-main">
        {graphViewMode === "3d" && webglSupported ? (
          <GraphRenderBoundary
            key={`rag-3d-${activeWorkspaceId}-${graphLimit}`}
            onCrash={() => {
              setGraphViewMode("map");
              setGlobalMessage("3D 渲染异常，已自动降级为 2D");
            }}
            fallback={(
              <section className="card rag-graph-canvas">
                <h3>知识图谱画布</h3>
                <p className="hint">3D 渲染失败，已切换为 2D。</p>
              </section>
            )}
          >
            <RagGraph3DCanvas
              graph={focusedGraph}
              fitTrigger={graphFitTick}
              fullscreenTrigger={graph3DFullscreenTick}
              selectedNodeId={selectedNodeId}
              onSelectNode={handleGraphNodeSelect}
              highlightNodes={highlightNodes}
              highlightEdges={highlightEdges}
            />
          </GraphRenderBoundary>
        ) : (
          <RagKnowledgeMapCanvas
            mapData={focusedMapData}
            loading={loadingGraph}
            selectedNodeId={selectedNodeId}
            centerNodeId={centerNodeId}
            navigationState={navigationState}
            zoomLevel={mapZoomLevel}
            activeMarker={activeMarker}
            highlightPathNodes={highlightPathNodes}
            onZoomChange={setMapZoomLevel}
            onSelectNode={handleMapNodeSelect}
            onFocusNode={handleMapFocusNode}
            onBackTrack={handleMapBackTrack}
            onResetView={handleFitGraphView}
          />
        )}

        <div className="rag-lite-side">
          <section className="card rag-kp-directory">
            <div className="rag-chapter-directory-head">
              <h3>知识点索引</h3>
              <span className="hint">点击后直接定位到图谱中的知识点</span>
            </div>
            {focusedKnowledgePoints.length ? (
              <div className="rag-kp-directory-list">
                {focusedKnowledgePoints.map((kp) => (
                  <button
                    key={`directory-kp-${kp.id}`}
                    type="button"
                    className="rag-kp-item"
                    onClick={() => handleKnowledgePointSelect(kp.chapter_id, kp.id)}
                  >
                    {kp.kp_code} {kp.name}
                  </button>
                ))}
              </div>
            ) : (
              <p className="hint">暂无知识点</p>
            )}
          </section>

          <section className="card rag-book-directory">
            <div className="rag-chapter-directory-head">
              <h3>物理导航目录</h3>
              <span className="hint">按书、章、节、知识点逐级定位</span>
            </div>
            {!chapterGroups.length ? <p className="hint">暂无物理目录</p> : null}
            <div className="rag-chapter-directory-groups">
              {chapterGroups.map((group) => (
                <section key={`book-${group.volume?.volume_code || group.volume?.volume_name}`} className="rag-chapter-volume-group">
                  <h4>{group.volume?.volume_name || "未分册"}</h4>
                  <div className="rag-chapter-list">
                    {(group.chapters || []).map((chapter) => {
                      const nodeId = `map-chapter:${chapter.id}`;
                      const state = chapterTreeState[String(chapter.id)] || {};
                      const sections = state.sections || [];
                      const fallbackPoints = knowledgePointsByChapter[String(chapter.id)] || [];
                      return (
                        <div key={`tree-${chapter.id}`} className={`rag-chapter-item ${(selectedNodeId === nodeId || state.expanded) ? "is-active" : ""}`}>
                          <div className="rag-chapter-item-head">
                            <button type="button" className="rag-chapter-main" onClick={() => handleChapterDirectorySelect(chapter)}>
                              <strong>{chapter.chapter_code} {chapter.title}</strong>
                              <span>{chapter.grade}</span>
                            </button>
                            <button type="button" className="ghost rag-tree-toggle" onClick={() => handleChapterTreeToggle(chapter)}>
                              {state.expanded ? "收起" : "展开"}
                            </button>
                          </div>
                          {state.expanded ? (
                            <div className="rag-section-tree">
                              {sections.length ? sections.map((section) => (
                                <section key={`${chapter.id}-${section.key}`} className="rag-section-node">
                                  <h5>{section.label}</h5>
                                  <div className="rag-section-tags">
                                    {section.items.map((item) => (
                                      <span key={`${section.key}-${item}`} className="rag-section-tag">{item}</span>
                                    ))}
                                  </div>
                                  <div className="rag-kp-list">
                                    {(section.knowledgePoints || []).map((kp) => (
                                      <button
                                        key={kp.id}
                                        type="button"
                                        className="rag-kp-item"
                                        onClick={() => handleKnowledgePointSelect(chapter.id, kp.meta?.knowledge_point_id || Number(String(kp.id).replace("kp:", "")))}
                                      >
                                        {kp.keyword_label || kp.label}
                                      </button>
                                    ))}
                                  </div>
                                </section>
                              )) : (
                                <section className="rag-section-node">
                                  <h5>知识点</h5>
                                  <div className="rag-kp-list">
                                    {fallbackPoints.map((kp) => (
                                      <button key={kp.id} type="button" className="rag-kp-item" onClick={() => handleKnowledgePointSelect(chapter.id, kp.id)}>
                                        {kp.kp_code} {kp.name}
                                      </button>
                                    ))}
                                  </div>
                                </section>
                              )}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          </section>

          <section className="card rag-chapter-directory">
            <div className="rag-chapter-directory-head">
              <h3>物理章节</h3>
              <span className="hint">按册快速定位到地图章节</span>
            </div>
            {!chapterGroups.length ? <p className="hint">暂无章节目录</p> : null}
            <div className="rag-chapter-directory-groups">
              {chapterGroups.map((group) => (
                <section key={group.volume?.volume_code || group.volume?.volume_name} className="rag-chapter-volume-group">
                  <h4>{group.volume?.volume_name || "未分册"}</h4>
                  <div className="rag-chapter-list">
                    {(group.chapters || []).map((chapter) => {
                      const nodeId = `map-chapter:${chapter.id}`;
                      const isActive = selectedNodeId === nodeId || mapFocusId === nodeId;
                      return (
                        <button
                          key={chapter.id}
                          type="button"
                          className={`rag-chapter-item ${isActive ? "is-active" : ""}`}
                          onClick={() => handleChapterDirectorySelect(chapter)}
                        >
                          <strong>{chapter.chapter_code} {chapter.title}</strong>
                          <span>{chapter.grade}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          </section>

          <RagNodeInspector
            node={selectedNode}
            linkedResources={linkedResources}
            loadingLinks={loadingLinked}
            variants={nodeVariants}
            variantsMeta={nodeVariantsMeta}
            loadingVariants={loadingVariants}
            onExpandRelated={(node) => {
              if (node?.node_type === "knowledge_point") {
                void handleMapNodeSelect(node);
              }
            }}
          />

          <section className="card rag-lite-answer-card">
            <h3>问答结果</h3>
            {qaAnswer ? <p className="rag-answer">{qaAnswer}</p> : <p className="hint">暂无问答结果</p>}
            <div className="rag-citation-list">
              {qaCitations.map((item, index) => (
                <div key={`${item.source_id}-${index}`} className="rag-citation-item">
                  <strong>{item.title}</strong>
                  <span className="hint">相关度 {Number(item.score || 0).toFixed(3)}</span>
                  <span>{item.evidence}</span>
                </div>
              ))}
            </div>
          </section>

          <section className="card rag-lite-semantic-card">
            <h3>搜索结果 Top20</h3>
            {!semanticResults.length ? <p className="hint">暂无搜索结果</p> : null}
            <div className="rag-semantic-results">
              {semanticResults.map((item, index) => (
                <article key={`${item.target?.source_id || item.resource?.id}-${index}`} className="rag-semantic-item">
                  <button
                    type="button"
                    className="rag-semantic-focus"
                    onClick={() => handleSelectSemanticResult(item)}
                  >
                    <strong>{item.target?.title || item.resource?.title || "未命名"}</strong>
                    <span>概率 {(Number(item.probability || 0) * 100).toFixed(1)}%</span>
                    <span className="hint">
                      向量 {Number(item.factors?.vector || 0).toFixed(2)}
                      {" / "}
                      摘要 {Number(item.factors?.summary || 0).toFixed(2)}
                      {" / "}
                      内容 {Number(item.factors?.content || 0).toFixed(2)}
                    </span>
                  </button>
                  {item.resource?.id ? (
                    <a
                      className="button-link"
                      href={`/viewer/resource/${item.resource.id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      打开资源
                    </a>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        </div>
      </div>

      <RagSourcePanel
        canManage={canManage}
        workspaces={workspaces}
        activeWorkspaceId={activeWorkspaceId}
        onWorkspaceChange={(value) => {
          setActiveWorkspaceId(value);
          if (value) {
            loadWorkspaceData(value).catch((error) => setGlobalMessage(error.message));
          }
        }}
        onCreateWorkspace={handleCreateWorkspace}
        newWorkspace={newWorkspace}
        onNewWorkspaceChange={setNewWorkspace}
        availableResources={availableResources}
        selectedResourceIds={selectedResourceIds}
        onToggleResource={toggleBindResource}
        onBindResources={handleBindResources}
        uploadState={uploadState}
        onUploadStateChange={setUploadState}
        onUpload={handleUploadSource}
        onExtractQuick={() => handleExtract("quick")}
        onExtractFull={() => handleExtract("full")}
        onRefresh={() => loadWorkspaceData(activeWorkspaceId)}
        sources={sources}
        jobs={jobs}
        onPublishSource={handlePublishSource}
      />
    </section>
  );
}
