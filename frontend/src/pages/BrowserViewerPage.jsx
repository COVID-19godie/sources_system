import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import DOMPurify from "dompurify";
import { marked } from "marked";
import OnlyOfficeViewer from "../components/OnlyOfficeViewer";
import {
  apiRequest,
  getResourceAccessUrls,
  getResourceOfficeConfig,
  getStorageAccessUrls,
  getStorageOfficeConfig
} from "../lib/api";

function isOfficeMode(mode) {
  return ["word", "excel", "ppt"].includes(mode || "");
}

export default function BrowserViewerPage({ token, setGlobalMessage }) {
  const navigate = useNavigate();
  const params = useParams();
  const [searchParams] = useSearchParams();
  const [preview, setPreview] = useState(null);
  const [officeConfig, setOfficeConfig] = useState(null);
  const [officeLoading, setOfficeLoading] = useState(false);
  const [officeError, setOfficeError] = useState("");
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);

  const resourceId = params.resourceId ? Number(params.resourceId) : null;
  const storageKey = searchParams.get("key") || "";
  const sourceType = resourceId ? "resource" : "storage";

  const title = useMemo(() => {
    if (resourceId) {
      return `资源预览 #${resourceId}`;
    }
    if (storageKey) {
      const parts = storageKey.split("/");
      return `文件预览：${parts[parts.length - 1]}`;
    }
    return "文件预览";
  }, [resourceId, storageKey]);

  useEffect(() => {
    async function loadPreview() {
      if (!token) {
        return;
      }
      if (!resourceId && !storageKey) {
        setGlobalMessage("缺少预览目标");
        return;
      }

      setLoading(true);
      setOfficeConfig(null);
      setOfficeError("");
      try {
        const data = resourceId
          ? await apiRequest(`/api/resources/${resourceId}/preview`, { token })
          : await apiRequest(`/api/storage/preview?${new URLSearchParams({ key: storageKey }).toString()}`, { token });
        setPreview(data || null);
      } catch (error) {
        setPreview(null);
        setGlobalMessage(error.message);
      } finally {
        setLoading(false);
      }
    }

    loadPreview();
  }, [resourceId, storageKey, token, setGlobalMessage]);

  useEffect(() => {
    async function loadOfficeConfig() {
      if (!token || !preview || !isOfficeMode(preview.mode)) {
        setOfficeConfig(null);
        return;
      }
      setOfficeLoading(true);
      setOfficeError("");
      try {
        const data = resourceId
          ? await getResourceOfficeConfig(resourceId, token)
          : await getStorageOfficeConfig(storageKey, token);
        setOfficeConfig(data || null);
      } catch (error) {
        setOfficeConfig(null);
        setOfficeError(error?.message || "Office 预览不可用");
      } finally {
        setOfficeLoading(false);
      }
    }

    loadOfficeConfig();
  }, [preview, resourceId, storageKey, token]);

  async function handleDownload() {
    if (!token || downloading) {
      return;
    }
    setDownloading(true);
    try {
      const data = resourceId
        ? await getResourceAccessUrls(resourceId, token)
        : await getStorageAccessUrls(storageKey, token);
      const url = data?.download_url || data?.open_url || "";
      if (!url) {
        setGlobalMessage("未找到下载地址");
        return;
      }
      window.location.assign(url);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setDownloading(false);
    }
  }

  const previewNode = useMemo(() => {
    if (loading) {
      return <p className="hint">预览加载中...</p>;
    }
    if (!preview) {
      return <p className="hint">暂无可预览内容</p>;
    }

    const previewUrl = preview?.open_url || preview?.url || "";

    if (preview.mode === "pdf" && previewUrl) {
      return <iframe title="viewer-pdf" className="preview-frame" src={previewUrl} />;
    }
    if (preview.mode === "video" && previewUrl) {
      return (
        <video className="preview-video" src={previewUrl} controls preload="metadata">
          您的浏览器不支持视频预览。
        </video>
      );
    }
    if (preview.mode === "image" && previewUrl) {
      return <img className="preview-image" src={previewUrl} alt={title} loading="lazy" />;
    }
    if (preview.mode === "audio" && previewUrl) {
      return (
        <audio className="preview-audio" src={previewUrl} controls preload="metadata">
          您的浏览器不支持音频预览。
        </audio>
      );
    }
    if (preview.mode === "markdown" && preview.content) {
      const html = DOMPurify.sanitize(marked.parse(preview.content));
      return <div className="preview-rich" dangerouslySetInnerHTML={{ __html: html }} />;
    }
    if (preview.mode === "html") {
      if (preview.content) {
        return (
          <iframe
            title="viewer-html"
            className="preview-frame"
            srcDoc={preview.content}
            sandbox="allow-scripts allow-forms allow-popups allow-downloads"
          />
        );
      }
      if (previewUrl) {
        return (
          <iframe
            title="viewer-html"
            className="preview-frame"
            src={previewUrl}
            sandbox="allow-scripts allow-forms allow-popups allow-downloads"
          />
        );
      }
    }
    if (isOfficeMode(preview.mode)) {
      if (officeLoading) {
        return <p className="hint">Office 预览加载中...</p>;
      }
      if (officeConfig) {
        return <OnlyOfficeViewer officeConfig={officeConfig} height={680} onError={setOfficeError} />;
      }
      if (officeError) {
        return <p className="hint">{officeError}</p>;
      }
    }
    if (["word", "excel", "ppt"].includes(preview.mode) && preview.content) {
      const html = DOMPurify.sanitize(marked.parse(preview.content));
      return <div className="preview-rich" dangerouslySetInnerHTML={{ __html: html }} />;
    }
    if (previewUrl) {
      return (
        <p className="hint">
          当前文件无法内嵌渲染，请使用“下载”按钮获取本地文件。
        </p>
      );
    }
    return <p className="hint">该文件暂不支持预览</p>;
  }, [loading, officeConfig, officeError, officeLoading, preview, title]);

  if (!token) {
    return (
      <section className="card">
        <h2>文件预览</h2>
        <p className="hint">请先登录后再打开预览页。</p>
        <button type="button" className="ghost" onClick={() => navigate("/discover")}>返回发现页</button>
      </section>
    );
  }

  return (
    <section className="card viewer-page">
      <div className="viewer-header">
        <div>
          <h2>{title}</h2>
          <p className="hint">
            预览模式：{preview?.mode || "-"}（{sourceType === "resource" ? "资源页" : "存储页"}）
          </p>
        </div>
        <div className="action-buttons">
          <button type="button" className="ghost" onClick={() => navigate(-1)}>返回</button>
          <button type="button" onClick={handleDownload} disabled={downloading}>
            {downloading ? "处理中..." : "下载到本地"}
          </button>
        </div>
      </div>
      <div className="preview-box viewer-preview-box">{previewNode}</div>
    </section>
  );
}
