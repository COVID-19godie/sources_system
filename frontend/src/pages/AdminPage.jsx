import { useEffect, useMemo, useState } from "react";
import EditModal from "../components/EditModal";
import {
  adoptResourceAiTags,
  apiRequest,
  bulkManageResources,
  createKnowledgeEdge,
  createKnowledgePoint,
  createTag,
  fetchTags,
  formatTime,
  listIngestDocuments,
  listIngestJobs,
  listAdminResources,
  listKnowledgePoints,
  listTrashItems,
  notifyResourcesChanged,
  purgeExpiredTrash,
  purgeTrashItem,
  reconcileStorage,
  reorderTags,
  restoreTrashItem,
  semanticSearchIngestDocuments,
  startIngestBackfill,
  submitIngestUrl,
  setResourceVisibility,
  updateKnowledgePoint,
  updateResourceTags,
  updateTag
} from "../lib/api";
import { GENERAL_CHAPTER_LABEL, GENERAL_CHAPTER_VALUE, isGeneralChapterValue, toChapterMode, withGeneralChapterOption } from "../lib/chapterOptions";

const STAGE = "senior";
const SUBJECT = "物理";
const GRADE_OPTIONS = ["高一", "高二", "高三"];
const TEXTBOOK_PRESETS = ["人教版", "其他"];
const TAG_CATEGORY_OPTIONS = [
  { value: "mechanics", label: "力学" },
  { value: "electromagnetism", label: "电磁学" },
  { value: "thermodynamics", label: "热学" },
  { value: "optics", label: "光学" },
  { value: "modern_physics", label: "近代物理" },
  { value: "experiment", label: "实验" },
  { value: "problem_solving", label: "解题" },
  { value: "other", label: "其他" }
];
const APPROVE_NOTE_TEMPLATES = [
  "内容规范，可公开",
  "分类准确，资源可用",
  "资源质量良好，建议发布"
];
const REJECT_NOTE_TEMPLATES = [
  "内容与章节不匹配",
  "文件无法正常预览",
  "内容质量不足",
  "存在重复资源"
];

function defaultChapterForm(firstVolume = null) {
  return {
    grade: "高一",
    volume_code: firstVolume?.code || "",
    volume_name: firstVolume?.name || "",
    volume_order: firstVolume?.order || 10,
    chapter_order: 10,
    chapter_code: "",
    title: "",
    chapter_keywords: "",
    textbook_mode: "人教版",
    textbook_custom: "",
    is_enabled: true
  };
}

function chapterToForm(chapter) {
  const known = TEXTBOOK_PRESETS.includes(chapter.textbook || "") ? chapter.textbook : "其他";
  return {
    grade: chapter.grade,
    volume_code: chapter.volume_code || "",
    volume_name: chapter.volume_name || "",
    volume_order: chapter.volume_order || 10,
    chapter_order: chapter.chapter_order || 10,
    chapter_code: chapter.chapter_code,
    title: chapter.title,
    chapter_keywords: (chapter.chapter_keywords || []).join("，"),
    textbook_mode: known,
    textbook_custom: known === "其他" ? chapter.textbook || "" : "",
    is_enabled: chapter.is_enabled
  };
}

function defaultSectionForm() {
  return {
    code: "",
    name: "",
    description: "",
    sort_order: 100,
    is_enabled: true
  };
}

function normalizeSectionCode(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll("_", "-")
    .replaceAll(" ", "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function sectionToForm(section) {
  return {
    code: section.code,
    name: section.name,
    description: section.description || "",
    sort_order: section.sort_order,
    is_enabled: section.is_enabled
  };
}

function defaultTagForm() {
  return {
    tag: "",
    category: "mechanics",
    sort_order: 100,
    is_enabled: true
  };
}

function tagToForm(tag) {
  return {
    tag: tag.tag,
    category: tag.category,
    sort_order: tag.sort_order,
    is_enabled: tag.is_enabled
  };
}

function tagsToCsv(tags) {
  if (!Array.isArray(tags) || !tags.length) {
    return "";
  }
  return tags.join("，");
}

function parseTagInput(value) {
  return String(value || "")
    .split(/[，,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export default function AdminPage({ token, role, onLogin, setGlobalMessage }) {
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [activeTab, setActiveTab] = useState("resources");
  const [managedItems, setManagedItems] = useState([]);
  const [resourceFilters, setResourceFilters] = useState({
    q: "",
    status: "all",
    chapterId: "",
    sectionId: "",
    author: ""
  });
  const [selectedResourceIds, setSelectedResourceIds] = useState([]);
  const [bulkAction, setBulkAction] = useState("hide");
  const [bulkNote, setBulkNote] = useState("");
  const [pendingItems, setPendingItems] = useState([]);
  const [chapters, setChapters] = useState([]);
  const [sections, setSections] = useState([]);
  const [tags, setTags] = useState([]);
  const [sectionFilter, setSectionFilter] = useState("");
  const [sectionStatus, setSectionStatus] = useState("all");
  const [tagFilter, setTagFilter] = useState("");
  const [tagStatus, setTagStatus] = useState("all");
  const [trashItems, setTrashItems] = useState([]);
  const [trashScope, setTrashScope] = useState("all");
  const [trashQuery, setTrashQuery] = useState("");
  const [trashPage, setTrashPage] = useState(1);
  const [trashPageSize] = useState(20);
  const [trashTotal, setTrashTotal] = useState(0);
  const [trashLoading, setTrashLoading] = useState(false);
  const [knowledgePoints, setKnowledgePoints] = useState([]);
  const [ingestJobs, setIngestJobs] = useState([]);
  const [knowledgeFilters, setKnowledgeFilters] = useState({
    chapterId: "",
    q: "",
    status: "all"
  });
  const [ingestForm, setIngestForm] = useState({ url: "", title: "" });
  const [ingestDocFilters, setIngestDocFilters] = useState({ q: "", chapterId: "" });
  const [ingestDocuments, setIngestDocuments] = useState([]);
  const [ingestSemanticQuery, setIngestSemanticQuery] = useState("");
  const [ingestSemanticLoading, setIngestSemanticLoading] = useState(false);
  const [ingestSemanticResults, setIngestSemanticResults] = useState([]);
  const [ingestBackfillLoading, setIngestBackfillLoading] = useState(false);
  const [knowledgeForm, setKnowledgeForm] = useState({
    chapter_id: "",
    kp_code: "",
    name: "",
    aliases: "",
    description: "",
    difficulty: "",
    prerequisite_level: 0.3,
    status: "published"
  });
  const [edgeForm, setEdgeForm] = useState({
    src_kp_id: "",
    dst_kp_id: "",
    edge_type: "related",
    strength: 0.6
  });

  const [reviewModal, setReviewModal] = useState({
    open: false,
    resourceId: null,
    status: "approved",
    template: "",
    extra: ""
  });
  const [chapterModal, setChapterModal] = useState({
    open: false,
    mode: "create",
    chapterId: null,
    form: defaultChapterForm()
  });
  const [sectionModal, setSectionModal] = useState({
    open: false,
    mode: "create",
    sectionId: null,
    form: defaultSectionForm()
  });
  const [tagModal, setTagModal] = useState({
    open: false,
    mode: "create",
    tagId: null,
    form: defaultTagForm()
  });
  const [resourceTagModal, setResourceTagModal] = useState({
    open: false,
    resourceId: null,
    title: "",
    tagsText: "",
    mode: "replace"
  });
  const [catalogAudit, setCatalogAudit] = useState(null);

  const volumeOptions = useMemo(() => {
    const grouped = new Map();
    for (const chapter of chapters) {
      const key = chapter.volume_code || "";
      if (!key || grouped.has(key)) {
        continue;
      }
      grouped.set(key, {
        code: key,
        name: chapter.volume_name || key,
        order: chapter.volume_order || 999
      });
    }
    return Array.from(grouped.values()).sort((a, b) => (a.order - b.order) || a.code.localeCompare(b.code, "zh-CN"));
  }, [chapters]);
  const strictCatalog = Boolean(catalogAudit?.strict_enabled);
  const chaptersWithGeneral = useMemo(() => withGeneralChapterOption(chapters), [chapters]);

  async function loadAll() {
    if (!token || role !== "admin") {
      setManagedItems([]);
      setPendingItems([]);
      setChapters([]);
      setSections([]);
      setTags([]);
      setCatalogAudit(null);
      return;
    }

    try {
      const [pendingData, chapterData, sectionData, tagData, auditData, kpData, ingestData, ingestDocData] = await Promise.all([
        apiRequest("/api/resources/pending", { token }),
        apiRequest(`/api/chapters?stage=${STAGE}&subject=${encodeURIComponent(SUBJECT)}`, { token }),
        apiRequest(`/api/sections?stage=${STAGE}&subject=${encodeURIComponent(SUBJECT)}`, { token }),
        fetchTags({ token, stage: STAGE, subject: SUBJECT }),
        apiRequest(`/api/chapters/catalog-audit?stage=${STAGE}&subject=${encodeURIComponent(SUBJECT)}`, { token }),
        listKnowledgePoints({ token, limit: 500 }),
        listIngestJobs({ token, limit: 30 }),
        listIngestDocuments({ token, limit: 120 })
      ]);
      setPendingItems(pendingData || []);
      setChapters(chapterData || []);
      setSections(sectionData || []);
      setTags(tagData || []);
      setCatalogAudit(auditData || null);
      setKnowledgePoints(kpData || []);
      setIngestJobs(ingestData || []);
      setIngestDocuments(ingestDocData || []);
      await loadManagedResources();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function loadManagedResources() {
    if (!token || role !== "admin") {
      setManagedItems([]);
      return;
    }
    try {
      const rows = await listAdminResources({
        token,
        q: resourceFilters.q,
        status: resourceFilters.status === "all" ? "" : resourceFilters.status,
        chapterId: isGeneralChapterValue(resourceFilters.chapterId) ? "" : resourceFilters.chapterId,
        chapterMode: toChapterMode(resourceFilters.chapterId),
        sectionId: resourceFilters.sectionId,
        subject: SUBJECT
      });
      const authorFilter = resourceFilters.author.trim();
      const filtered = authorFilter
        ? (rows || []).filter((item) => String(item.author_id || "").includes(authorFilter))
        : (rows || []);
      setManagedItems(filtered);
      setSelectedResourceIds((prev) => prev.filter((id) => filtered.some((item) => item.id === id)));
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function loadKnowledgeData() {
    if (!token || role !== "admin") {
      setKnowledgePoints([]);
      setIngestJobs([]);
      return;
    }
    try {
      const [kpData, ingestData, ingestDocData] = await Promise.all([
        listKnowledgePoints({
          token,
          chapterId: isGeneralChapterValue(knowledgeFilters.chapterId) ? "" : knowledgeFilters.chapterId,
          chapterMode: toChapterMode(knowledgeFilters.chapterId),
          q: knowledgeFilters.q,
          status: knowledgeFilters.status === "all" ? "" : knowledgeFilters.status,
          limit: 600
        }),
        listIngestJobs({ token, limit: 50 }),
        listIngestDocuments({
          token,
          q: ingestDocFilters.q,
          chapterId: isGeneralChapterValue(ingestDocFilters.chapterId) ? "" : ingestDocFilters.chapterId,
          chapterMode: toChapterMode(ingestDocFilters.chapterId),
          limit: 200
        })
      ]);
      setKnowledgePoints(kpData || []);
      setIngestJobs(ingestData || []);
      setIngestDocuments(ingestDocData || []);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleSubmitIngest() {
    if (!ingestForm.url.trim()) {
      setGlobalMessage("请输入要采集的链接");
      return;
    }
    try {
      await submitIngestUrl(
        {
          url: ingestForm.url.trim(),
          title: ingestForm.title.trim() || null,
          stage: STAGE,
          subject: SUBJECT
        },
        token
      );
      setIngestForm({ url: "", title: "" });
      setGlobalMessage("链接采集任务已提交");
      await loadKnowledgeData();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleSemanticSearchIngest() {
    const query = ingestSemanticQuery.trim();
    if (!query) {
      setGlobalMessage("请输入来源语义检索问题");
      return;
    }
    try {
      setIngestSemanticLoading(true);
      const data = await semanticSearchIngestDocuments(
        {
          query,
          stage: STAGE,
          subject: SUBJECT,
          top_k: 20,
          candidate_limit: 320
        },
        token
      );
      setIngestSemanticResults(data?.results || []);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setIngestSemanticLoading(false);
    }
  }

  async function handleBackfillIngest() {
    try {
      setIngestBackfillLoading(true);
      const data = await startIngestBackfill(
        {
          stage: STAGE,
          subject: SUBJECT,
          limit: 120,
          reparse: false,
          reembed: false
        },
        token
      );
      setGlobalMessage(`补算任务已提交 #${data?.job?.id || "-"}`);
      await loadKnowledgeData();
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setIngestBackfillLoading(false);
    }
  }

  async function handleCreateKnowledgePoint() {
    if (!knowledgeForm.chapter_id || !knowledgeForm.kp_code.trim() || !knowledgeForm.name.trim()) {
      setGlobalMessage("请填写章节、知识点编号和名称");
      return;
    }
    if (isGeneralChapterValue(knowledgeForm.chapter_id)) {
      setGlobalMessage("知识点必须绑定真实章节，不能使用通用章节");
      return;
    }
    try {
      await createKnowledgePoint(
        {
          chapter_id: Number(knowledgeForm.chapter_id),
          kp_code: knowledgeForm.kp_code.trim(),
          name: knowledgeForm.name.trim(),
          aliases: parseTagInput(knowledgeForm.aliases),
          description: knowledgeForm.description.trim() || null,
          difficulty: knowledgeForm.difficulty.trim() || null,
          prerequisite_level: Number(knowledgeForm.prerequisite_level || 0),
          status: knowledgeForm.status || "published"
        },
        token
      );
      setKnowledgeForm((prev) => ({
        ...prev,
        kp_code: "",
        name: "",
        aliases: "",
        description: ""
      }));
      setGlobalMessage("知识点已创建");
      await loadKnowledgeData();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleCreateKnowledgeEdge() {
    if (!edgeForm.src_kp_id || !edgeForm.dst_kp_id) {
      setGlobalMessage("请选择关系起点和终点");
      return;
    }
    try {
      await createKnowledgeEdge(
        {
          src_kp_id: Number(edgeForm.src_kp_id),
          dst_kp_id: Number(edgeForm.dst_kp_id),
          edge_type: edgeForm.edge_type,
          strength: Number(edgeForm.strength),
          evidence_count: 0
        },
        token
      );
      setGlobalMessage("知识关系已创建");
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleToggleKnowledgeStatus(item) {
    const nextStatus = item.status === "published" ? "hidden" : "published";
    try {
      await updateKnowledgePoint(item.id, { status: nextStatus }, token);
      setGlobalMessage(`知识点已设为${nextStatus === "published" ? "公开" : "隐藏"}`);
      await loadKnowledgeData();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleSyncStrictCatalog() {
    try {
      const result = await apiRequest("/api/chapters/sync-strict", {
        method: "POST",
        token
      });
      setGlobalMessage(
        `目录同步完成：新增 ${result.created_count}，更新 ${result.updated_count}，禁用 ${result.disabled_count}`
      );
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function loadTrash(targetPage = trashPage) {
    if (!token || role !== "admin") {
      setTrashItems([]);
      setTrashTotal(0);
      return;
    }

    setTrashLoading(true);
    try {
      const data = await listTrashItems({
        token,
        scope: trashScope === "all" ? "" : trashScope,
        q: trashQuery,
        page: targetPage,
        pageSize: trashPageSize
      });
      setTrashItems(data?.items || []);
      setTrashTotal(data?.total || 0);
      setTrashPage(data?.page || targetPage);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setTrashLoading(false);
    }
  }

  useEffect(() => {
    const panel = new URLSearchParams(window.location.search).get("panel");
    if (panel === "trash") {
      setActiveTab("trash");
    }
  }, []);

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role]);

  useEffect(() => {
    loadManagedResources();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role, resourceFilters.q, resourceFilters.status, resourceFilters.chapterId, resourceFilters.sectionId, resourceFilters.author]);

  useEffect(() => {
    loadTrash(trashPage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role, trashScope, trashQuery, trashPage, trashPageSize]);

  useEffect(() => {
    if (activeTab !== "knowledge") {
      return;
    }
    loadKnowledgeData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    token,
    role,
    activeTab,
    knowledgeFilters.chapterId,
    knowledgeFilters.q,
    knowledgeFilters.status,
    ingestDocFilters.chapterId,
    ingestDocFilters.q
  ]);

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

  function openReviewModal(resourceId, status) {
    const defaultTemplate = status === "approved" ? APPROVE_NOTE_TEMPLATES[0] : REJECT_NOTE_TEMPLATES[0];
    setReviewModal({
      open: true,
      resourceId,
      status,
      template: defaultTemplate,
      extra: ""
    });
  }

  async function submitReview(event) {
    event.preventDefault();
    if (!reviewModal.resourceId) {
      return;
    }
    const note = [reviewModal.template.trim(), reviewModal.extra.trim()].filter(Boolean).join("；");

    try {
      await apiRequest(`/api/resources/${reviewModal.resourceId}/review`, {
        method: "PATCH",
        token,
        body: {
          status: reviewModal.status,
          review_note: note || null
        }
      });
      setReviewModal({
        open: false,
        resourceId: null,
        status: "approved",
        template: "",
        extra: ""
      });
      setGlobalMessage(`审核已更新：${reviewModal.status}`);
      notifyResourcesChanged();
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleDeleteResource(resourceId) {
    const ok = window.confirm(`确认将资源 #${resourceId} 移入回收站吗？`);
    if (!ok) {
      return;
    }
    try {
      await apiRequest(`/api/resources/${resourceId}`, {
        method: "DELETE",
        token
      });
      setGlobalMessage(`资源 #${resourceId} 已移入回收站`);
      notifyResourcesChanged();
      await loadAll();
      await loadTrash(1);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleSetVisibility(resourceId, visibility) {
    try {
      await setResourceVisibility(resourceId, visibility, token);
      setGlobalMessage(visibility === "public" ? "资源已公开" : "资源已设为不公开");
      notifyResourcesChanged();
      await loadManagedResources();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function openResourceTagModal(item) {
    setResourceTagModal({
      open: true,
      resourceId: item.id,
      title: item.title,
      tagsText: tagsToCsv(item.tags || []),
      mode: "replace"
    });
  }

  async function submitResourceTags(event) {
    event.preventDefault();
    if (!resourceTagModal.resourceId) {
      return;
    }
    try {
      await updateResourceTags(
        resourceTagModal.resourceId,
        {
          tags: parseTagInput(resourceTagModal.tagsText),
          mode: resourceTagModal.mode
        },
        token
      );
      setGlobalMessage("资源标签已更新");
      setResourceTagModal({
        open: false,
        resourceId: null,
        title: "",
        tagsText: "",
        mode: "replace"
      });
      notifyResourcesChanged();
      await loadManagedResources();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleAdoptAiTags(resourceId, strategy = "merge") {
    try {
      await adoptResourceAiTags(resourceId, { strategy }, token);
      setGlobalMessage(strategy === "replace" ? "已用 AI 标签覆盖人工标签" : "AI 标签已合并到人工标签");
      notifyResourcesChanged();
      await loadManagedResources();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function toggleResourceSelection(resourceId) {
    setSelectedResourceIds((prev) => (
      prev.includes(resourceId)
        ? prev.filter((id) => id !== resourceId)
        : [...prev, resourceId]
    ));
  }

  function toggleSelectAllManaged() {
    if (!managedItems.length) {
      return;
    }
    if (selectedResourceIds.length === managedItems.length) {
      setSelectedResourceIds([]);
      return;
    }
    setSelectedResourceIds(managedItems.map((item) => item.id));
  }

  async function handleBulkManage() {
    if (!selectedResourceIds.length) {
      setGlobalMessage("请先勾选资源");
      return;
    }
    const actionLabel = bulkAction === "publish" ? "公开" : bulkAction === "hide" ? "不公开" : "删除到回收站";
    const ok = window.confirm(`确认批量执行「${actionLabel}」吗？`);
    if (!ok) {
      return;
    }
    try {
      const result = await bulkManageResources(
        {
          resource_ids: selectedResourceIds,
          action: bulkAction,
          note: bulkNote.trim() || null
        },
        token
      );
      setGlobalMessage(
        `批量操作完成：成功 ${result.succeeded}，失败 ${result.failed}`
      );
      setSelectedResourceIds([]);
      setBulkNote("");
      notifyResourcesChanged();
      await loadAll();
      if (bulkAction === "trash") {
        await loadTrash(1);
      }
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function openChapterModal(mode, chapter = null) {
    setChapterModal({
      open: true,
      mode,
      chapterId: chapter?.id || null,
      form: chapter ? chapterToForm(chapter) : defaultChapterForm(volumeOptions[0] || null)
    });
  }

  async function submitChapter(event) {
    event.preventDefault();
    const textbook =
      chapterModal.form.textbook_mode === "其他"
        ? chapterModal.form.textbook_custom.trim() || null
        : chapterModal.form.textbook_mode;
    const parsedKeywords = chapterModal.form.chapter_keywords
      .split(/[，,]/)
      .map((item) => item.trim())
      .filter(Boolean);

    try {
      if (chapterModal.mode === "create") {
        await apiRequest("/api/chapters", {
          method: "POST",
          token,
          body: {
            stage: STAGE,
            subject: SUBJECT,
            grade: chapterModal.form.grade,
            textbook,
            volume_code: chapterModal.form.volume_code,
            volume_name: chapterModal.form.volume_name,
            volume_order: Number(chapterModal.form.volume_order) || 10,
            chapter_order: Number(chapterModal.form.chapter_order) || 10,
            chapter_code: chapterModal.form.chapter_code.trim(),
            title: chapterModal.form.title.trim(),
            chapter_keywords: parsedKeywords
          }
        });
        setGlobalMessage("章节已新增");
      } else {
        const updateBody = strictCatalog
          ? {
              grade: chapterModal.form.grade,
              textbook,
              chapter_order: Number(chapterModal.form.chapter_order) || 10,
              chapter_keywords: parsedKeywords,
              is_enabled: chapterModal.form.is_enabled
            }
          : {
              grade: chapterModal.form.grade,
              volume_code: chapterModal.form.volume_code,
              volume_name: chapterModal.form.volume_name,
              volume_order: Number(chapterModal.form.volume_order) || 10,
              chapter_order: Number(chapterModal.form.chapter_order) || 10,
              chapter_code: chapterModal.form.chapter_code.trim(),
              title: chapterModal.form.title.trim(),
              textbook,
              chapter_keywords: parsedKeywords,
              is_enabled: chapterModal.form.is_enabled
            };
        await apiRequest(`/api/chapters/${chapterModal.chapterId}`, {
          method: "PATCH",
          token,
          body: updateBody
        });
        setGlobalMessage("章节已更新");
      }
      setChapterModal({ open: false, mode: "create", chapterId: null, form: defaultChapterForm(volumeOptions[0] || null) });
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function openSectionModal(mode, section = null) {
    setSectionModal({
      open: true,
      mode,
      sectionId: section?.id || null,
      form: section ? sectionToForm(section) : defaultSectionForm()
    });
  }

  async function submitSection(event) {
    event.preventDefault();
    const payload = {
      code: normalizeSectionCode(sectionModal.form.code),
      name: sectionModal.form.name.trim(),
      description: sectionModal.form.description.trim() || null,
      sort_order: Number(sectionModal.form.sort_order) || 100,
      is_enabled: sectionModal.form.is_enabled
    };

    try {
      if (sectionModal.mode === "create") {
        await apiRequest("/api/sections", {
          method: "POST",
          token,
          body: {
            stage: STAGE,
            subject: SUBJECT,
            ...payload
          }
        });
        setGlobalMessage("板块已新增");
      } else {
        await apiRequest(`/api/sections/${sectionModal.sectionId}`, {
          method: "PATCH",
          token,
          body: payload
        });
        setGlobalMessage("板块已更新");
      }
      setSectionModal({ open: false, mode: "create", sectionId: null, form: defaultSectionForm() });
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function moveSection(sectionId, direction) {
    const ordered = [...sections].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
    const index = ordered.findIndex((item) => item.id === sectionId);
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) {
      return;
    }
    const swapped = [...ordered];
    [swapped[index], swapped[targetIndex]] = [swapped[targetIndex], swapped[index]];
    const items = swapped.map((item, idx) => ({ id: item.id, sort_order: (idx + 1) * 10 }));

    try {
      await apiRequest("/api/sections/reorder", {
        method: "POST",
        token,
        body: { items }
      });
      setGlobalMessage("板块排序已更新");
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  function openTagModal(mode, tag = null) {
    setTagModal({
      open: true,
      mode,
      tagId: tag?.id || null,
      form: tag ? tagToForm(tag) : defaultTagForm()
    });
  }

  async function submitTag(event) {
    event.preventDefault();
    const payload = {
      tag: tagModal.form.tag.trim(),
      category: tagModal.form.category,
      sort_order: Number(tagModal.form.sort_order) || 100,
      is_enabled: tagModal.form.is_enabled
    };

    try {
      if (tagModal.mode === "create") {
        await createTag(
          {
            stage: STAGE,
            subject: SUBJECT,
            ...payload
          },
          token
        );
        setGlobalMessage("标签已新增");
      } else {
        await updateTag(tagModal.tagId, payload, token);
        setGlobalMessage("标签已更新");
      }
      setTagModal({ open: false, mode: "create", tagId: null, form: defaultTagForm() });
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function moveTag(tagId, direction) {
    const ordered = [...tags].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);
    const index = ordered.findIndex((item) => item.id === tagId);
    const targetIndex = direction === "up" ? index - 1 : index + 1;
    if (index < 0 || targetIndex < 0 || targetIndex >= ordered.length) {
      return;
    }
    const swapped = [...ordered];
    [swapped[index], swapped[targetIndex]] = [swapped[targetIndex], swapped[index]];
    const items = swapped.map((item, idx) => ({ id: item.id, sort_order: (idx + 1) * 10 }));

    try {
      await reorderTags(items, token);
      setGlobalMessage("标签排序已更新");
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleRestoreTrash(itemId) {
    try {
      const result = await restoreTrashItem(itemId, token);
      setGlobalMessage(result?.message || "已恢复");
      notifyResourcesChanged();
      await loadTrash(trashPage);
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handlePurgeTrash(itemId) {
    const ok = window.confirm("确认彻底删除该回收项吗？该操作不可恢复。");
    if (!ok) {
      return;
    }
    try {
      const result = await purgeTrashItem(itemId, token);
      setGlobalMessage(result?.message || "已彻底删除");
      await loadTrash(trashPage);
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handlePurgeExpired() {
    try {
      const result = await purgeExpiredTrash(token, 2000);
      setGlobalMessage(`过期清理完成：${result?.purged_count || 0} 条`);
      await loadTrash(1);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleReconcile() {
    try {
      const result = await reconcileStorage({ token });
      setGlobalMessage(
        `对账完成：扫描 ${result.scanned_count}，缺失 ${result.missing_count}，入回收站 ${result.trashed_count}`
      );
      await loadTrash(1);
      await loadAll();
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  const orderedSections = useMemo(
    () => [...sections].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
    [sections]
  );
  const filteredSections = useMemo(() => {
    const keyword = sectionFilter.trim().toLowerCase();
    return orderedSections.filter((item) => {
      const statusOk =
        sectionStatus === "all" ||
        (sectionStatus === "enabled" && item.is_enabled) ||
        (sectionStatus === "disabled" && !item.is_enabled);
      const text = `${item.name} ${item.code} ${item.description || ""}`.toLowerCase();
      return statusOk && (!keyword || text.includes(keyword));
    });
  }, [orderedSections, sectionFilter, sectionStatus]);

  const orderedTags = useMemo(
    () => [...tags].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id),
    [tags]
  );
  const filteredTags = useMemo(() => {
    const keyword = tagFilter.trim().toLowerCase();
    return orderedTags.filter((item) => {
      const statusOk =
        tagStatus === "all" ||
        (tagStatus === "enabled" && item.is_enabled) ||
        (tagStatus === "disabled" && !item.is_enabled);
      const text = `${item.tag} ${item.category}`.toLowerCase();
      return statusOk && (!keyword || text.includes(keyword));
    });
  }, [orderedTags, tagFilter, tagStatus]);

  const chapterMap = useMemo(() => {
    const map = {};
    for (const row of chapters) {
      map[row.id] = `${row.chapter_code} ${row.title}`;
    }
    return map;
  }, [chapters]);

  const sectionMap = useMemo(() => {
    const map = {};
    for (const row of sections) {
      map[row.id] = row.name;
    }
    return map;
  }, [sections]);

  const managedOrdered = useMemo(
    () => [...managedItems].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at)),
    [managedItems]
  );
  const filteredKnowledgePoints = useMemo(() => {
    return [...knowledgePoints].sort((a, b) => {
      const chapterA = Number(a.chapter_id || 0);
      const chapterB = Number(b.chapter_id || 0);
      if (chapterA !== chapterB) {
        return chapterA - chapterB;
      }
      return String(a.kp_code || "").localeCompare(String(b.kp_code || ""), "zh-CN");
    });
  }, [knowledgePoints]);
  const visibleIngestDocuments = useMemo(() => {
    if (isGeneralChapterValue(ingestDocFilters.chapterId)) {
      return (ingestDocuments || []).filter((item) => !item.chapter_id);
    }
    return ingestDocuments || [];
  }, [ingestDocuments, ingestDocFilters.chapterId]);

  const statusLabel = {
    pending: "待审核",
    approved: "公开",
    rejected: "驳回",
    hidden: "不公开"
  };

  function renderResourceChapterLabel(item) {
    if (item?.chapter_id) {
      return chapterMap[item.chapter_id] || item.chapter_id;
    }
    const links = Array.isArray(item?.chapter_ids) ? item.chapter_ids : [];
    if (links.length) {
      return links
        .map((chapterId) => chapterMap[chapterId] || chapterId)
        .join(" / ");
    }
    return GENERAL_CHAPTER_LABEL;
  }

  if (!token) {
    return (
      <section className="card">
        <h2>管理后台</h2>
        <p className="hint">该页面需管理员登录</p>
        <form onSubmit={handleLogin}>
          <input
            type="text"
            placeholder="管理员账号"
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

  if (role !== "admin") {
    return (
      <section className="card">
        <h2>管理后台</h2>
        <p className="hint">当前账号无管理员权限</p>
      </section>
    );
  }

  const reviewTemplates = reviewModal.status === "approved" ? APPROVE_NOTE_TEMPLATES : REJECT_NOTE_TEMPLATES;
  const totalTrashPages = Math.max(1, Math.ceil((trashTotal || 0) / trashPageSize));

  return (
    <>
      <section className="card">
        <h2>管理后台</h2>
        <div className="type-tabs">
          <button type="button" className={activeTab === "resources" ? "active" : ""} onClick={() => setActiveTab("resources")}>
            资源管理
          </button>
          <button type="button" className={activeTab === "review" ? "active" : ""} onClick={() => setActiveTab("review")}>
            待审核
          </button>
          <button type="button" className={activeTab === "structure" ? "active" : ""} onClick={() => setActiveTab("structure")}>
            结构配置
          </button>
          <button type="button" className={activeTab === "knowledge" ? "active" : ""} onClick={() => setActiveTab("knowledge")}>
            知识库
          </button>
          <button type="button" className={activeTab === "trash" ? "active" : ""} onClick={() => setActiveTab("trash")}>
            回收站
          </button>
        </div>
      </section>

      {activeTab === "resources" ? (
        <section className="card">
          <h2>资源管理</h2>
          <div className="action-buttons">
            <input
              type="text"
              placeholder="搜索标题/描述"
              value={resourceFilters.q}
              onChange={(event) => setResourceFilters((prev) => ({ ...prev, q: event.target.value }))}
            />
            <select
              value={resourceFilters.status}
              onChange={(event) => setResourceFilters((prev) => ({ ...prev, status: event.target.value }))}
            >
              <option value="all">全部状态</option>
              <option value="pending">待审核</option>
              <option value="approved">公开</option>
              <option value="hidden">不公开</option>
              <option value="rejected">驳回</option>
            </select>
            <select
              value={resourceFilters.chapterId}
              onChange={(event) => setResourceFilters((prev) => ({ ...prev, chapterId: event.target.value }))}
            >
              <option value="">全部章节</option>
              {chaptersWithGeneral.map((chapter) => (
                <option key={chapter.id} value={chapter.id}>
                  {chapter.chapter_code} {chapter.title}
                </option>
              ))}
            </select>
            <select
              value={resourceFilters.sectionId}
              onChange={(event) => setResourceFilters((prev) => ({ ...prev, sectionId: event.target.value }))}
            >
              <option value="">全部板块</option>
              {sections.map((section) => (
                <option key={section.id} value={section.id}>{section.name}</option>
              ))}
            </select>
            <input
              type="text"
              placeholder="上传者ID筛选"
              value={resourceFilters.author}
              onChange={(event) => setResourceFilters((prev) => ({ ...prev, author: event.target.value }))}
            />
          </div>

          <div className="action-buttons">
            <button type="button" className="ghost" onClick={toggleSelectAllManaged}>
              {selectedResourceIds.length === managedOrdered.length && managedOrdered.length ? "取消全选" : "全选"}
            </button>
            <select value={bulkAction} onChange={(event) => setBulkAction(event.target.value)}>
              <option value="hide">批量设为不公开</option>
              <option value="publish">批量公开</option>
              <option value="trash">批量删除到回收站</option>
            </select>
            <input
              type="text"
              placeholder="批量备注（可选）"
              value={bulkNote}
              onChange={(event) => setBulkNote(event.target.value)}
            />
            <button type="button" onClick={handleBulkManage}>执行批量操作</button>
            <span className="hint">已选 {selectedResourceIds.length} 条</span>
          </div>

          {!managedOrdered.length ? (
            <p className="hint">当前筛选无资源</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={selectedResourceIds.length > 0 && selectedResourceIds.length === managedOrdered.length}
                      onChange={toggleSelectAllManaged}
                    />
                  </th>
                  <th>ID</th>
                  <th>标题</th>
                  <th>状态</th>
                  <th>章节/板块</th>
                  <th>上传者</th>
                  <th>标签</th>
                  <th>更新时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {managedOrdered.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <input
                        type="checkbox"
                        checked={selectedResourceIds.includes(item.id)}
                        onChange={() => toggleResourceSelection(item.id)}
                      />
                    </td>
                    <td>{item.id}</td>
                    <td>{item.title}</td>
                    <td>{statusLabel[item.status] || item.status}</td>
                    <td>
                      <div>{renderResourceChapterLabel(item)}</div>
                      <div className="hint">{sectionMap[item.section_id] || "-"}</div>
                    </td>
                    <td>{item.author_id}</td>
                    <td>
                      <div className="hint">人工：{item.tags?.length ? item.tags.join("、") : "-"}</div>
                      <div className="hint">AI：{item.ai_tags?.length ? item.ai_tags.join("、") : "-"}</div>
                    </td>
                    <td>{formatTime(item.updated_at)}</td>
                    <td className="action-buttons">
                      {item.status !== "approved" ? (
                        <button type="button" onClick={() => handleSetVisibility(item.id, "public")}>公开</button>
                      ) : (
                        <button type="button" className="ghost" disabled>已公开</button>
                      )}
                      {item.status !== "hidden" ? (
                        <button type="button" className="ghost" onClick={() => handleSetVisibility(item.id, "hidden")}>不公开</button>
                      ) : (
                        <button type="button" className="ghost" disabled>已不公开</button>
                      )}
                      <button type="button" className="ghost" onClick={() => openResourceTagModal(item)}>
                        编辑标签
                      </button>
                      <button type="button" className="ghost" onClick={() => handleAdoptAiTags(item.id, "merge")}>
                        采纳AI标签
                      </button>
                      <button type="button" className="danger" onClick={() => handleDeleteResource(item.id)}>
                        删除到回收站
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {activeTab === "review" ? (
        <section className="card">
          <h2>待审核资源</h2>
          {pendingItems.length === 0 ? (
            <p>当前没有待审核资源</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>标题</th>
                  <th>上传者</th>
                  <th>创建时间</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {pendingItems.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.title}</td>
                    <td>{item.author_id}</td>
                    <td>{formatTime(item.created_at)}</td>
                    <td className="action-buttons">
                      <button type="button" onClick={() => openReviewModal(item.id, "approved")}>通过</button>
                      <button type="button" className="danger" onClick={() => openReviewModal(item.id, "rejected")}>
                        驳回
                      </button>
                      <button type="button" className="danger" onClick={() => handleDeleteResource(item.id)}>
                        删除到回收站
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}

      {activeTab === "structure" ? (
        <>
          <section className="card">
            <h2>章节管理</h2>
            <div className="action-buttons">
              <button type="button" onClick={() => openChapterModal("create")} disabled={strictCatalog}>
                新增章节
              </button>
              <button type="button" className="ghost" onClick={handleSyncStrictCatalog}>
                同步严格目录
              </button>
            </div>
            <p className="hint">当前范围：高中 / 物理（固定）</p>
            {catalogAudit ? (
              <p className="hint">
                目录版本 {catalogAudit.catalog_version} · 期望 {catalogAudit.expected_count} 章 ·
                缺失 {catalogAudit.missing_count} · 非目录启用 {catalogAudit.unexpected_enabled_count}
                {strictCatalog ? " · 严格模式已开启" : ""}
              </p>
            ) : null}
            {strictCatalog ? (
              <p className="hint">严格目录模式：章节名/章节号/册别不可手工修改。</p>
            ) : null}
            {!chapters.length ? (
              <p className="hint">暂无章节</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>章节</th>
                    <th>教材</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {chapters.map((chapter) => (
                    <tr key={chapter.id}>
                      <td>{chapter.id}</td>
                      <td>
                        <div>{chapter.volume_name} · {chapter.grade} · {chapter.chapter_code} {chapter.title}</div>
                        <div className="hint">册码 {chapter.volume_code}（册序 {chapter.volume_order} / 章序 {chapter.chapter_order}）</div>
                      </td>
                      <td>{chapter.textbook || "-"}</td>
                      <td>{chapter.is_enabled ? "启用" : "停用"}</td>
                      <td className="action-buttons">
                        <button type="button" className="ghost" onClick={() => openChapterModal("edit", chapter)}>编辑</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <h2>板块管理</h2>
            <div className="action-buttons">
              <button type="button" onClick={() => openSectionModal("create")}>新增板块</button>
              <input
                type="text"
                placeholder="筛选板块"
                value={sectionFilter}
                onChange={(event) => setSectionFilter(event.target.value)}
              />
              <select value={sectionStatus} onChange={(event) => setSectionStatus(event.target.value)}>
                <option value="all">全部状态</option>
                <option value="enabled">仅启用</option>
                <option value="disabled">仅停用</option>
              </select>
            </div>
            {!filteredSections.length ? (
              <p className="hint">暂无板块</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>板块</th>
                    <th>排序</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSections.map((section) => (
                    <tr key={section.id}>
                      <td>{section.id}</td>
                      <td>
                        <div>{section.name} ({section.code})</div>
                        {section.description ? <div className="hint">{section.description}</div> : null}
                      </td>
                      <td>{section.sort_order}</td>
                      <td>{section.is_enabled ? "启用" : "停用"}</td>
                      <td className="action-buttons">
                        <button type="button" className="ghost" onClick={() => openSectionModal("edit", section)}>编辑</button>
                        <button type="button" className="ghost" onClick={() => moveSection(section.id, "up")}>上移</button>
                        <button type="button" className="ghost" onClick={() => moveSection(section.id, "down")}>下移</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <h2>标签库管理</h2>
            <div className="action-buttons">
              <button type="button" onClick={() => openTagModal("create")}>新增标签</button>
              <input
                type="text"
                placeholder="筛选标签"
                value={tagFilter}
                onChange={(event) => setTagFilter(event.target.value)}
              />
              <select value={tagStatus} onChange={(event) => setTagStatus(event.target.value)}>
                <option value="all">全部状态</option>
                <option value="enabled">仅启用</option>
                <option value="disabled">仅停用</option>
              </select>
            </div>
            {!filteredTags.length ? (
              <p className="hint">暂无标签</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>标签</th>
                    <th>分类</th>
                    <th>排序</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTags.map((item) => (
                    <tr key={item.id}>
                      <td>{item.id}</td>
                      <td>{item.tag}</td>
                      <td>{item.category}</td>
                      <td>{item.sort_order}</td>
                      <td>{item.is_enabled ? "启用" : "停用"}</td>
                      <td className="action-buttons">
                        <button type="button" className="ghost" onClick={() => openTagModal("edit", item)}>编辑</button>
                        <button type="button" className="ghost" onClick={() => moveTag(item.id, "up")}>上移</button>
                        <button type="button" className="ghost" onClick={() => moveTag(item.id, "down")}>下移</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      ) : null}

      {activeTab === "knowledge" ? (
        <>
          <section className="card">
            <h2>来源采集（URL）</h2>
            <div className="action-buttons">
              <input
                type="url"
                placeholder="https://..."
                value={ingestForm.url}
                onChange={(event) => setIngestForm((prev) => ({ ...prev, url: event.target.value }))}
              />
              <input
                type="text"
                placeholder="可选标题"
                value={ingestForm.title}
                onChange={(event) => setIngestForm((prev) => ({ ...prev, title: event.target.value }))}
              />
              <button type="button" onClick={handleSubmitIngest}>提交采集</button>
              <button type="button" className="ghost" onClick={handleBackfillIngest} disabled={ingestBackfillLoading}>
                {ingestBackfillLoading ? "补算中..." : "历史补算"}
              </button>
            </div>
            {!ingestJobs.length ? (
              <p className="hint">暂无采集任务</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>URL</th>
                    <th>状态</th>
                    <th>进度</th>
                    <th>详情</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {ingestJobs.map((job) => (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{job.url || "-"}</td>
                      <td>{job.status}</td>
                      <td>{Math.round((job.progress || 0) * 100)}%</td>
                      <td>{job.detail || "-"}</td>
                      <td>{formatTime(job.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="action-buttons" style={{ marginTop: 12 }}>
              <input
                type="text"
                placeholder="来源文档搜索（标题/摘要/正文）"
                value={ingestDocFilters.q}
                onChange={(event) => setIngestDocFilters((prev) => ({ ...prev, q: event.target.value }))}
              />
              <select
                value={ingestDocFilters.chapterId}
                onChange={(event) => setIngestDocFilters((prev) => ({ ...prev, chapterId: event.target.value }))}
              >
                <option value="">全部章节</option>
                {chaptersWithGeneral.map((chapter) => (
                  <option key={`ingest-doc-chapter-${chapter.id}`} value={chapter.id}>
                    {chapter.chapter_code} {chapter.title}
                  </option>
                ))}
              </select>
            </div>
            {!visibleIngestDocuments.length ? (
              <p className="hint">暂无来源文档</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>标题</th>
                    <th>章节</th>
                    <th>正文长度</th>
                    <th>索引状态</th>
                    <th>解析状态</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleIngestDocuments.map((item) => (
                    <tr key={`source-doc-${item.id}`}>
                      <td>{item.id}</td>
                      <td>
                        <div>{item.title || "-"}</div>
                        <div className="hint">{item.url || "-"}</div>
                        {item.content_excerpt ? <div className="hint">{item.content_excerpt}</div> : null}
                      </td>
                      <td>{item.chapter_id ? (chapterMap[item.chapter_id] || item.chapter_id) : GENERAL_CHAPTER_LABEL}</td>
                      <td>{item.content_chars || 0}{item.content_truncated ? "（截断）" : ""}</td>
                      <td>{item.content_indexed_at ? `已索引 ${formatTime(item.content_indexed_at)}` : "未索引"}</td>
                      <td>{item.parse_error || "正常"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="action-buttons" style={{ marginTop: 12 }}>
              <input
                type="text"
                placeholder="来源语义搜索（例如：楞次定律实验原理）"
                value={ingestSemanticQuery}
                onChange={(event) => setIngestSemanticQuery(event.target.value)}
              />
              <button type="button" onClick={handleSemanticSearchIngest} disabled={ingestSemanticLoading}>
                {ingestSemanticLoading ? "检索中..." : "来源语义搜索"}
              </button>
            </div>
            {ingestSemanticResults.length ? (
              <table>
                <thead>
                  <tr>
                    <th>概率</th>
                    <th>来源文档</th>
                    <th>章节</th>
                    <th>片段</th>
                  </tr>
                </thead>
                <tbody>
                  {ingestSemanticResults.map((item, index) => {
                    const doc = item.document;
                    return (
                      <tr key={`semantic-doc-${doc?.id || index}`}>
                        <td>{((item.probability || item.score || 0) * 100).toFixed(1)}%</td>
                        <td>
                          <div>{doc?.title || "-"}</div>
                          <div className="hint">{doc?.url || "-"}</div>
                        </td>
                        <td>{doc?.chapter_id ? (chapterMap[doc.chapter_id] || doc.chapter_id) : GENERAL_CHAPTER_LABEL}</td>
                        <td>{doc?.content_excerpt || doc?.summary || "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : null}
          </section>

          <section className="card">
            <h2>知识点管理</h2>
            <div className="action-buttons">
              <select
                value={knowledgeFilters.chapterId}
                onChange={(event) => setKnowledgeFilters((prev) => ({ ...prev, chapterId: event.target.value }))}
              >
                <option value="">全部章节</option>
                {chaptersWithGeneral.map((chapter) => (
                  <option key={chapter.id} value={chapter.id}>
                    {chapter.volume_name} {chapter.chapter_code} {chapter.title}
                  </option>
                ))}
              </select>
              <input
                type="text"
                placeholder="搜索知识点"
                value={knowledgeFilters.q}
                onChange={(event) => setKnowledgeFilters((prev) => ({ ...prev, q: event.target.value }))}
              />
              <select
                value={knowledgeFilters.status}
                onChange={(event) => setKnowledgeFilters((prev) => ({ ...prev, status: event.target.value }))}
              >
                <option value="all">全部状态</option>
                <option value="published">公开</option>
                <option value="hidden">隐藏</option>
                <option value="draft">草稿</option>
              </select>
            </div>

            <div className="action-buttons">
              <select
                value={knowledgeForm.chapter_id}
                onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, chapter_id: event.target.value }))}
              >
                <option value="">选择章节</option>
                {chaptersWithGeneral.map((chapter) => (
                  <option
                    key={chapter.id}
                    value={chapter.id}
                    disabled={String(chapter.id) === GENERAL_CHAPTER_VALUE}
                  >
                    {chapter.chapter_code} {chapter.title}
                  </option>
                ))}
              </select>
              {knowledgeForm.chapter_id === GENERAL_CHAPTER_VALUE ? (
                <span className="hint">该功能需真实章节</span>
              ) : null}
              <input
                type="text"
                placeholder="知识点编号"
                value={knowledgeForm.kp_code}
                onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, kp_code: event.target.value }))}
              />
              <input
                type="text"
                placeholder="知识点名称"
                value={knowledgeForm.name}
                onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, name: event.target.value }))}
              />
              <input
                type="text"
                placeholder="别名（逗号分隔）"
                value={knowledgeForm.aliases}
                onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, aliases: event.target.value }))}
              />
              <input
                type="text"
                placeholder="难度（可选）"
                value={knowledgeForm.difficulty}
                onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, difficulty: event.target.value }))}
              />
              <button type="button" onClick={handleCreateKnowledgePoint}>新增知识点</button>
            </div>
            <textarea
              placeholder="知识点描述（可选）"
              value={knowledgeForm.description}
              onChange={(event) => setKnowledgeForm((prev) => ({ ...prev, description: event.target.value }))}
            />

            {!filteredKnowledgePoints.length ? (
              <p className="hint">暂无知识点数据</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>章节</th>
                    <th>知识点</th>
                    <th>先修度</th>
                    <th>状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                {filteredKnowledgePoints.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{chapterMap[item.chapter_id] || item.chapter_id || GENERAL_CHAPTER_LABEL}</td>
                      <td>
                        <div>{item.kp_code} {item.name}</div>
                        <div className="hint">{item.description || "-"}</div>
                      </td>
                      <td>{Number(item.prerequisite_level || 0).toFixed(2)}</td>
                      <td>{item.status}</td>
                      <td className="action-buttons">
                        <button type="button" className="ghost" onClick={() => handleToggleKnowledgeStatus(item)}>
                          {item.status === "published" ? "设为隐藏" : "设为公开"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <h2>知识关系（先修/关联）</h2>
            <div className="action-buttons">
              <select
                value={edgeForm.src_kp_id}
                onChange={(event) => setEdgeForm((prev) => ({ ...prev, src_kp_id: event.target.value }))}
              >
                <option value="">起点知识点</option>
                {filteredKnowledgePoints.map((item) => (
                  <option key={`src-${item.id}`} value={item.id}>
                    {item.kp_code} {item.name}
                  </option>
                ))}
              </select>
              <select
                value={edgeForm.dst_kp_id}
                onChange={(event) => setEdgeForm((prev) => ({ ...prev, dst_kp_id: event.target.value }))}
              >
                <option value="">终点知识点</option>
                {filteredKnowledgePoints.map((item) => (
                  <option key={`dst-${item.id}`} value={item.id}>
                    {item.kp_code} {item.name}
                  </option>
                ))}
              </select>
              <select
                value={edgeForm.edge_type}
                onChange={(event) => setEdgeForm((prev) => ({ ...prev, edge_type: event.target.value }))}
              >
                <option value="prerequisite">先修关系</option>
                <option value="related">关联关系</option>
                <option value="contains">包含关系</option>
                <option value="applies_to">应用关系</option>
              </select>
              <input
                type="number"
                min="0"
                max="1"
                step="0.05"
                value={edgeForm.strength}
                onChange={(event) => setEdgeForm((prev) => ({ ...prev, strength: event.target.value }))}
              />
              <button type="button" onClick={handleCreateKnowledgeEdge}>创建关系</button>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === "trash" ? (
        <section className="card">
          <h2>回收站管理</h2>
          <div className="action-buttons">
            <select
              value={trashScope}
              onChange={(event) => {
                setTrashScope(event.target.value);
                setTrashPage(1);
              }}
            >
              <option value="all">全部类型</option>
              <option value="resource">资源回收</option>
              <option value="storage">存储回收</option>
            </select>
            <input
              type="text"
              placeholder="搜索路径或来源"
              value={trashQuery}
              onChange={(event) => {
                setTrashQuery(event.target.value);
                setTrashPage(1);
              }}
            />
            <button type="button" className="ghost" onClick={handleReconcile}>立即对账</button>
            <button type="button" className="ghost" onClick={handlePurgeExpired}>清理过期</button>
          </div>
          {trashLoading ? <p className="hint">回收站加载中...</p> : null}
          {!trashLoading && trashItems.length === 0 ? (
            <p className="hint">回收站为空</p>
          ) : null}
          {!trashLoading && trashItems.length ? (
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>类型</th>
                  <th>资源</th>
                  <th>原路径</th>
                  <th>来源</th>
                  <th>删除时间</th>
                  <th>到期时间</th>
                  <th>二进制</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {trashItems.map((item) => (
                  <tr key={item.id}>
                    <td>{item.id}</td>
                    <td>{item.scope}</td>
                    <td>{item.resource_title || item.resource_id || "-"}</td>
                    <td>{item.original_key}</td>
                    <td>{item.source}</td>
                    <td>{formatTime(item.deleted_at)}</td>
                    <td>{formatTime(item.expires_at)}</td>
                    <td>{item.has_binary ? "可恢复" : "仅记录"}</td>
                    <td className="action-buttons">
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => handleRestoreTrash(item.id)}
                        disabled={!item.has_binary}
                      >
                        恢复
                      </button>
                      <button type="button" className="danger" onClick={() => handlePurgeTrash(item.id)}>
                        彻底删除
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
          <div className="action-buttons">
            <button
              type="button"
              className="ghost"
              disabled={trashPage <= 1}
              onClick={() => setTrashPage((page) => Math.max(1, page - 1))}
            >
              上一页
            </button>
            <span className="hint">第 {trashPage} / {totalTrashPages} 页（共 {trashTotal} 条）</span>
            <button
              type="button"
              className="ghost"
              disabled={trashPage >= totalTrashPages}
              onClick={() => setTrashPage((page) => Math.min(totalTrashPages, page + 1))}
            >
              下一页
            </button>
          </div>
        </section>
      ) : null}

      <EditModal
        open={reviewModal.open}
        title={reviewModal.status === "approved" ? "通过审核" : "驳回审核"}
        onClose={() => setReviewModal({ open: false, resourceId: null, status: "approved", template: "", extra: "" })}
        onSubmit={submitReview}
        submitText="确认提交"
      >
        <label>
          审核模板
          <select
            value={reviewModal.template}
            onChange={(event) => setReviewModal({ ...reviewModal, template: event.target.value })}
          >
            {reviewTemplates.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          补充说明（可选）
          <textarea
            value={reviewModal.extra}
            onChange={(event) => setReviewModal({ ...reviewModal, extra: event.target.value })}
          />
        </label>
      </EditModal>

      <EditModal
        open={chapterModal.open}
        title={chapterModal.mode === "create" ? "新增章节" : "编辑章节"}
        onClose={() => setChapterModal({ open: false, mode: "create", chapterId: null, form: defaultChapterForm(volumeOptions[0] || null) })}
        onSubmit={submitChapter}
      >
        <div className="hint">学段：高中（固定） / 学科：物理（固定）</div>
        <label>
          年级
          <select
            value={chapterModal.form.grade}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, grade: event.target.value }
            })}
          >
            {GRADE_OPTIONS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          册别
          <select
            value={chapterModal.form.volume_code}
            disabled={strictCatalog}
            onChange={(event) => {
              const selected = volumeOptions.find((item) => item.code === event.target.value);
              setChapterModal({
                ...chapterModal,
                form: {
                  ...chapterModal.form,
                  volume_code: event.target.value,
                  volume_name: selected?.name || chapterModal.form.volume_name,
                  volume_order: selected?.order || chapterModal.form.volume_order
                }
              });
            }}
          >
            {volumeOptions.map((item) => (
              <option key={item.code} value={item.code}>{item.name}</option>
            ))}
          </select>
        </label>
        <label>
          册显示名
          <input
            type="text"
            value={chapterModal.form.volume_name}
            disabled={strictCatalog}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, volume_name: event.target.value }
            })}
            required
          />
        </label>
        <label>
          册排序
          <input
            type="number"
            min={1}
            value={chapterModal.form.volume_order}
            disabled={strictCatalog}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, volume_order: Number(event.target.value || 10) }
            })}
          />
        </label>
        <label>
          章排序
          <input
            type="number"
            min={1}
            value={chapterModal.form.chapter_order}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, chapter_order: Number(event.target.value || 10) }
            })}
          />
        </label>
        <label>
          教材
          <select
            value={chapterModal.form.textbook_mode}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, textbook_mode: event.target.value }
            })}
          >
            {TEXTBOOK_PRESETS.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <label>
          章节关键词（逗号分隔）
          <input
            type="text"
            value={chapterModal.form.chapter_keywords}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, chapter_keywords: event.target.value }
            })}
            placeholder="例如：牛顿定律,受力分析,加速度"
          />
        </label>
        {chapterModal.form.textbook_mode === "其他" ? (
          <label>
            自定义教材
            <input
              type="text"
              value={chapterModal.form.textbook_custom}
              onChange={(event) => setChapterModal({
                ...chapterModal,
                form: { ...chapterModal.form, textbook_custom: event.target.value }
              })}
            />
          </label>
        ) : null}
        <label>
          章节编号
          <input
            type="text"
            value={chapterModal.form.chapter_code}
            disabled={strictCatalog}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, chapter_code: event.target.value }
            })}
            required
          />
        </label>
        <label>
          章节标题
          <input
            type="text"
            value={chapterModal.form.title}
            disabled={strictCatalog}
            onChange={(event) => setChapterModal({
              ...chapterModal,
              form: { ...chapterModal.form, title: event.target.value }
            })}
            required
          />
        </label>
        {chapterModal.mode === "edit" ? (
          <label className="inline-check">
            <input
              type="checkbox"
              checked={chapterModal.form.is_enabled}
              onChange={(event) => setChapterModal({
                ...chapterModal,
                form: { ...chapterModal.form, is_enabled: event.target.checked }
              })}
            />
            启用章节
          </label>
        ) : null}
      </EditModal>

      <EditModal
        open={sectionModal.open}
        title={sectionModal.mode === "create" ? "新增板块" : "编辑板块"}
        onClose={() => setSectionModal({ open: false, mode: "create", sectionId: null, form: defaultSectionForm() })}
        onSubmit={submitSection}
      >
        <div className="hint">学段：高中（固定） / 学科：物理（固定）</div>
        <label>
          板块代码
          <input
            type="text"
            value={sectionModal.form.code}
            onChange={(event) => setSectionModal({
              ...sectionModal,
              form: { ...sectionModal.form, code: normalizeSectionCode(event.target.value) }
            })}
            placeholder="例如：experiment-design"
            required
          />
        </label>
        <div className="hint">规则：仅小写字母/数字/连字符，建议英文语义码（示例：`simulation-3d`）。</div>
        <label>
          板块名称
          <input
            type="text"
            value={sectionModal.form.name}
            onChange={(event) => setSectionModal({
              ...sectionModal,
              form: { ...sectionModal.form, name: event.target.value }
            })}
            required
          />
        </label>
        <label>
          描述
          <textarea
            value={sectionModal.form.description}
            onChange={(event) => setSectionModal({
              ...sectionModal,
              form: { ...sectionModal.form, description: event.target.value }
            })}
          />
        </label>
        <label>
          排序值
          <input
            type="number"
            value={sectionModal.form.sort_order}
            onChange={(event) => setSectionModal({
              ...sectionModal,
              form: { ...sectionModal.form, sort_order: Number(event.target.value || 100) }
            })}
          />
        </label>
        <label className="inline-check">
          <input
            type="checkbox"
            checked={sectionModal.form.is_enabled}
            onChange={(event) => setSectionModal({
              ...sectionModal,
              form: { ...sectionModal.form, is_enabled: event.target.checked }
            })}
          />
          启用板块
        </label>
      </EditModal>

      <EditModal
        open={tagModal.open}
        title={tagModal.mode === "create" ? "新增标签" : "编辑标签"}
        onClose={() => setTagModal({ open: false, mode: "create", tagId: null, form: defaultTagForm() })}
        onSubmit={submitTag}
      >
        <div className="hint">学段：高中（固定） / 学科：物理（固定）</div>
        <label>
          标签名称
          <input
            type="text"
            value={tagModal.form.tag}
            onChange={(event) => setTagModal({
              ...tagModal,
              form: { ...tagModal.form, tag: event.target.value }
            })}
            required
          />
        </label>
        <label>
          标签分类
          <select
            value={tagModal.form.category}
            onChange={(event) => setTagModal({
              ...tagModal,
              form: { ...tagModal.form, category: event.target.value }
            })}
          >
            {TAG_CATEGORY_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </label>
        <label>
          排序值
          <input
            type="number"
            value={tagModal.form.sort_order}
            onChange={(event) => setTagModal({
              ...tagModal,
              form: { ...tagModal.form, sort_order: Number(event.target.value || 100) }
            })}
          />
        </label>
        <label className="inline-check">
          <input
            type="checkbox"
            checked={tagModal.form.is_enabled}
            onChange={(event) => setTagModal({
              ...tagModal,
              form: { ...tagModal.form, is_enabled: event.target.checked }
            })}
          />
          启用标签
        </label>
      </EditModal>

      <EditModal
        open={resourceTagModal.open}
        title={`资源标签管理 #${resourceTagModal.resourceId || ""}`}
        onClose={() => setResourceTagModal({ open: false, resourceId: null, title: "", tagsText: "", mode: "replace" })}
        onSubmit={submitResourceTags}
      >
        <div className="hint">{resourceTagModal.title || "-"}</div>
        <label>
          更新模式
          <select
            value={resourceTagModal.mode}
            onChange={(event) => setResourceTagModal((prev) => ({ ...prev, mode: event.target.value }))}
          >
            <option value="replace">覆盖人工标签</option>
            <option value="append">追加人工标签</option>
          </select>
        </label>
        <label>
          标签（逗号分隔）
          <textarea
            value={resourceTagModal.tagsText}
            onChange={(event) => setResourceTagModal((prev) => ({ ...prev, tagsText: event.target.value }))}
            placeholder="例如：牛顿第二定律,受力分析,典型例题"
          />
        </label>
        <div className="hint">AI标签不会被覆盖，可用“采纳AI标签”一键合并。</div>
      </EditModal>
    </>
  );
}
