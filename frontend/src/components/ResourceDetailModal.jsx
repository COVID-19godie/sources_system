import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import OnlyOfficeViewer from "./OnlyOfficeViewer";
import { apiRequest, formatTime, getResourceAccessUrls, getResourceOfficeConfig, makeApiUrl } from "../lib/api";

function isOfficeMode(mode) {
  return ["word", "excel", "ppt"].includes(mode || "");
}

export default function ResourceDetailModal({ item, onClose, token, role, onDeleted, showDelete = true }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [officeConfig, setOfficeConfig] = useState(null);
  const [officeLoading, setOfficeLoading] = useState(false);
  const [officeError, setOfficeError] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [actionBusy, setActionBusy] = useState("");

  useEffect(() => {
    async function fetchPreview() {
      if (!item) {
        setPreview(null);
        setOfficeConfig(null);
        setOfficeError("");
        return;
      }
      setLoading(true);
      setOfficeConfig(null);
      setOfficeError("");
      try {
        const data = await apiRequest(`/api/resources/${item.id}/preview`, { token });
        setPreview(data);
      } catch {
        setPreview(null);
      } finally {
        setLoading(false);
      }
    }

    fetchPreview();
  }, [item, token]);

  useEffect(() => {
    async function fetchOfficeConfig() {
      if (!item || !preview || !token || !isOfficeMode(preview.mode)) {
        setOfficeConfig(null);
        return;
      }
      setOfficeLoading(true);
      setOfficeError("");
      try {
        const data = await getResourceOfficeConfig(item.id, token);
        setOfficeConfig(data || null);
      } catch {
        setOfficeConfig(null);
      } finally {
        setOfficeLoading(false);
      }
    }

    fetchOfficeConfig();
  }, [item, preview, token]);

  const fallbackUrl =
    preview?.download_url ||
    preview?.open_url ||
    preview?.url ||
    item?.download_url ||
    (item?.file_path ? makeApiUrl(item.file_path) : "");

  const previewNode = useMemo(() => {
    if (!item) {
      return null;
    }
    if (loading) {
      return <p className="hint">预览加载中...</p>;
    }

    const previewUrl = preview?.url || preview?.open_url || fallbackUrl;

    if (preview?.mode === "pdf" && previewUrl) {
      return <iframe title="pdf-preview" className="preview-frame" src={previewUrl} />;
    }

    if (preview?.mode === "video" && previewUrl) {
      return (
        <video className="preview-video" src={previewUrl} controls preload="metadata">
          您的浏览器不支持视频预览。
        </video>
      );
    }

    if (preview?.mode === "image" && previewUrl) {
      return (
        <img
          className="preview-image"
          src={previewUrl}
          alt={item?.title || "image-preview"}
          loading="lazy"
        />
      );
    }

    if (preview?.mode === "audio" && previewUrl) {
      return (
        <audio className="preview-audio" src={previewUrl} controls preload="metadata">
          您的浏览器不支持音频预览。
        </audio>
      );
    }

    if (preview?.mode === "markdown" && preview?.content) {
      const html = DOMPurify.sanitize(marked.parse(preview.content));
      return <div className="preview-rich" dangerouslySetInnerHTML={{ __html: html }} />;
    }

    if (preview?.mode === "html") {
      if (preview?.content) {
        return (
          <iframe
            title="html-preview"
            className="preview-frame"
            srcDoc={preview.content}
            sandbox="allow-scripts allow-forms allow-popups allow-downloads"
          />
        );
      }
      const browserUrl = preview?.open_url || preview?.url || "";
      if (browserUrl) {
        return (
          <iframe
            title="html-preview"
            className="preview-frame"
            src={browserUrl}
            sandbox="allow-scripts allow-forms allow-popups allow-downloads"
          />
        );
      }
    }

    if (isOfficeMode(preview?.mode)) {
      if (officeLoading) {
        return <p className="hint">Office 预览加载中...</p>;
      }
      if (officeConfig) {
        return (
          <OnlyOfficeViewer
            officeConfig={officeConfig}
            height={460}
            onError={(message) => setOfficeError(message || "OnlyOffice 预览加载失败")}
          />
        );
      }
      if (officeError) {
        return <p className="hint">{officeError}</p>;
      }
    }

    if (["word", "excel", "ppt"].includes(preview?.mode) && preview?.content) {
      const html = DOMPurify.sanitize(marked.parse(preview.content));
      return <div className="preview-rich" dangerouslySetInnerHTML={{ __html: html }} />;
    }

    if (previewUrl) {
      return <p className="hint">该资源暂不支持内嵌预览，请使用下方打开/下载按钮。</p>;
    }

    return <p className="hint">该资源暂无预览内容</p>;
  }, [fallbackUrl, item, loading, officeConfig, officeError, officeLoading, preview]);

  if (!item) {
    return null;
  }

  const canDelete = Boolean(showDelete && role === "admin" && token);
  const hasAttachment = Boolean(item?.object_key || item?.file_path || fallbackUrl);

  function openViewerPage() {
    if (!item?.id) {
      return;
    }
    window.location.assign(`/viewer/resource/${item.id}`);
  }

  async function handleDownload() {
    if (!item?.id || !token || actionBusy) {
      return;
    }
    setActionBusy("download");
    try {
      const data = await getResourceAccessUrls(item.id, token);
      const targetUrl = data?.download_url || data?.open_url || fallbackUrl;
      if (!targetUrl) {
        window.alert("该资源暂无附件");
        return;
      }
      window.location.assign(targetUrl);
    } catch (error) {
      window.alert(error?.message || "获取资源地址失败");
    } finally {
      setActionBusy("");
    }
  }

  async function handleDelete() {
    if (!item?.id || !canDelete || deleting) {
      return;
    }
    const ok = window.confirm(`确认将资源「${item.title}」移入回收站吗？`);
    if (!ok) {
      return;
    }
    try {
      setDeleting(true);
      await apiRequest(`/api/resources/${item.id}`, {
        method: "DELETE",
        token
      });
      if (typeof onDeleted === "function") {
        onDeleted(item);
      }
      onClose();
    } catch (error) {
      window.alert(error?.message || "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal-panel modal-large" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h3>{item.title}</h3>
          <button type="button" className="ghost" onClick={onClose}>关闭</button>
        </div>
        <p className="modal-desc">{item.description || "暂无描述"}</p>
        <div className="modal-grid">
          <span>类型：{item.type}</span>
          <span>资源板块：{item.section?.name || item.resource_kind || "未分区"}</span>
          <span>学科：{item.subject || "-"}</span>
          <span>年级：{item.grade || "-"}</span>
          <span>格式：{item.file_format || "other"}</span>
          <span>难度：{item.difficulty || "-"}</span>
          <span>标签：{item.tags?.length ? item.tags.join("、") : "-"}</span>
          <span>AI标签：{item.ai_tags?.length ? item.ai_tags.join("、") : "-"}</span>
          <span>更新时间：{formatTime(item.updated_at)}</span>
        </div>
        {isOfficeMode(preview?.mode) ? (
          <p className="hint">Office 预览模式：{role === "admin" ? "管理员可编辑（自动保存）" : "只读"}</p>
        ) : null}
        {item.ai_summary ? <p className="modal-desc"><strong>AI总结：</strong>{item.ai_summary}</p> : null}

        <div className="preview-box">{previewNode}</div>

        <div className="modal-actions action-buttons">
          {hasAttachment ? (
            <>
              <button type="button" onClick={openViewerPage} disabled={actionBusy !== ""}>
                在浏览器中打开
              </button>
              <button type="button" className="ghost" onClick={handleDownload} disabled={actionBusy !== ""}>
                {actionBusy === "download" ? "处理中..." : "下载"}
              </button>
            </>
          ) : (
            <span className="hint">该资源暂无附件</span>
          )}
          {canDelete ? (
            <button type="button" className="danger" onClick={handleDelete} disabled={deleting}>
              {deleting ? "处理中..." : "删除到回收站"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
