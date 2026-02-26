import { useEffect, useMemo, useState } from "react";
import { fetchUploadOptions, getRagGraph } from "../lib/api";

function nodeColor(nodeType) {
  if (nodeType === "chapter") return "#0f766e";
  if (nodeType === "section") return "#0369a1";
  if (nodeType === "resource") return "#7c3aed";
  return "#334155";
}

export default function RagPage({ token, onLogin, setGlobalMessage }) {
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [chapters, setChapters] = useState([]);
  const [chapterId, setChapterId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [limit, setLimit] = useState(200);
  const [similarityThreshold, setSimilarityThreshold] = useState(0.78);
  const [maxLinks, setMaxLinks] = useState(2);
  const [graph, setGraph] = useState({ nodes: [], edges: [], stats: null });
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) return;
    async function loadOptions() {
      try {
        const data = await fetchUploadOptions({ token, stage: "senior", subject: "物理" });
        const chapterItems = data?.chapters || [];
        setChapters(chapterItems);
        if (!chapterId && chapterItems.length) {
          setChapterId(String(chapterItems[0].id));
        }
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }
    loadOptions();
  }, [token, chapterId, setGlobalMessage]);

  async function loadGraph() {
    if (!token) return;
    try {
      setLoading(true);
      const data = await getRagGraph({
        token,
        stage: "senior",
        subject: "物理",
        chapterId,
        keyword,
        limit: Number(limit) || 200,
        similarityThreshold: Number(similarityThreshold) || 0.78,
        maxLinksPerResource: Number(maxLinks) || 2
      });
      setGraph(data || { nodes: [], edges: [], stats: null });
      if (data?.nodes?.length) {
        setSelectedNodeId(data.nodes[0].id);
      } else {
        setSelectedNodeId("");
      }
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (token) {
      loadGraph();
    }
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  const layout = useMemo(() => {
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const chapterNodes = nodes.filter((node) => node.node_type === "chapter");
    const sectionNodes = nodes.filter((node) => node.node_type === "section");
    const resourceNodes = nodes.filter((node) => node.node_type === "resource");

    const chapterToSections = new Map();
    const sectionToResources = new Map();
    for (const edge of edges) {
      if (edge.edge_type !== "contains") continue;
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      if (source.node_type === "chapter" && target.node_type === "section") {
        const rows = chapterToSections.get(source.id) || [];
        rows.push(target.id);
        chapterToSections.set(source.id, rows);
      }
      if (source.node_type === "section" && target.node_type === "resource") {
        const rows = sectionToResources.get(source.id) || [];
        rows.push(target.id);
        sectionToResources.set(source.id, rows);
      }
    }

    const positions = {};
    const lineHeight = 72;
    const top = 46;
    let cursor = top;
    const chapterX = 150;
    const sectionX = 460;
    const resourceX = 840;

    const chapterOrder = [...chapterNodes].sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));
    for (const chapter of chapterOrder) {
      const sectionIds = Array.from(new Set(chapterToSections.get(chapter.id) || []));
      const safeSectionIds = sectionIds.length ? sectionIds : sectionNodes.filter((item) => item.chapter_id == null).map((item) => item.id);
      const chapterStart = cursor;
      for (const sectionId of safeSectionIds) {
        const section = byId.get(sectionId);
        if (!section) continue;
        const resourceIds = Array.from(new Set(sectionToResources.get(section.id) || []));
        const safeResources = resourceIds.length ? resourceIds : resourceNodes.filter((item) => item.section_id == null).map((item) => item.id);
        const sectionStart = cursor;
        for (const resourceId of safeResources) {
          const resource = byId.get(resourceId);
          if (!resource) continue;
          positions[resource.id] = { x: resourceX, y: cursor };
          cursor += lineHeight;
        }
        if (!safeResources.length) {
          cursor += lineHeight;
        }
        positions[section.id] = { x: sectionX, y: (sectionStart + cursor - lineHeight) / 2 };
      }
      positions[chapter.id] = { x: chapterX, y: (chapterStart + cursor - lineHeight) / 2 };
      cursor += 16;
    }

    const height = Math.max(560, cursor + 24);
    const width = 1120;

    const visibleEdges = edges
      .map((edge) => ({ ...edge, sourcePos: positions[edge.source], targetPos: positions[edge.target] }))
      .filter((edge) => edge.sourcePos && edge.targetPos);

    return { nodes, edges: visibleEdges, positions, width, height };
  }, [graph]);

  const selectedNode = useMemo(
    () => (graph.nodes || []).find((node) => node.id === selectedNodeId) || null,
    [graph.nodes, selectedNodeId]
  );

  async function handleLogin(event) {
    event.preventDefault();
    try {
      await onLogin(loginForm);
      setLoginForm({ email: "", password: "" });
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  if (!token) {
    return (
      <section className="card">
        <h2>RAG 知识树</h2>
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
    <section className="rag-page">
      <section className="card rag-toolbar">
        <h2>RAG 知识树可视化</h2>
        <p className="hint">章节 → 板块 → 资源，橙色虚线表示语义相似连接。</p>
        <div className="row-inline rag-filters">
          <select value={chapterId} onChange={(event) => setChapterId(event.target.value)}>
            {chapters.map((item) => (
              <option key={item.id} value={item.id}>{item.chapter_code} {item.title}</option>
            ))}
          </select>
          <input
            type="text"
            placeholder="关键词过滤（标题/简介）"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <input
            type="number"
            min="20"
            max="500"
            value={limit}
            onChange={(event) => setLimit(event.target.value)}
            title="资源上限"
          />
          <input
            type="number"
            min="0"
            max="1"
            step="0.01"
            value={similarityThreshold}
            onChange={(event) => setSimilarityThreshold(event.target.value)}
            title="相似度阈值"
          />
          <input
            type="number"
            min="0"
            max="8"
            value={maxLinks}
            onChange={(event) => setMaxLinks(event.target.value)}
            title="每个资源最大语义连边"
          />
          <button type="button" onClick={loadGraph} disabled={loading}>
            {loading ? "加载中..." : "刷新图谱"}
          </button>
        </div>
        {graph?.stats ? (
          <div className="rag-stats">
            <span>资源 {graph.stats.total_resources}</span>
            <span>向量 {graph.stats.embedded_resources}</span>
            <span>章节节点 {graph.stats.chapter_nodes}</span>
            <span>板块节点 {graph.stats.section_nodes}</span>
            <span>语义连边 {graph.stats.similarity_edges}</span>
          </div>
        ) : null}
      </section>

      <section className="card rag-canvas-wrap">
        <div className="rag-canvas">
          <svg viewBox={`0 0 ${layout.width} ${layout.height}`} preserveAspectRatio="xMinYMin meet">
            {layout.edges.map((edge, index) => {
              const s = edge.sourcePos;
              const t = edge.targetPos;
              if (edge.edge_type === "similar") {
                const cx = (s.x + t.x) / 2;
                const cy = Math.min(s.y, t.y) - 30;
                return (
                  <path
                    key={`e-${index}`}
                    d={`M ${s.x + 44} ${s.y} Q ${cx} ${cy} ${t.x - 44} ${t.y}`}
                    className="rag-edge rag-edge-similar"
                    strokeWidth={Math.max(1.2, Math.min(3.5, edge.weight * 3.2))}
                  />
                );
              }
              return (
                <line
                  key={`e-${index}`}
                  x1={s.x + 48}
                  y1={s.y}
                  x2={t.x - 48}
                  y2={t.y}
                  className="rag-edge rag-edge-contains"
                />
              );
            })}

            {layout.nodes.map((node) => {
              const pos = layout.positions[node.id];
              if (!pos) return null;
              const isActive = selectedNodeId === node.id;
              return (
                <g
                  key={node.id}
                  transform={`translate(${pos.x},${pos.y})`}
                  className={`rag-node rag-node-${node.node_type} ${isActive ? "active" : ""}`}
                  onClick={() => setSelectedNodeId(node.id)}
                >
                  <rect x={-48} y={-19} width={96} height={38} rx={9} fill={nodeColor(node.node_type)} />
                  <text textAnchor="middle" y="5">{node.label}</text>
                </g>
              );
            })}
          </svg>
        </div>

        <aside className="rag-side">
          {selectedNode ? (
            <>
              <h3>{selectedNode.label}</h3>
              <p className="hint">类型：{selectedNode.node_type}</p>
              {selectedNode.meta?.summary ? <p className="rag-summary">{selectedNode.meta.summary}</p> : null}
              {selectedNode.meta?.tags?.length ? (
                <div className="chip-list">
                  {selectedNode.meta.tags.map((tag) => <span key={tag} className="chip">{tag}</span>)}
                </div>
              ) : null}
              {selectedNode.resource_id ? (
                <div className="row-inline">
                  <button type="button" onClick={() => window.open(`/viewer/resource/${selectedNode.resource_id}`, "_blank", "noopener,noreferrer")}>打开资源</button>
                  <button
                    type="button"
                    className="ghost"
                    onClick={() => window.open(`/discover`, "_blank", "noopener,noreferrer")}
                  >
                    去发现页
                  </button>
                </div>
              ) : null}
            </>
          ) : (
            <p className="hint">点击节点查看详情</p>
          )}
        </aside>
      </section>
    </section>
  );
}
