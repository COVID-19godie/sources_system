import { useEffect, useMemo, useState } from "react";
import QuickSuggestionChips from "../components/QuickSuggestionChips";
import ResourceCard from "../components/ResourceCard";
import ResourceDetailModal from "../components/ResourceDetailModal";
import {
  apiRequest,
  fetchChapterTaxonomy,
  fetchUploadOptions,
  listKnowledgePoints,
  semanticSearchResources,
} from "../lib/api";

const FILE_FORMATS = [
  { key: "all", label: "全部格式" },
  { key: "markdown", label: "Markdown" },
  { key: "html", label: "HTML" },
  { key: "pdf", label: "PDF" },
  { key: "video", label: "视频" },
  { key: "image", label: "图片" },
  { key: "audio", label: "音频" },
  { key: "word", label: "Word" },
  { key: "excel", label: "Excel" },
  { key: "ppt", label: "PPT" },
  { key: "other", label: "其他" },
];

export default function DiscoverPage({ token, role, searchKeyword, onLogin, setGlobalMessage }) {
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [chapters, setChapters] = useState([]);
  const [sections, setSections] = useState([]);
  const [tags, setTags] = useState([]);
  const [quickQueries, setQuickQueries] = useState([]);
  const [difficulties, setDifficulties] = useState(["基础", "进阶", "挑战"]);
  const [quickKeyword, setQuickKeyword] = useState("");
  const [activeChapterId, setActiveChapterId] = useState(null);
  const [activeSection, setActiveSection] = useState("all");
  const [activeFormat, setActiveFormat] = useState("all");
  const [activeDifficulty, setActiveDifficulty] = useState("all");
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [groupData, setGroupData] = useState([]);
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticLoading, setSemanticLoading] = useState(false);
  const [semanticAnswer, setSemanticAnswer] = useState("");
  const [semanticResults, setSemanticResults] = useState([]);
  const [refreshTick, setRefreshTick] = useState(0);
  const [knowledgePointsByChapter, setKnowledgePointsByChapter] = useState({});
  const [expandedChapters, setExpandedChapters] = useState({});
  const [chapterTaxonomy, setChapterTaxonomy] = useState({});

  const effectiveKeyword = (searchKeyword || "").trim() || quickKeyword.trim();

  useEffect(() => {
    if (!token) {
      setChapters([]);
      setSections([]);
      setTags([]);
      setQuickQueries([]);
      setGroupData([]);
      return;
    }

    async function loadOptions() {
      try {
        const [data, kpRows] = await Promise.all([
          fetchUploadOptions({
            token,
            stage: "senior",
            subject: "物理",
          }),
          listKnowledgePoints({
            token,
            limit: 2000,
          }),
        ]);

        const chapterItems = data?.chapters || [];
        setChapters(chapterItems);
        setSections(data?.sections || []);
        setTags(data?.tags || []);
        setQuickQueries(data?.quick_queries || []);
        setDifficulties(data?.difficulties?.length ? data.difficulties : ["基础", "进阶", "挑战"]);

        const grouped = {};
        for (const item of kpRows || []) {
          const key = String(item.chapter_id || "");
          if (!key) continue;
          if (!grouped[key]) grouped[key] = [];
          grouped[key].push(item);
        }
        setKnowledgePointsByChapter(grouped);

        if (chapterItems.length && !activeChapterId) {
          setActiveChapterId(chapterItems[0].id);
        }
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }

    loadOptions();
  }, [token, setGlobalMessage, activeChapterId]);

  useEffect(() => {
    if (!token || !activeChapterId) {
      setGroupData([]);
      return;
    }

    async function loadByChapter() {
      setLoading(true);
      try {
        const params = new URLSearchParams();
        if (effectiveKeyword) params.set("q", effectiveKeyword);
        if (activeFormat !== "all") params.set("file_format", activeFormat);
        if (activeDifficulty !== "all") params.set("difficulty", activeDifficulty);
        const query = params.toString() ? `?${params.toString()}` : "";
        const data = await apiRequest(`/api/resources/chapter/${activeChapterId}/groups${query}`, { token });
        setGroupData(data?.groups || []);
      } catch (error) {
        setGlobalMessage(error.message);
      } finally {
        setLoading(false);
      }
    }

    loadByChapter();
  }, [activeChapterId, activeFormat, activeDifficulty, effectiveKeyword, token, setGlobalMessage, refreshTick]);

  useEffect(() => {
    function handleResourcesChanged() {
      setRefreshTick((value) => value + 1);
    }
    window.addEventListener("resources-changed", handleResourcesChanged);
    return () => window.removeEventListener("resources-changed", handleResourcesChanged);
  }, []);

  const chapterGroups = useMemo(() => {
    const groups = [];
    const index = new Map();
    for (const chapter of chapters) {
      const key = chapter.volume_code || "unassigned";
      if (!index.has(key)) {
        const row = {
          volume_code: key,
          volume_name: chapter.volume_name || "未分册",
          volume_order: chapter.volume_order || 999,
          chapters: [],
        };
        index.set(key, row);
        groups.push(row);
      }
      index.get(key).chapters.push(chapter);
    }
    groups.sort((a, b) => (a.volume_order - b.volume_order) || a.volume_code.localeCompare(b.volume_code, "zh-CN"));
    return groups;
  }, [chapters]);

  const sectionTabs = useMemo(() => {
    const base = [{ key: "all", label: "全部资源" }];
    for (const item of sections) {
      base.push({ key: String(item.id), label: item.name });
    }
    if (groupData.some((item) => !item.section && item.items?.length)) {
      base.push({ key: "unsectioned", label: "未分区" });
    }
    return base;
  }, [sections, groupData]);

  const visibleGroups = useMemo(() => {
    if (activeSection === "all") return groupData;
    if (activeSection === "unsectioned") return groupData.filter((group) => !group.section);
    return groupData.filter((group) => String(group.section?.id) === activeSection);
  }, [groupData, activeSection]);

  const recommendKeywords = useMemo(() => {
    const fromTags = tags.map((item) => item.tag);
    return Array.from(new Set([...fromTags, ...quickQueries])).slice(0, 14);
  }, [tags, quickQueries]);

  async function toggleChapterTree(chapter) {
    if (!chapter?.id) return;
    const chapterId = String(chapter.id);
    const nextExpanded = !expandedChapters[chapterId];
    setExpandedChapters((prev) => ({ ...prev, [chapterId]: nextExpanded }));
    setActiveChapterId(chapter.id);
    if (!nextExpanded || chapterTaxonomy[chapterId]) return;
    try {
      const data = await fetchChapterTaxonomy(chapter.id, token);
      setChapterTaxonomy((prev) => ({ ...prev, [chapterId]: data }));
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function runSemanticSearch(rawQuery) {
    const query = (rawQuery || semanticQuery).trim();
    if (!query) {
      setGlobalMessage("请输入语义检索问题");
      return;
    }

    try {
      setSemanticLoading(true);
      const data = await semanticSearchResources(
        {
          query,
          top_k: 20,
          include_answer: false,
        },
        token
      );
      setSemanticQuery(query);
      setSemanticAnswer(data?.answer || "");
      setSemanticResults(data?.results || []);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setSemanticLoading(false);
    }
  }

  async function handleLogin(event) {
    event.preventDefault();
    try {
      await onLogin(loginForm);
      setLoginForm({ email: "", password: "" });
      setGlobalMessage("登录成功");
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  if (!token) {
    return (
      <section className="card">
        <h2>资源发现</h2>
        <p className="hint">该页面需登录后访问</p>
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
    <section className="discover-page chapter-layout">
      <aside className="chapter-sidebar card">
        <h3>高中物理导航</h3>
        <div className="chapter-list">
          {chapterGroups.map((group) => (
            <div key={group.volume_code} className="chapter-volume-group">
              <h4>{group.volume_name}</h4>
              {group.chapters.map((chapter) => (
                <div key={chapter.id} className={`discover-tree-chapter ${activeChapterId === chapter.id ? "active" : ""}`}>
                  <div className="discover-tree-head">
                    <button
                      type="button"
                      className={activeChapterId === chapter.id ? "active" : ""}
                      onClick={() => setActiveChapterId(chapter.id)}
                    >
                      <span>{chapter.grade}</span>
                      <strong>{chapter.chapter_code} {chapter.title}</strong>
                    </button>
                    <button type="button" className="ghost discover-tree-toggle" onClick={() => toggleChapterTree(chapter)}>
                      {expandedChapters[String(chapter.id)] ? "收起" : "展开"}
                    </button>
                  </div>

                  {expandedChapters[String(chapter.id)] ? (
                    <div className="discover-tree-body">
                      {(chapterTaxonomy[String(chapter.id)]?.sections || []).map((section) => (
                        <section key={`${chapter.id}-${section.key}`} className="discover-tree-section">
                          <h5>{section.label}</h5>
                          <div className="discover-tree-tags">
                            {section.items.map((item) => (
                              <span key={`${section.key}-${item}`}>{item}</span>
                            ))}
                          </div>
                        </section>
                      ))}

                      <div className="discover-tree-kps">
                        {(knowledgePointsByChapter[String(chapter.id)] || []).map((kp) => (
                          <button
                            key={kp.id}
                            type="button"
                            className="discover-tree-kp"
                            onClick={() => setActiveChapterId(chapter.id)}
                          >
                            {kp.kp_code} {kp.name}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ))}
          {!chapters.length ? <p className="hint">暂无章节数据</p> : null}
        </div>
      </aside>

      <div className="chapter-main">
        <section className="card">
          <h3>AI语义检索</h3>
          <QuickSuggestionChips
            title="常见问题快捷提示"
            items={quickQueries.slice(0, 6)}
            onPick={(value) => runSemanticSearch(value)}
          />
          <div className="row-inline">
            <input
              type="text"
              value={semanticQuery}
              placeholder="例如：找高二电磁感应中讲楞次定律的教程"
              onChange={(event) => setSemanticQuery(event.target.value)}
            />
            <button type="button" onClick={() => runSemanticSearch()} disabled={semanticLoading}>
              {semanticLoading ? "检索中..." : "语义检索"}
            </button>
          </div>
          {semanticAnswer ? <p className="modal-desc"><strong>AI回答：</strong>{semanticAnswer}</p> : null}
          {semanticResults.length ? (
            <div className="resource-grid">
              {semanticResults.map((item) => (
                <div key={item.resource?.id || item.target?.source_id} className="semantic-result">
                  <div className="hint">
                    概率 {(item.probability || 0) * 100 < 0 ? "0.0" : ((item.probability || 0) * 100).toFixed(1)}%
                    {" / "}
                    向量 {Number(item.factors?.vector || 0).toFixed(2)}
                    {" / "}
                    摘要 {Number(item.factors?.summary || 0).toFixed(2)}
                    {" / "}
                    内容 {Number(item.factors?.content || 0).toFixed(2)}
                  </div>
                  {item.resource ? (
                    <ResourceCard item={item.resource} onClick={setSelected} />
                  ) : (
                    <div className="card">
                      <strong>{item.target?.title || "工作台来源"}</strong>
                      <p className="hint">{item.target?.summary || "该结果来自工作台源，不在资源库公开列表中。"}</p>
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : null}
        </section>

        <div className="discover-filter card">
          <QuickSuggestionChips
            title="推荐关键词"
            items={recommendKeywords}
            onPick={(value) => setQuickKeyword(value)}
          />
          {quickKeyword ? (
            <div className="action-buttons">
              <span className="hint">当前推荐词：{quickKeyword}</span>
              <button type="button" className="ghost" onClick={() => setQuickKeyword("")}>清除</button>
            </div>
          ) : null}

          <div className="type-tabs">
            {sectionTabs.map((item) => (
              <button key={item.key} type="button" className={activeSection === item.key ? "active" : ""} onClick={() => setActiveSection(item.key)}>
                {item.label}
              </button>
            ))}
          </div>

          <div className="type-tabs">
            {FILE_FORMATS.map((item) => (
              <button key={item.key} type="button" className={activeFormat === item.key ? "active" : ""} onClick={() => setActiveFormat(item.key)}>
                {item.label}
              </button>
            ))}
          </div>

          <div className="type-tabs">
            <button type="button" className={activeDifficulty === "all" ? "active" : ""} onClick={() => setActiveDifficulty("all")}>
              全部难度
            </button>
            {difficulties.map((item) => (
              <button key={item} type="button" className={activeDifficulty === item ? "active" : ""} onClick={() => setActiveDifficulty(item)}>
                {item}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <p className="hint">资源加载中...</p>
        ) : (
          visibleGroups.map((group, index) => (
            <section className="card" key={group.section?.id || `group-${index}`}>
              <h3>{group.section?.name || "未分区资源"}</h3>
              {group.items?.length ? (
                <div className="resource-grid">
                  {group.items.map((item) => (
                    <ResourceCard key={item.id} item={item} onClick={setSelected} />
                  ))}
                </div>
              ) : (
                <p className="hint">该分区暂无资源</p>
              )}
            </section>
          ))
        )}
      </div>

      <ResourceDetailModal item={selected} onClose={() => setSelected(null)} token={token} role={role} showDelete={false} />
    </section>
  );
}
