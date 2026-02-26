import { useEffect, useMemo, useRef, useState } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import OnlyOfficeViewer from "../components/OnlyOfficeViewer";
import {
  createStorageFolder,
  deleteStorageObject,
  formatTime,
  getStorageAccessUrls,
  getStorageOfficeConfig,
  listStorage,
  previewStorageObject,
  notifyResourcesChanged,
  uploadStorageWithProgress
} from "../lib/api";

function formatBytes(size) {
  if (typeof size !== "number" || Number.isNaN(size)) {
    return "-";
  }
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  if (size < 1024 * 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function itemLabel(item) {
  if (item?.is_dir) {
    return "文件夹";
  }
  if (!item?.name) {
    return "文件";
  }
  const suffix = item.name.includes(".") ? item.name.split(".").pop().toUpperCase() : "";
  return suffix ? `${suffix} 文件` : "文件";
}

function isOfficeMode(mode) {
  return ["word", "excel", "ppt"].includes(mode || "");
}

export default function StoragePage({ token, role, onLogin, setGlobalMessage }) {
  const isAdmin = role === "admin";
  const fileInputRef = useRef(null);
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [prefix, setPrefix] = useState("");
  const [parentPrefix, setParentPrefix] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [officeConfig, setOfficeConfig] = useState(null);
  const [officeLoading, setOfficeLoading] = useState(false);
  const [officeError, setOfficeError] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [folderModal, setFolderModal] = useState({ open: false, name: "" });
  const [actionBusy, setActionBusy] = useState("");
  const [dragActive, setDragActive] = useState(false);

  const breadcrumbs = useMemo(() => {
    const crumbs = [{ label: "根目录", value: "" }];
    const segments = prefix.split("/").filter(Boolean);
    let acc = "";
    for (const segment of segments) {
      acc += `${segment}/`;
      crumbs.push({ label: segment, value: acc });
    }
    return crumbs;
  }, [prefix]);

  async function loadList(targetPrefix = prefix, keepSelectionKey = "") {
    if (!token) {
      setItems([]);
      setParentPrefix(null);
      setSelectedItem(null);
      setPreview(null);
      setOfficeConfig(null);
      setOfficeError("");
      return;
    }

    setLoading(true);
    try {
      const data = await listStorage({ token, prefix: targetPrefix });
      setPrefix(data?.prefix || "");
      setParentPrefix(data?.parent_prefix ?? null);
      const rows = data?.items || [];
      setItems(rows);

      const matched = rows.find((row) => row.key === keepSelectionKey) || null;
      setSelectedItem(matched);
      if (!matched) {
        setPreview(null);
        setOfficeConfig(null);
        setOfficeError("");
      }
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadList(prefix);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role]);

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

  async function loadPreview(item) {
    if (!item || item.is_dir) {
      setPreview(null);
      setOfficeConfig(null);
      setOfficeLoading(false);
      setOfficeError("");
      return;
    }
    setPreviewLoading(true);
    setOfficeConfig(null);
    setOfficeError("");
    try {
      const data = await previewStorageObject(item.key, token);
      setPreview({ ...data, name: item.name });
      if (isOfficeMode(data?.mode)) {
        setOfficeLoading(true);
        try {
          const office = await getStorageOfficeConfig(item.key, token);
          setOfficeConfig(office || null);
        } catch {
          setOfficeConfig(null);
        } finally {
          setOfficeLoading(false);
        }
      } else {
        setOfficeConfig(null);
        setOfficeLoading(false);
      }
    } catch (error) {
      setPreview(null);
      setOfficeConfig(null);
      setOfficeLoading(false);
      setGlobalMessage(error.message);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function openStorageLink(item, intent) {
    if (!item || item.is_dir || actionBusy) {
      return;
    }
    if (intent === "open") {
      window.location.assign(`/viewer/storage?${new URLSearchParams({ key: item.key }).toString()}`);
      return;
    }

    setActionBusy(intent);
    try {
      const data = await getStorageAccessUrls(item.key, token);
      const targetUrl =
        intent === "download"
          ? (data?.download_url || data?.open_url || "")
          : (data?.open_url || data?.download_url || "");
      if (!targetUrl) {
        setGlobalMessage("该文件暂无可用地址");
        return;
      }
      window.location.assign(targetUrl);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setActionBusy("");
    }
  }

  async function onItemDoubleClick(item) {
    if (item.is_dir) {
      await loadList(item.key);
      return;
    }
    await loadPreview(item);
  }

  async function uploadFiles(fileList) {
    if (!isAdmin) {
      setGlobalMessage("当前账号为只读模式，无法上传文件");
      return;
    }
    const files = Array.from(fileList || []);
    if (!files.length) {
      return;
    }

    for (const file of files) {
      try {
        setUploadProgress(0);
        await uploadStorageWithProgress({
          token,
          prefix,
          file,
          onProgress: (progress) => setUploadProgress(progress)
        });
        setUploadProgress(100);
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }
    setTimeout(() => setUploadProgress(0), 500);
    await loadList(prefix);
    setGlobalMessage(`上传完成，共 ${files.length} 个文件`);
  }

  async function handleMenuAction(action, fromItem = null) {
    const item = fromItem || selectedItem;

    if (action === "refresh") {
      await loadList(prefix, selectedItem?.key || "");
      return;
    }

    if (action === "new-folder") {
      if (!isAdmin) {
        setGlobalMessage("当前账号为只读模式，无法新建文件夹");
        return;
      }
      setFolderModal({ open: true, name: "" });
      return;
    }

    if (action === "upload") {
      if (!isAdmin) {
        setGlobalMessage("当前账号为只读模式，无法上传文件");
        return;
      }
      fileInputRef.current?.click();
      return;
    }

    if (!item) {
      return;
    }

    if (action === "open") {
      if (item.is_dir) {
        await loadList(item.key);
      } else {
        await openStorageLink(item, "open");
      }
      return;
    }

    if (action === "preview") {
      if (item.is_dir) {
        setGlobalMessage("文件夹不支持预览");
        return;
      }
      await loadPreview(item);
      return;
    }

    if (action === "download") {
      if (item.is_dir) {
        setGlobalMessage("文件夹不支持下载链接");
        return;
      }
      await openStorageLink(item, "download");
      return;
    }

    if (action === "delete") {
      if (!isAdmin) {
        setGlobalMessage("当前账号为只读模式，无法删除");
        return;
      }
      const ok = window.confirm(`确认删除 ${item.name} 吗？该操作会移入回收站。`);
      if (!ok) {
        return;
      }
      try {
        const result = await deleteStorageObject(item.key, token);
        setPreview(null);
        setOfficeConfig(null);
        setSelectedItem(null);
        await loadList(prefix);
        if ((result?.trashed_count || 0) > 0) {
          notifyResourcesChanged();
          setGlobalMessage(`${item.name} 已移入回收站`);
        } else {
          setGlobalMessage(`${item.name} 已删除`);
        }
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }
  }

  async function submitFolder(event) {
    event.preventDefault();
    if (!isAdmin) {
      setGlobalMessage("当前账号为只读模式，无法新建文件夹");
      return;
    }
    const folderName = folderModal.name.trim();
    if (!folderName) {
      setGlobalMessage("请输入文件夹名称");
      return;
    }

    try {
      const data = await createStorageFolder({ prefix, name: folderName }, token);
      setFolderModal({ open: false, name: "" });
      await loadList(prefix, data.key);
      setGlobalMessage("文件夹已创建");
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  const previewNode = useMemo(() => {
    if (previewLoading) {
      return <p className="hint">预览加载中...</p>;
    }
    if (!preview) {
      return <p className="hint">请选择文件进行预览</p>;
    }

    if (preview.mode === "pdf" && preview.url) {
      return <iframe title="storage-pdf-preview" className="preview-frame" src={preview.url} />;
    }
    if (preview.mode === "video" && preview.url) {
      return (
        <video className="preview-video" src={preview.url} controls preload="metadata">
          您的浏览器不支持视频预览。
        </video>
      );
    }
    if (preview.mode === "image" && preview.url) {
      return (
        <img
          className="preview-image"
          src={preview.url}
          alt={preview?.name || "storage-image-preview"}
          loading="lazy"
        />
      );
    }
    if (preview.mode === "audio" && preview.url) {
      return (
        <audio className="preview-audio" src={preview.url} controls preload="metadata">
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
            title="storage-html-preview"
            className="preview-frame"
            srcDoc={preview.content}
            sandbox="allow-scripts allow-forms allow-popups allow-downloads"
          />
        );
      }
      const openUrl = preview.open_url || preview.url || "";
      if (openUrl) {
        return (
          <iframe
            title="storage-html-preview"
            className="preview-frame"
            src={openUrl}
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
        return (
          <OnlyOfficeViewer
            officeConfig={officeConfig}
            height={500}
            onError={(message) => setOfficeError(message || "OnlyOffice 预览加载失败")}
          />
        );
      }
      if (officeError) {
        return <p className="hint">{officeError}</p>;
      }
    }
    if (["word", "excel", "ppt"].includes(preview.mode) && preview.content) {
      const html = DOMPurify.sanitize(marked.parse(preview.content));
      return <div className="preview-rich" dangerouslySetInnerHTML={{ __html: html }} />;
    }
    if (preview.open_url || preview.url) {
      return (
        <a className="button-link" href={preview.open_url || preview.url} target="_blank" rel="noreferrer">
          打开文件
        </a>
      );
    }
    return <p className="hint">该文件暂不支持预览</p>;
  }, [preview, previewLoading, officeConfig, officeLoading, officeError]);

  if (!token) {
    return (
      <section className="card">
        <form onSubmit={handleLogin}>
          <h2>登录后使用文件管理</h2>
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
          <p className="hint">仅管理员可使用存储管理页</p>
        </form>
      </section>
    );
  }

  return (
    <>
      <section className="card storage-toolbar">
        <div className="storage-toolbar-top">
          <h2>MinIO 文件管理台（中文基础版）</h2>
          <div className="action-buttons">
            {isAdmin ? <button type="button" onClick={() => handleMenuAction("new-folder")}>新建文件夹</button> : null}
            {isAdmin ? (
              <button type="button" className="ghost" onClick={() => fileInputRef.current?.click()}>上传文件</button>
            ) : null}
            {isAdmin ? <button type="button" className="ghost" onClick={() => window.open("/storage/trash", "_self")}>回收站</button> : null}
            <button type="button" className="ghost" onClick={() => loadList(prefix, selectedItem?.key || "")}>刷新</button>
          </div>
          <input
            ref={fileInputRef}
            className="hidden-file-input"
            type="file"
            multiple
            onChange={(event) => uploadFiles(event.target.files)}
          />
        </div>
        {!isAdmin ? <p className="hint">当前账号为只读模式：可浏览、预览、下载，不能改写文件。</p> : null}
        <p className="hint">基础功能：浏览目录、上传文件、新建文件夹、预览、打开、下载、移动到回收站。</p>
        <div className="storage-breadcrumbs">
          {breadcrumbs.map((crumb, index) => (
            <button
              key={crumb.value || "root"}
              type="button"
              className={`crumb ${index === breadcrumbs.length - 1 ? "active" : ""}`}
              onClick={() => loadList(crumb.value)}
            >
              {crumb.label}
            </button>
          ))}
        </div>
        {uploadProgress > 0 ? (
          <div className="upload-progress-wrap">
            <div className="upload-progress-label">上传进度：{uploadProgress}%</div>
            <div className="upload-progress-track">
              <div className="upload-progress-fill" style={{ width: `${uploadProgress}%` }} />
            </div>
          </div>
        ) : null}
      </section>

      <section className="card storage-layout">
        <div
          className={`storage-list-wrap ${dragActive ? "drag-active" : ""}`}
          onDragOver={(event) => {
            if (!isAdmin) {
              return;
            }
            event.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={(event) => {
            if (!isAdmin) {
              return;
            }
            event.preventDefault();
            setDragActive(false);
          }}
          onDrop={(event) => {
            if (!isAdmin) {
              return;
            }
            event.preventDefault();
            setDragActive(false);
            uploadFiles(event.dataTransfer?.files);
          }}
        >
          <div className="storage-current-path">
            当前目录：{prefix || "/"}
          </div>
          <table className="storage-table">
            <thead>
              <tr>
                <th>名称</th>
                <th>类型</th>
                <th>大小</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={5}>加载中...</td>
                </tr>
              ) : null}
              {!loading && parentPrefix !== null ? (
                <tr className="storage-parent-row" onDoubleClick={() => loadList(parentPrefix)}>
                  <td colSpan={5}>..（返回上级）</td>
                </tr>
              ) : null}
              {!loading && !items.length ? (
                <tr>
                  <td colSpan={5} className="hint">当前目录为空</td>
                </tr>
              ) : null}
              {!loading
                ? items.map((item) => (
                    <tr
                      key={item.key}
                      className={selectedItem?.key === item.key ? "selected-row" : ""}
                      onClick={() => setSelectedItem(item)}
                      onDoubleClick={() => onItemDoubleClick(item)}
                    >
                      <td>
                        <span className={`storage-icon ${item.is_dir ? "folder" : "file"}`} />
                        {item.name}
                      </td>
                      <td>{itemLabel(item)}</td>
                      <td>{item.is_dir ? "-" : formatBytes(item.size)}</td>
                      <td>{formatTime(item.updated_at)}</td>
                      <td>
                        <div className="action-buttons">
                          <button
                            type="button"
                            className="ghost"
                            onClick={(event) => {
                              event.stopPropagation();
                              handleMenuAction("open", item);
                            }}
                          >
                            {item.is_dir ? "打开目录" : "打开"}
                          </button>
                          {!item.is_dir ? (
                            <button
                              type="button"
                              className="ghost"
                              onClick={(event) => {
                                event.stopPropagation();
                                handleMenuAction("preview", item);
                              }}
                            >
                              预览
                            </button>
                          ) : null}
                          {!item.is_dir ? (
                            <button
                              type="button"
                              className="ghost"
                              onClick={(event) => {
                                event.stopPropagation();
                                handleMenuAction("download", item);
                              }}
                            >
                              下载
                            </button>
                          ) : null}
                          {isAdmin ? (
                            <button
                              type="button"
                              className="ghost danger-item"
                              onClick={(event) => {
                                event.stopPropagation();
                                handleMenuAction("delete", item);
                              }}
                            >
                              回收站
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))
                : null}
            </tbody>
          </table>
        </div>

        <aside className="storage-preview-panel">
          <h3>预览</h3>
          {selectedItem ? (
            <div className="storage-preview-meta">
              <div><strong>名称：</strong>{selectedItem.name}</div>
              <div><strong>路径：</strong>{selectedItem.key}</div>
              <div><strong>类型：</strong>{itemLabel(selectedItem)}</div>
              <div><strong>大小：</strong>{selectedItem.is_dir ? "-" : formatBytes(selectedItem.size)}</div>
              <div className="action-buttons">
                <button
                  type="button"
                  onClick={() => handleMenuAction("open", selectedItem)}
                  disabled={!selectedItem.is_dir && actionBusy !== ""}
                >
                  {selectedItem.is_dir ? "打开目录" : actionBusy === "open" ? "处理中..." : "打开"}
                </button>
                <button type="button" className="ghost" onClick={() => handleMenuAction("preview", selectedItem)}>
                  预览
                </button>
                <button
                  type="button"
                  className="ghost"
                  onClick={() => handleMenuAction("download", selectedItem)}
                  disabled={!selectedItem.is_dir && actionBusy !== ""}
                >
                  {actionBusy === "download" ? "处理中..." : "下载"}
                </button>
                {isAdmin ? (
                  <button
                    type="button"
                    className="ghost danger-item"
                    onClick={() => handleMenuAction("delete", selectedItem)}
                  >
                    移动到回收站
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="hint">请选择左侧文件或文件夹</p>
          )}
          <div className="preview-box">{previewNode}</div>
        </aside>
      </section>

      {folderModal.open ? (
        <div className="modal-mask" onClick={() => setFolderModal({ open: false, name: "" })}>
          <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
            <form onSubmit={submitFolder}>
              <h3>新建文件夹</h3>
              <input
                type="text"
                value={folderModal.name}
                onChange={(event) => setFolderModal({ open: true, name: event.target.value })}
                placeholder="文件夹名称"
                required
              />
              <div className="action-buttons">
                <button type="submit">创建</button>
                <button type="button" className="ghost" onClick={() => setFolderModal({ open: false, name: "" })}>
                  取消
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  );
}
