import { Component, useEffect, useMemo, useRef, useState } from "react";
import RagSourcePanel from "../components/RagSourcePanel";
import RagGraph2DCanvas from "../components/RagGraph2DCanvas";
import RagGraph3DCanvas from "../components/RagGraph3DCanvas";
import RagNodeInspector from "../components/RagNodeInspector";
import {
  apiRequest,
  askRagWorkspace,
  bindRagResources,
  createRagWorkspace,
  extractRagWorkspace,
  getNodeLinkedResources,
  getRagBootstrapJob,
  getRagNodeVariants,
  getRagWorkspaceGraph,
  listRagJobs,
  listRagSources,
  listRagWorkspaces,
  publishRagSource,
  quickBootstrapRag,
  semanticSearchWorkspace,
  uploadRagSourceWithProgress
} from "../lib/api";

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
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });

  const [workspaces, setWorkspaces] = useState([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("");
  const [workspaceMeta, setWorkspaceMeta] = useState(null);

  const [availableResources, setAvailableResources] = useState([]);
  const [selectedResourceIds, setSelectedResourceIds] = useState([]);

  const [sources, setSources] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [newWorkspace, setNewWorkspace] = useState({ name: "", description: "" });
  const [uploadState, setUploadState] = useState({ file: null, title: "", tags: "", progress: 0 });

  const [graph, setGraph] = useState({ nodes: [], edges: [], stats: null });
  const [loadingGraph, setLoadingGraph] = useState(false);
  const [graphLimit, setGraphLimit] = useState(200);
  const [graphFitTick, setGraphFitTick] = useState(0);
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [highlightNodes, setHighlightNodes] = useState([]);
  const [highlightEdges, setHighlightEdges] = useState([]);

  const [graphViewMode, setGraphViewMode] = useState(() => {
    if (typeof window === "undefined") {
      return "3d";
    }
    const stored = window.localStorage.getItem("rag_graph_view_mode");
    return stored === "2d" || stored === "3d" ? stored : "3d";
  });
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

  const selectedNode = useMemo(
    () => (filteredGraph.nodes || []).find((item) => item.id === selectedNodeId) || null,
    [filteredGraph.nodes, selectedNodeId]
  );

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

  async function loadWorkspaceData(workspaceId) {
    if (!workspaceId) {
      setSources([]);
      setJobs([]);
      setGraph({ nodes: [], edges: [], stats: null });
      setSelectedNodeId("");
      return;
    }

    const id = Number(workspaceId);
    setLoadingGraph(true);
    try {
      const [sourceRows, graphData, jobRows] = await Promise.all([
        listRagSources(id, token),
        getRagWorkspaceGraph(id, {
          token,
          limit: graphLimit,
          scope: graphScope,
          includeFormatNodes,
          dedupe: true,
          includeVariants: true
        }),
        listRagJobs(id, token, 30)
      ]);
      setSources(sourceRows || []);
      setJobs(jobRows || []);
      setGraph(graphData || { nodes: [], edges: [], stats: null });
    } finally {
      setLoadingGraph(false);
    }
  }

  async function runQuickBootstrap(forceExtract = false, withMessage = false) {
    const data = await quickBootstrapRag({
      token,
      stage: "senior",
      subject: "物理",
      forceExtract
    });
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
    if (!token) {
      return;
    }
    async function bootstrapPage() {
      try {
        const workspaceId = await runQuickBootstrap(false, false);
        await Promise.all([loadWorkspaces(), loadResources()]);
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
    if (!hasWebgl) {
      setGraphViewMode("2d");
      return;
    }
    setGraphViewMode((prev) => (prev === "2d" || prev === "3d" ? prev : "3d"));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem("rag_graph_view_mode", graphViewMode);
  }, [graphViewMode]);

  useEffect(() => {
    if (!token || !activeWorkspaceId) {
      return;
    }
    loadWorkspaceData(activeWorkspaceId).catch((error) => setGlobalMessage(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphScope, includeFormatNodes, graphLimit]);

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

  function handleFitGraphView() {
    setGraphFitTick((prev) => prev + 1);
  }

  function locateGraphNode() {
    const keyword = graphQuery.trim().toLowerCase();
    if (!keyword) {
      setGlobalMessage("请输入节点关键词");
      return;
    }
    const match = (filteredGraph.nodes || []).find((node) => {
      const label = `${node.keyword_label || ""} ${node.label || ""}`.toLowerCase();
      return label.includes(keyword);
    });
    if (!match) {
      setGlobalMessage("当前筛选范围未找到匹配节点");
      return;
    }
    setSelectedNodeId(match.id);
    setHighlightNodes([match.id]);
    setHighlightEdges([]);
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
          setSelectedNodeId(data.results[0].highlight_nodes[0]);
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
        setSelectedNodeId(data.highlight_nodes[0]);
      }
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setQaLoading(false);
    }
  }

  function handleSelectSemanticResult(item) {
    const nodes = item.highlight_nodes || [];
    const edges = item.highlight_edges || [];
    setHighlightNodes(nodes);
    setHighlightEdges(edges);
    if (nodes.length) {
      setSelectedNodeId(nodes[0]);
    }
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

  if (!token) {
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
            <option value="3d" disabled={!webglSupported}>3D</option>
            <option value="2d">2D</option>
          </select>
          {!webglSupported ? <span className="hint">当前设备不支持 WebGL，已自动回退 2D</span> : null}
          {webglSupported && graphViewMode === "3d" && (filteredGraph.nodes || []).length > 260 ? (
            <span className="hint">节点较多时如出现卡顿，可手动切换到 2D</span>
          ) : null}
          {graphViewMode === "2d" ? (
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
                locateGraphNode();
              }
            }}
          />
          <button type="button" onClick={locateGraphNode}>定位</button>
          <button type="button" className="ghost" onClick={handleFitGraphView}>适配视图</button>
          <button type="button" className="ghost" onClick={resetGraphFilters}>重置筛选</button>
        </div>

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

      <div className="rag-lite-main">
        {graphViewMode === "3d" && webglSupported ? (
          <GraphRenderBoundary
            key={`rag-3d-${activeWorkspaceId}-${graphLimit}`}
            onCrash={() => {
              setGraphViewMode("2d");
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
              graph={filteredGraph}
              fitTrigger={graphFitTick}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              highlightNodes={highlightNodes}
              highlightEdges={highlightEdges}
            />
          </GraphRenderBoundary>
        ) : (
          <RagGraph2DCanvas
            graph={filteredGraph}
            fitTrigger={graphFitTick}
            selectedNodeId={selectedNodeId}
            onSelectNode={setSelectedNodeId}
            highlightNodes={highlightNodes}
            highlightEdges={highlightEdges}
          />
        )}

        <div className="rag-lite-side">
          <RagNodeInspector
            node={selectedNode}
            linkedResources={linkedResources}
            loadingLinks={loadingLinked}
            variants={nodeVariants}
            variantsMeta={nodeVariantsMeta}
            loadingVariants={loadingVariants}
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
