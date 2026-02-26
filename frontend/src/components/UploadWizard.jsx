import { useEffect, useMemo, useRef, useState } from "react";
import TagPicker from "./TagPicker";
import { autoClassifyResource, getUploadPathPreview } from "../lib/api";

function todayDateCode() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}${m}${d}`;
}

function typeLabel(value) {
  return {
    document: "文档",
    ppt: "课件",
    video: "视频",
    image: "图片",
    audio: "音频",
    exercise: "习题"
  }[value] || "资源";
}

function cleanKeyword(raw) {
  const value = (raw || "").replace(/\.[^/.]+$/, "");
  const sanitized = value
    .replace(/[\\/_\-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 16);
  return sanitized || "资源";
}

function buildAutoTitle({ volumeCode, chapter, section, fileName }) {
  const volumePart = volumeCode || chapter?.volume_code || "unassigned";
  const chapterPart = chapter?.chapter_code || "unassigned";
  const sectionPart = section?.code || "general";
  const keyword = cleanKeyword(fileName || "");
  return `${volumePart}-${chapterPart}-${sectionPart}-${keyword}-${todayDateCode()}`;
}

function formatPercent(value) {
  const number = Number(value || 0) * 100;
  if (number <= 0) {
    return "0.0%";
  }
  if (number < 0.1) {
    return "<0.1%";
  }
  return `${number.toFixed(1)}%`;
}

const DESCRIPTION_TEMPLATES = [
  { key: "course", label: "课程讲解型", text: "本资源用于课堂讲解，包含核心概念、典型例题与易错提醒。" },
  { key: "experiment", label: "实验探究型", text: "本资源围绕实验探究，包含实验目的、步骤、现象记录与结论分析。" },
  { key: "exercise", label: "题型训练型", text: "本资源用于题型训练，包含分层题目、方法总结与答案解析。" }
];

const VOLUME_SEQUENCE = ["bx1", "bx2", "xbx1", "xbx2", "xbx3"];

function sortVolumes(a, b) {
  const idxA = VOLUME_SEQUENCE.indexOf(a.volume_code);
  const idxB = VOLUME_SEQUENCE.indexOf(b.volume_code);
  const orderA = idxA === -1 ? 999 : idxA;
  const orderB = idxB === -1 ? 999 : idxB;
  if (orderA !== orderB) {
    return orderA - orderB;
  }
  return (a.volume_order - b.volume_order) || a.volume_code.localeCompare(b.volume_code, "zh-CN");
}

export default function UploadWizard({
  token = "",
  volumes = [],
  chapters = [],
  sections = [],
  tags = [],
  difficulties = ["基础", "进阶", "挑战"],
  aiCapability = { loaded: false, enabled: false, auto_enrich: false },
  aiTagRuntime = "idle",
  isUploading = false,
  uploadProgress = 0,
  onSubmit,
  setGlobalMessage
}) {
  const fileInputRef = useRef(null);
  const [step, setStep] = useState(1);
  const [isDragActive, setIsDragActive] = useState(false);
  const [uploadFile, setUploadFile] = useState(null);
  const [pathPreview, setPathPreview] = useState("");
  const [isClassifying, setIsClassifying] = useState(false);
  const [isScopedClassifying, setIsScopedClassifying] = useState(false);
  const [autoResult, setAutoResult] = useState(null);
  const [scopedAutoResult, setScopedAutoResult] = useState(null);
  const [lastGoodResult, setLastGoodResult] = useState(null);
  const [displaySource, setDisplaySource] = useState("global");
  const [classifyError, setClassifyError] = useState("");
  const [autoFilledChapter, setAutoFilledChapter] = useState(false);
  const globalReqSeqRef = useRef(0);
  const scopedReqSeqRef = useRef(0);
  const lastGoodResultRef = useRef(null);
  const [form, setForm] = useState({
    chapter_id: "",
    volume_code: "",
    section_id: "",
    type: "document",
    difficulty: difficulties[0] || "基础",
    use_custom_title: false,
    custom_title: "",
    description: "",
    tags: []
  });

  const selectedChapter = useMemo(
    () => chapters.find((item) => String(item.id) === form.chapter_id) || null,
    [chapters, form.chapter_id]
  );
  const selectedSection = useMemo(
    () => sections.find((item) => String(item.id) === form.section_id) || null,
    [sections, form.section_id]
  );
  const chapterGroups = useMemo(() => {
    const rows = [];
    const seen = new Map();
    for (const chapter of chapters) {
      const key = chapter.volume_code || "unassigned";
      if (!seen.has(key)) {
        const group = {
          key,
          name: chapter.volume_name || "未分册",
          order: chapter.volume_order || 999,
          items: []
        };
        seen.set(key, group);
        rows.push(group);
      }
      seen.get(key).items.push(chapter);
    }
    rows.sort((a, b) => (a.order - b.order) || a.key.localeCompare(b.key, "zh-CN"));
    return rows;
  }, [chapters]);
  const volumeOptions = useMemo(() => {
    if (volumes.length) {
      return [...volumes].sort(sortVolumes);
    }
    return chapterGroups.map((group) => ({
      volume_code: group.key,
      volume_name: group.name,
      volume_order: group.order
    })).sort(sortVolumes);
  }, [volumes, chapterGroups]);
  const selectedVolume = useMemo(
    () => volumeOptions.find((item) => item.volume_code === form.volume_code) || null,
    [volumeOptions, form.volume_code]
  );
  const volumeChapters = useMemo(() => {
    if (!form.volume_code) {
      return [];
    }
    return chapters
      .filter((item) => item.volume_code === form.volume_code)
      .sort((a, b) => (a.chapter_order - b.chapter_order) || a.chapter_code.localeCompare(b.chapter_code, "zh-CN"));
  }, [chapters, form.volume_code]);
  const autoTitle = useMemo(
    () => buildAutoTitle({
      volumeCode: form.volume_code,
      chapter: selectedChapter,
      section: selectedSection,
      fileName: uploadFile?.name || ""
    }),
    [form.volume_code, selectedChapter, selectedSection, uploadFile]
  );
  const finalTitle = form.use_custom_title && form.custom_title.trim() ? form.custom_title.trim() : autoTitle;

  const guidedVolumeOptions = volumeOptions;
  const guidedChapterOptions = volumeChapters;
  const shouldUseScopedResult = Boolean(form.volume_code && uploadFile);
  const displayAutoResult = useMemo(() => {
    if (scopedAutoResult) {
      return scopedAutoResult;
    }
    if (autoResult) {
      return autoResult;
    }
    if (lastGoodResult) {
      return lastGoodResult;
    }
    return null;
  }, [autoResult, scopedAutoResult, lastGoodResult]);

  useEffect(() => {
    if (scopedAutoResult) {
      setDisplaySource("scoped");
      return;
    }
    if (autoResult) {
      setDisplaySource("global");
      return;
    }
    if (lastGoodResult) {
      setDisplaySource("fallback");
      return;
    }
    setDisplaySource("global");
  }, [autoResult, scopedAutoResult, lastGoodResult]);

  const displaySourceText = useMemo(() => {
    if (displaySource === "scoped") {
      return "按已选册";
    }
    if (displaySource === "fallback") {
      return "兜底";
    }
    return "全局";
  }, [displaySource]);

  const aiTagStatus = useMemo(() => {
    if (!aiCapability?.loaded) {
      return { code: "processing", text: "AI 打标中", hint: "正在获取AI能力配置..." };
    }
    if (!aiCapability.enabled || !aiCapability.auto_enrich || aiTagRuntime === "unavailable") {
      return { code: "unavailable", text: "AI 暂不可用", hint: "未配置本地AI或自动打标未开启，仍可手动选择标签。" };
    }
    if (aiTagRuntime === "done") {
      return { code: "done", text: "AI 已生成", hint: "最近一次上传已返回AI标签，可继续人工补充。" };
    }
    if (aiTagRuntime === "processing" || isUploading) {
      return { code: "processing", text: "AI 打标中", hint: "上传后后台静默生成 AI 标签与总结。" };
    }
    return { code: "processing", text: "AI 打标中", hint: "上传后将自动生成 AI 标签，你可先手动勾选标签。" };
  }, [aiCapability, aiTagRuntime, isUploading]);

  useEffect(() => {
    lastGoodResultRef.current = lastGoodResult;
  }, [lastGoodResult]);

  useEffect(() => {
    async function loadPathPreview() {
      if (!token || !uploadFile?.name) {
        setPathPreview("");
        return;
      }
      try {
        const data = await getUploadPathPreview({
          token,
          filename: uploadFile.name,
          chapterId: form.chapter_id,
          sectionId: form.section_id,
          volumeCode: form.volume_code,
          lowConfidence: Boolean((scopedAutoResult || autoResult)?.is_low_confidence && !form.chapter_id)
        });
        setPathPreview(data?.object_key || "");
      } catch {
        const volumePart = form.volume_code || selectedChapter?.volume_code;
        const chapterPart = selectedChapter?.chapter_code;
        const sectionPart = selectedSection?.code;
        const suffix = uploadFile.name.includes(".") ? uploadFile.name.slice(uploadFile.name.lastIndexOf(".")) : "";
        if (volumePart && chapterPart && sectionPart) {
          setPathPreview(`resources/${volumePart}/${chapterPart}/${sectionPart}/<clean-name>${suffix}`);
        } else if (volumePart && sectionPart) {
          setPathPreview(`resources/${volumePart}/unassigned/${sectionPart}/<clean-name>${suffix}`);
        } else {
          setPathPreview(`resources/unassigned/<clean-name>${suffix}`);
        }
      }
    }

    loadPathPreview();
  }, [token, uploadFile, form.chapter_id, form.section_id, form.volume_code, autoResult, scopedAutoResult, selectedChapter, selectedSection]);

  function resetWizard() {
    setStep(1);
    setUploadFile(null);
    setPathPreview("");
    setAutoResult(null);
    setScopedAutoResult(null);
    setLastGoodResult(null);
    setDisplaySource("global");
    setClassifyError("");
    setAutoFilledChapter(false);
    setIsScopedClassifying(false);
    setForm({
      chapter_id: "",
      volume_code: "",
      section_id: "",
      type: "document",
      difficulty: difficulties[0] || "基础",
      use_custom_title: false,
      custom_title: "",
      description: "",
      tags: []
    });
  }

  async function runAutoClassify(file) {
    if (!token || !file) {
      setAutoResult(null);
      setScopedAutoResult(null);
      setLastGoodResult(null);
      setDisplaySource("global");
      setClassifyError("");
      return;
    }
    globalReqSeqRef.current += 1;
    const requestId = globalReqSeqRef.current;
    setIsClassifying(true);
    setClassifyError("");
    try {
      const data = await autoClassifyResource({
        token,
        file,
        subject: "物理",
        stage: "senior"
      });
      if (requestId !== globalReqSeqRef.current) {
        return;
      }
      setAutoResult(data || null);
      setScopedAutoResult(null);
      if (data) {
        setLastGoodResult(data);
      }
      setForm((prev) => ({
        ...prev,
        chapter_id: "",
        volume_code: "",
        section_id: ""
      }));
      setAutoFilledChapter(false);
      setIsScopedClassifying(false);
      setDisplaySource(data ? "global" : "fallback");
      if (!data) {
        setClassifyError(lastGoodResultRef.current ? "全局判章无结果，已展示最近一次有效推荐" : "本次判章未返回有效结果，请重试");
      }
    } catch (error) {
      if (requestId !== globalReqSeqRef.current) {
        return;
      }
      setAutoResult(null);
      setScopedAutoResult(null);
      setAutoFilledChapter(false);
      setIsScopedClassifying(false);
      setDisplaySource(lastGoodResultRef.current ? "fallback" : "global");
      setClassifyError(lastGoodResultRef.current ? "全局判章失败，已展示最近一次有效推荐" : (error?.message || "全局判章失败，请重试"));
    } finally {
      if (requestId === globalReqSeqRef.current) {
        setIsClassifying(false);
      }
    }
  }

  useEffect(() => {
    async function runScopedClassify() {
      if (!token || !uploadFile || !form.volume_code) {
        setScopedAutoResult(null);
        setIsScopedClassifying(false);
        return;
      }
      scopedReqSeqRef.current += 1;
      const requestId = scopedReqSeqRef.current;
      setIsScopedClassifying(true);
      setClassifyError("");
      try {
        const data = await autoClassifyResource({
          token,
          file: uploadFile,
          subject: "物理",
          stage: "senior",
          volumeCode: form.volume_code,
          selectedVolumeCode: form.volume_code
        });
        if (requestId !== scopedReqSeqRef.current) {
          return;
        }
        setScopedAutoResult(data || null);
        if (data) {
          setLastGoodResult(data);
        }
        setDisplaySource(data ? "scoped" : (lastGoodResultRef.current ? "fallback" : "global"));
        if (!data) {
          setClassifyError(lastGoodResultRef.current ? "册内重算无结果，已展示最近一次有效推荐" : "册内重算未返回有效结果，请重试");
        }
        if (data?.recommended_chapter_id) {
          setForm((prev) => {
            if (prev.chapter_id) {
              return prev;
            }
            return {
              ...prev,
              chapter_id: String(data.recommended_chapter_id),
              section_id: ""
            };
          });
          setAutoFilledChapter(true);
        }
      } catch {
        if (requestId !== scopedReqSeqRef.current) {
          return;
        }
        setScopedAutoResult(null);
        setDisplaySource(lastGoodResultRef.current ? "fallback" : "global");
        setClassifyError("册内重算失败，已展示最近一次有效推荐");
      } finally {
        if (requestId === scopedReqSeqRef.current) {
          setIsScopedClassifying(false);
        }
      }
    }
    runScopedClassify();
  }, [token, uploadFile, form.volume_code]);

  function onFileSelect(file) {
    if (!file) {
      return;
    }
    setClassifyError("");
    setUploadFile(file);
    setAutoResult(null);
    setScopedAutoResult(null);
    setLastGoodResult(null);
    setDisplaySource("global");
    setForm((prev) => ({
      ...prev,
      volume_code: "",
      chapter_id: "",
      section_id: ""
    }));
    setAutoFilledChapter(false);
    runAutoClassify(file);
  }

  function handleNext() {
    if (step === 1) {
      if (!uploadFile) {
        setGlobalMessage("请先选择上传文件");
        return;
      }
      if (!form.volume_code) {
        setGlobalMessage("请先选择册");
        return;
      }
      if (!form.chapter_id) {
        setGlobalMessage("请先选择章节");
        return;
      }
      if (!form.section_id) {
        setGlobalMessage("请先选择板块（第3问）");
        return;
      }
    }
    if (step === 2) {
      if (!form.section_id) return;
    }
    setStep((prev) => Math.min(3, prev + 1));
  }

  function handlePrev() {
    setStep((prev) => Math.max(1, prev - 1));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!uploadFile) {
      setGlobalMessage("请先选择上传文件");
      return;
    }
    if (!form.section_id) {
      setGlobalMessage("请先选择板块");
      return;
    }

    const ok = await onSubmit({
      title: finalTitle,
      type: form.type,
      description: form.description,
      subject: "物理",
      grade: selectedChapter?.grade || "",
      tags: form.tags.join(","),
      section_id: form.section_id,
      resource_kind: selectedSection?.code || "tutorial",
      difficulty: form.difficulty,
      chapter_id: form.chapter_id || "",
      volume_code: form.volume_code || selectedChapter?.volume_code || "",
      file: uploadFile
    });

    if (ok) {
      resetWizard();
    }
  }

  return (
    <section className="card">
      <h2>上传资源（向导）</h2>
      <div className="wizard-steps">
        <span className={step >= 1 ? "active" : ""}>1. 选择文件</span>
        <span className={step >= 2 ? "active" : ""}>2. 选择信息</span>
        <span className={step >= 3 ? "active" : ""}>3. 确认提交</span>
      </div>

      <form className="wizard-form" onSubmit={handleSubmit}>
        {step === 1 && (
          <>
            <div
              className={`upload-dropzone ${isDragActive ? "active" : ""}`}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDragActive(true);
              }}
              onDragLeave={(event) => {
                event.preventDefault();
                setIsDragActive(false);
              }}
              onDrop={(event) => {
                event.preventDefault();
                setIsDragActive(false);
                onFileSelect(event.dataTransfer?.files?.[0] || null);
              }}
              onClick={() => fileInputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
            >
              <input
                ref={fileInputRef}
                className="hidden-file-input"
                type="file"
                onChange={(event) => onFileSelect(event.target.files?.[0] || null)}
              />
              <strong>拖拽文件到此区域上传</strong>
              <span>或点击选择文件（支持文档/PDF/视频/图片/音频/Office）</span>
              {uploadFile ? (
                <span className="upload-file-picked">已选择：{uploadFile.name}</span>
              ) : (
                <span className="upload-file-picked muted">当前未选择文件</span>
              )}
            </div>
            {isClassifying ? (
              <p className="hint">AI 正在判章中...</p>
            ) : null}
            {shouldUseScopedResult && isScopedClassifying ? (
              <p className="hint">已按你选择的册重算章节中...</p>
            ) : null}
            {classifyError ? (
              <p className="hint">{classifyError}</p>
            ) : null}
            {displayAutoResult ? (
              <div className={`auto-classify-card ${displayAutoResult.is_low_confidence ? "low" : ""}`}>
                <strong>
                  AI 推荐候选（{displaySourceText}，请确认）
                </strong>
                <p className="hint">
                  置信度：{formatPercent(displayAutoResult.confidence)}
                  {" · "}
                  级别：{displayAutoResult.confidence_level || "low"}
                  {" · "}
                  {displayAutoResult.reason}
                </p>
                {displayAutoResult.rule_hits?.length ? (
                  <div className="rule-hit-list">
                    <div className="hint">规则命中：</div>
                    {displayAutoResult.rule_hits.map((item) => (
                      <span key={item} className="rule-hit-item">{item}</span>
                    ))}
                  </div>
                ) : null}
                {displayAutoResult.candidates?.length ? (
                  <div className="chip-group">
                    {displayAutoResult.candidates.map((item) => (
                      <button
                        key={item.chapter_id}
                        type="button"
                        className="chip"
                        onClick={() => {
                          setAutoFilledChapter(false);
                          setForm((prev) => ({
                            ...prev,
                            volume_code: item.volume_code || prev.volume_code,
                            chapter_id: String(item.chapter_id),
                            section_id: ""
                          }));
                        }}
                      >
                        {item.title}（{formatPercent(item.probability ?? item.score ?? 0)}）
                        {item.reasons?.length ? ` · ${item.reasons[0]}` : ""}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : (!isClassifying && !isScopedClassifying && uploadFile) ? (
              <p className="hint">暂未收到判章结果，请重试或重新选择文件。</p>
            ) : null}

            <div className="ai-archive-guide">
              <strong>AI 归档三步（选择题）</strong>
              <div className="hint">高中物理资源归档严格按人教版2019目录执行，必须选择“册/章/节”。</div>
              <div className="ai-guide-step">
                <div className="hint">第1问：请选择册</div>
                <div className="chip-group">
                  {guidedVolumeOptions.map((item) => (
                    <button
                      key={item.volume_code}
                      type="button"
                      className={`chip ${form.volume_code === item.volume_code ? "active" : ""}`}
                      onClick={() => {
                        setAutoFilledChapter(false);
                        setForm((prev) => ({
                          ...prev,
                          volume_code: item.volume_code,
                          chapter_id: "",
                          section_id: ""
                        }));
                      }}
                    >
                      {item.volume_name}
                    </button>
                  ))}
                </div>
              </div>

              {form.volume_code ? (
                <div className="ai-guide-step">
                  <div className="hint">第2问：请选择章</div>
                  <div className="chip-group">
                    {guidedChapterOptions.map((chapter) => (
                      <button
                        key={chapter.id}
                        type="button"
                        className={`chip ${String(chapter.id) === form.chapter_id ? "active" : ""}`}
                        onClick={() => {
                          setAutoFilledChapter(false);
                          setForm((prev) => ({
                            ...prev,
                            chapter_id: String(chapter.id),
                            section_id: ""
                          }));
                        }}
                      >
                        {chapter.chapter_code} {chapter.title}
                      </button>
                    ))}
                  </div>
                  {autoFilledChapter && form.chapter_id ? (
                    <div className="hint">AI已填入推荐章节，你可以手动改。</div>
                  ) : null}
                </div>
              ) : null}

              {form.chapter_id ? (
                <div className="ai-guide-step">
                  <div className="hint">第3问：请选择节（板块）</div>
                  <div className="chip-group">
                    {sections.map((section) => (
                      <button
                        key={section.id}
                        type="button"
                        className={`chip ${String(section.id) === form.section_id ? "active" : ""}`}
                        onClick={() => setForm((prev) => ({
                          ...prev,
                          section_id: String(section.id)
                        }))}
                      >
                        {section.name}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              <div className="hint">
                当前选择：
                {" 册 "}
                {selectedChapter?.volume_name || selectedVolume?.volume_name || "未选"}
                {" / 章 "}
                {selectedChapter ? `${selectedChapter.chapter_code} ${selectedChapter.title}` : "未选"}
                {" / 节 "}
                {selectedSection?.name || "未选"}
              </div>
            </div>
          </>
        )}

        {step === 2 && (
          <div className="wizard-grid">
            <div className={`ai-status-card ${aiTagStatus.code}`}>
              <strong>AI 标签状态：{aiTagStatus.text}</strong>
              <p className="hint">{aiTagStatus.hint}</p>
            </div>
            <label>
              资源类型
              <select
                value={form.type}
                onChange={(event) => setForm({ ...form, type: event.target.value })}
              >
                <option value="document">文档</option>
                <option value="ppt">课件</option>
                <option value="video">视频</option>
                <option value="image">图片</option>
                <option value="audio">音频</option>
                <option value="exercise">习题</option>
              </select>
            </label>

            <label>
              难度
              <select
                value={form.difficulty}
                onChange={(event) => setForm({ ...form, difficulty: event.target.value })}
              >
                {difficulties.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>

            <div className="hint">
              学段：高中（固定） / 学科：物理（固定） / 册：{selectedChapter?.volume_name || selectedVolume?.volume_name || "未识别"}
              {" / "}
              年级：{selectedChapter?.grade || "未选择章节"}
              {" / "}
              板块：{selectedSection?.name || "未选择"}
            </div>

            <div>
              <div className="hint">标签（多选）</div>
              <TagPicker
                tagOptions={tags}
                selectedTags={form.tags}
                onChange={(next) => setForm({ ...form, tags: next })}
                allowCustom
              />
            </div>

            <div>
              <div className="hint">描述模板（可选）</div>
              <div className="chip-group">
                {DESCRIPTION_TEMPLATES.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className="chip"
                    onClick={() => setForm({ ...form, description: item.text })}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <textarea
                placeholder="资源描述（可选）"
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="wizard-preview">
            <p><strong>文件：</strong>{uploadFile?.name || "-"}</p>
            <p><strong>册：</strong>{selectedChapter?.volume_name || selectedVolume?.volume_name || "-"}</p>
            <p><strong>章节：</strong>{selectedChapter ? `${selectedChapter.chapter_code} ${selectedChapter.title}` : "未选择"}</p>
            <p><strong>板块：</strong>{selectedSection?.name || "-"}</p>
            <p><strong>预计存储路径：</strong>{pathPreview || "resources/unassigned/<uuid>"}</p>
            <p><strong>类型：</strong>{typeLabel(form.type)}</p>
            <p><strong>难度：</strong>{form.difficulty}</p>
            <p><strong>标签：</strong>{form.tags.length ? form.tags.join("、") : "未选择"}</p>

            <label className="inline-check">
              <input
                type="checkbox"
                checked={form.use_custom_title}
                onChange={(event) => setForm({ ...form, use_custom_title: event.target.checked })}
              />
              手动编辑标题
            </label>
            {form.use_custom_title ? (
              <input
                type="text"
                value={form.custom_title}
                onChange={(event) => setForm({ ...form, custom_title: event.target.value })}
                placeholder="自定义标题"
              />
            ) : null}
            <p><strong>标题：</strong>{finalTitle}</p>
          </div>
        )}

        {(isUploading || uploadProgress > 0) && (
          <div className="upload-progress-wrap">
            <div className="upload-progress-label">上传进度：{uploadProgress}%</div>
            <div className="upload-progress-track">
              <div className="upload-progress-fill" style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        )}

        <div className="action-buttons">
          {step > 1 ? (
            <button type="button" className="ghost" onClick={handlePrev} disabled={isUploading}>上一步</button>
          ) : null}
          {step < 3 ? (
            <button type="button" onClick={handleNext} disabled={isUploading}>下一步</button>
          ) : (
            <button type="submit" disabled={isUploading}>{isUploading ? "上传中..." : "提交审核"}</button>
          )}
        </div>
      </form>
    </section>
  );
}
