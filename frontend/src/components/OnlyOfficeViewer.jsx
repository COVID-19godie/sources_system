import { useEffect, useMemo, useRef, useState } from "react";

let docsApiPromise = null;
const DEFAULT_OFFICE_ERROR =
  "OnlyOffice 服务不可用（可能是 /office 502），已可使用打开/下载按钮继续操作。";

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function loadDocsApi(scriptUrl) {
  if (window.DocsAPI) {
    return Promise.resolve();
  }
  if (docsApiPromise) {
    return docsApiPromise;
  }

  docsApiPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-onlyoffice-src="${scriptUrl}"]`);
    if (existing) {
      if (window.DocsAPI) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => {
          docsApiPromise = null;
          existing.remove();
          reject(new Error(DEFAULT_OFFICE_ERROR));
        },
        { once: true }
      );
      return;
    }

    const script = document.createElement("script");
    script.src = scriptUrl;
    script.async = true;
    script.dataset.onlyofficeSrc = scriptUrl;
    script.onload = () => resolve();
    script.onerror = () => {
      docsApiPromise = null;
      script.remove();
      reject(new Error(DEFAULT_OFFICE_ERROR));
    };
    document.head.appendChild(script);
  });

  return docsApiPromise;
}

export default function OnlyOfficeViewer({ officeConfig, height = 540, onError }) {
  const hostRef = useRef(null);
  const editorRef = useRef(null);
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState("");

  const containerId = useMemo(
    () => `onlyoffice-${Math.random().toString(36).slice(2, 10)}`,
    []
  );

  useEffect(() => {
    let cancelled = false;

    async function mountEditor() {
      if (!officeConfig?.document_server_js_url || !officeConfig?.config) {
        return;
      }

      setLoading(true);
      setErrorText("");
      try {
        let loaded = false;
        let lastError = null;
        for (let attempt = 1; attempt <= 3; attempt += 1) {
          try {
            await loadDocsApi(officeConfig.document_server_js_url);
            loaded = true;
            break;
          } catch (error) {
            docsApiPromise = null;
            lastError = error;
            if (attempt < 3) {
              await sleep(350 * attempt);
            }
          }
        }
        if (!loaded) {
          throw lastError || new Error(DEFAULT_OFFICE_ERROR);
        }
        if (cancelled) {
          return;
        }
        if (!window.DocsAPI || typeof window.DocsAPI.DocEditor !== "function") {
          throw new Error(DEFAULT_OFFICE_ERROR);
        }

        if (editorRef.current && typeof editorRef.current.destroyEditor === "function") {
          editorRef.current.destroyEditor();
        }
        if (hostRef.current) {
          hostRef.current.id = containerId;
        }
        editorRef.current = new window.DocsAPI.DocEditor(containerId, officeConfig.config);
      } catch (error) {
        const message = error instanceof Error ? error.message : DEFAULT_OFFICE_ERROR;
        setErrorText(message);
        if (typeof onError === "function") {
          onError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    mountEditor();
    return () => {
      cancelled = true;
      if (editorRef.current && typeof editorRef.current.destroyEditor === "function") {
        editorRef.current.destroyEditor();
      }
      editorRef.current = null;
    };
  }, [officeConfig, containerId, onError]);

  if (!officeConfig) {
    return <p className="hint">暂无 Office 预览配置</p>;
  }

  return (
    <div className="onlyoffice-wrap">
      {loading ? <div className="onlyoffice-status">OnlyOffice 加载中...</div> : null}
      {errorText ? <div className="onlyoffice-status error">{errorText}</div> : null}
      <div
        ref={hostRef}
        className="onlyoffice-host"
        style={{ minHeight: `${height}px` }}
      />
    </div>
  );
}
