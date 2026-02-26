const API_BASE = import.meta.env.VITE_API_URL || "";

export function makeApiUrl(path) {
  return `${API_BASE}${path}`;
}

export function notifyResourcesChanged() {
  window.dispatchEvent(new Event("resources-changed"));
}

function normalizeErrorDetail(detail, fallback) {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }

  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object") {
          const location = Array.isArray(item.loc) ? item.loc.join(".") : "";
          const message = typeof item.msg === "string" ? item.msg : "";
          return [location, message].filter(Boolean).join(": ");
        }
        return "";
      })
      .filter(Boolean);

    if (parts.length) {
      return parts.join("；");
    }
  }

  if (detail && typeof detail === "object") {
    try {
      return JSON.stringify(detail);
    } catch {
      return fallback;
    }
  }

  return fallback;
}

export async function apiRequest(path, options = {}) {
  const { method = "GET", token = "", body = null, isForm = false } = options;
  const headers = {};

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body && !isForm) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(makeApiUrl(path), {
    method,
    headers,
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined
  });

  if (!response.ok) {
    if (response.status === 401) {
      localStorage.removeItem("token");
      localStorage.removeItem("role");
      localStorage.removeItem("email");
      window.dispatchEvent(new Event("auth-expired"));
      throw new Error("登录状态已失效，请重新登录");
    }

    let detail = `请求失败：${response.status}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        detail = normalizeErrorDetail(errorData.detail, detail);
      }
    } catch {
      // ignore JSON parse failures
    }
    throw new Error(detail);
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return null;
  }

  return response.json();
}

export function uploadWithProgress(path, options = {}) {
  const { token = "", body, onProgress } = options;

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", makeApiUrl(path), true);

    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || typeof onProgress !== "function") {
        return;
      }
      const percent = Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100)));
      onProgress(percent);
    };

    xhr.onerror = () => {
      reject(new Error("上传失败：网络错误"));
    };

    xhr.onload = () => {
      const responseText = xhr.responseText || "";
      let parsed = null;
      try {
        parsed = responseText ? JSON.parse(responseText) : null;
      } catch {
        parsed = null;
      }

      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = parsed?.detail ? normalizeErrorDetail(parsed.detail, "") : "";
        reject(new Error(detail || `请求失败：${xhr.status}`));
        return;
      }

      resolve(parsed);
    };

    xhr.send(body);
  });
}

export function uploadStorageWithProgress(options = {}) {
  const {
    token = "",
    prefix = "",
    file,
    onProgress
  } = options;
  const formData = new FormData();
  formData.append("prefix", prefix || "");
  formData.append("file", file);
  return uploadWithProgress("/api/storage/upload", {
    token,
    body: formData,
    onProgress
  });
}

export async function listStorage(options = {}) {
  const { token = "", prefix = "" } = options;
  const params = new URLSearchParams();
  if (prefix) {
    params.set("prefix", prefix);
  }
  return apiRequest(`/api/storage/list?${params.toString()}`, { token });
}

export async function createStorageFolder(payload, token) {
  return apiRequest("/api/storage/folder", {
    method: "POST",
    token,
    body: payload
  });
}

export async function renameStorageObject(payload, token) {
  return apiRequest("/api/storage/rename", {
    method: "POST",
    token,
    body: payload
  });
}

export async function deleteStorageObject(key, token) {
  const params = new URLSearchParams();
  params.set("key", key);
  return apiRequest(`/api/storage/object?${params.toString()}`, {
    method: "DELETE",
    token
  });
}

export async function reconcileStorage({ token = "", dryRun = false } = {}) {
  const params = new URLSearchParams();
  if (dryRun) {
    params.set("dry_run", "true");
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest(`/api/storage/reconcile${query}`, {
    method: "POST",
    token
  });
}

export async function getStorageDownloadUrl(key, token) {
  const params = new URLSearchParams();
  params.set("key", key);
  return apiRequest(`/api/storage/download-url?${params.toString()}`, { token });
}

export async function getStorageAccessUrls(key, token) {
  const params = new URLSearchParams();
  params.set("key", key);
  return apiRequest(`/api/storage/access-urls?${params.toString()}`, { token });
}

export async function previewStorageObject(key, token) {
  const params = new URLSearchParams();
  params.set("key", key);
  return apiRequest(`/api/storage/preview?${params.toString()}`, { token });
}

export async function getStorageOfficeConfig(key, token) {
  const params = new URLSearchParams();
  params.set("key", key);
  return apiRequest(`/api/storage/office-config?${params.toString()}`, { token });
}

export async function getResourceOfficeConfig(resourceId, token) {
  return apiRequest(`/api/resources/${resourceId}/office-config`, { token });
}

export async function getResourceAccessUrls(resourceId, token) {
  return apiRequest(`/api/resources/${resourceId}/access-urls`, { token });
}

export async function listAdminResources(options = {}) {
  const {
    token = "",
    q = "",
    status = "",
    chapterId = "",
    sectionId = "",
    subject = "",
    grade = "",
    page = 1,
    pageSize = 200
  } = options;
  const params = new URLSearchParams();
  params.set("all", "true");
  params.set("legacy_flat", "false");
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  if (q.trim()) {
    params.set("q", q.trim());
  }
  if (status.trim()) {
    params.set("status", status.trim());
  }
  if (chapterId) {
    params.set("chapter_id", String(chapterId));
  }
  if (sectionId) {
    params.set("section_id", String(sectionId));
  }
  if (subject.trim()) {
    params.set("subject", subject.trim());
  }
  if (grade.trim()) {
    params.set("grade", grade.trim());
  }
  const data = await apiRequest(`/api/resources?${params.toString()}`, { token });
  if (Array.isArray(data)) {
    return data;
  }
  return data?.items || [];
}

export async function setResourceVisibility(resourceId, visibility, token, note = "") {
  return apiRequest(`/api/resources/${resourceId}/visibility`, {
    method: "PATCH",
    token,
    body: {
      visibility,
      note: note || null
    }
  });
}

export async function bulkManageResources(payload, token) {
  return apiRequest("/api/resources/bulk-manage", {
    method: "POST",
    token,
    body: payload
  });
}

export async function updateResourceTags(resourceId, payload, token) {
  return apiRequest(`/api/resources/${resourceId}/tags`, {
    method: "PATCH",
    token,
    body: payload
  });
}

export async function adoptResourceAiTags(resourceId, payload, token) {
  return apiRequest(`/api/resources/${resourceId}/tags/adopt-ai`, {
    method: "POST",
    token,
    body: payload
  });
}

export function formatTime(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString("zh-CN");
}

export async function fetchUploadOptions(options = {}) {
  const {
    token = "",
    stage = "senior",
    subject = "物理"
  } = options;
  const params = new URLSearchParams();
  params.set("stage", stage);
  params.set("subject", subject);
  return apiRequest(`/api/meta/upload-options?${params.toString()}`, { token });
}

export async function getRagGraph(options = {}) {
  const {
    token = "",
    stage = "senior",
    subject = "物理",
    chapterId = "",
    keyword = "",
    limit = 200,
    similarityThreshold = 0.78,
    maxLinksPerResource = 2
  } = options;
  const params = new URLSearchParams();
  params.set("stage", stage);
  params.set("subject", subject);
  params.set("limit", String(limit));
  params.set("similarity_threshold", String(similarityThreshold));
  params.set("max_links_per_resource", String(maxLinksPerResource));
  if (chapterId) {
    params.set("chapter_id", String(chapterId));
  }
  if (keyword && keyword.trim()) {
    params.set("q", keyword.trim());
  }
  return apiRequest(`/api/rag/graph?${params.toString()}`, { token });
}

export async function listRagWorkspaces(options = {}) {
  const { token = "", stage = "", subject = "" } = options;
  const params = new URLSearchParams();
  if (stage.trim()) {
    params.set("stage", stage.trim());
  }
  if (subject.trim()) {
    params.set("subject", subject.trim());
  }
  const query = params.toString() ? `?${params.toString()}` : "";
  return apiRequest(`/api/rag/workspaces${query}`, { token });
}

export async function quickBootstrapRag(options = {}) {
  const {
    token = "",
    stage = "senior",
    subject = "物理",
    forceExtract = false
  } = options;
  return apiRequest("/api/rag/quick-bootstrap", {
    method: "POST",
    token,
    body: {
      stage,
      subject,
      force_extract: forceExtract
    }
  });
}

export async function createRagWorkspace(payload, token) {
  return apiRequest("/api/rag/workspaces", {
    method: "POST",
    token,
    body: payload
  });
}

export async function listRagSources(workspaceId, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/sources`, { token });
}

export async function bindRagResources(workspaceId, resourceIds, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/sources/bind-resources`, {
    method: "POST",
    token,
    body: { resource_ids: resourceIds }
  });
}

export function uploadRagSourceWithProgress(options = {}) {
  const {
    workspaceId,
    token = "",
    file,
    title = "",
    summaryText = "",
    tags = "",
    onProgress
  } = options;
  const formData = new FormData();
  formData.append("file", file);
  formData.append("title", title);
  formData.append("summary_text", summaryText);
  formData.append("tags", tags);
  return uploadWithProgress(`/api/rag/workspaces/${workspaceId}/sources/upload`, {
    token,
    body: formData,
    onProgress
  });
}

export async function extractRagWorkspace(workspaceId, payload, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/extract`, {
    method: "POST",
    token,
    body: payload
  });
}

export async function getRagWorkspaceGraph(workspaceId, options = {}) {
  const {
    token = "",
    q = "",
    limit = 200,
    scope = "public",
    includeFormatNodes = true,
    dedupe = true,
    includeVariants = true
  } = options;
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("scope", scope);
  params.set("include_format_nodes", includeFormatNodes ? "true" : "false");
  params.set("dedupe", dedupe ? "true" : "false");
  params.set("include_variants", includeVariants ? "true" : "false");
  if (q.trim()) {
    params.set("q", q.trim());
  }
  return apiRequest(`/api/rag/workspaces/${workspaceId}/graph?${params.toString()}`, { token });
}

export async function getRagBootstrapJob(workspaceId, jobId, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/bootstrap-jobs/${jobId}`, { token });
}

export async function getRagBootstrapJobErrors(workspaceId, jobId, options = {}) {
  const { token = "", page = 1, pageSize = 20 } = options;
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  return apiRequest(
    `/api/rag/workspaces/${workspaceId}/bootstrap-jobs/${jobId}/errors?${params.toString()}`,
    { token }
  );
}

export async function getRagNodeVariants(workspaceId, nodeId, options = {}) {
  const { token = "" } = options;
  const encodedNodeId = encodeURIComponent(nodeId);
  return apiRequest(`/api/rag/workspaces/${workspaceId}/nodes/${encodedNodeId}/variants`, { token });
}

export async function getNodeLinkedResources(workspaceId, nodeId, options = {}) {
  const { token = "", limit = 5 } = options;
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const encodedNodeId = encodeURIComponent(nodeId);
  return apiRequest(`/api/rag/workspaces/${workspaceId}/nodes/${encodedNodeId}/linked-resources?${params.toString()}`, { token });
}

export async function semanticSearchResources(payload, token) {
  return apiRequest("/api/resources/semantic-search", {
    method: "POST",
    token,
    body: payload
  });
}

export async function semanticSearchWorkspace(workspaceId, payload, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/semantic-search`, {
    method: "POST",
    token,
    body: payload
  });
}

export async function askRagWorkspace(workspaceId, question, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/qa`, {
    method: "POST",
    token,
    body: { question }
  });
}

export async function listRagJobs(workspaceId, token, limit = 50) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  return apiRequest(`/api/rag/workspaces/${workspaceId}/jobs?${params.toString()}`, { token });
}

export async function listRagQaLogs(workspaceId, token, limit = 50) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  return apiRequest(`/api/rag/workspaces/${workspaceId}/qa/logs?${params.toString()}`, { token });
}

export async function publishRagSource(workspaceId, sourceId, token) {
  return apiRequest(`/api/rag/workspaces/${workspaceId}/sources/${sourceId}/publish`, {
    method: "POST",
    token
  });
}

export async function getUploadPathPreview(options = {}) {
  const {
    token = "",
    filename = "",
    chapterId = "",
    sectionId = "",
    volumeCode = "",
    lowConfidence = false
  } = options;
  const params = new URLSearchParams();
  params.set("filename", filename || "resource");
  if (chapterId) {
    params.set("chapter_id", String(chapterId));
  }
  if (sectionId) {
    params.set("section_id", String(sectionId));
  }
  if (volumeCode) {
    params.set("volume_code", String(volumeCode));
  }
  if (lowConfidence) {
    params.set("low_confidence", "true");
  }
  return apiRequest(`/api/resources/upload-path-preview?${params.toString()}`, { token });
}

export async function autoClassifyResource(options = {}) {
  const {
    token = "",
    file = null,
    title = "",
    description = "",
    tags = "",
    subject = "物理",
    stage = "senior",
    volumeCode = "",
    selectedVolumeCode = "",
    externalUrl = ""
  } = options;
  const formData = new FormData();
  formData.append("title", title || "");
  formData.append("description", description || "");
  formData.append("tags", tags || "");
  formData.append("subject", subject || "物理");
  formData.append("stage", stage || "senior");
  formData.append("volume_code", volumeCode || "");
  formData.append("selected_volume_code", selectedVolumeCode || "");
  formData.append("external_url", externalUrl || "");
  if (file) {
    formData.append("file", file);
  }
  return apiRequest("/api/resources/auto-classify", {
    method: "POST",
    token,
    body: formData,
    isForm: true
  });
}

export async function fetchTags(options = {}) {
  const {
    token = "",
    stage = "senior",
    subject = "物理",
    enabledOnly = false,
    q = ""
  } = options;
  const params = new URLSearchParams();
  params.set("stage", stage);
  params.set("subject", subject);
  if (enabledOnly) {
    params.set("enabled_only", "true");
  }
  if (q.trim()) {
    params.set("q", q.trim());
  }
  return apiRequest(`/api/tags?${params.toString()}`, { token });
}

export async function createTag(payload, token) {
  return apiRequest("/api/tags", {
    method: "POST",
    token,
    body: payload
  });
}

export async function updateTag(tagId, payload, token) {
  return apiRequest(`/api/tags/${tagId}`, {
    method: "PATCH",
    token,
    body: payload
  });
}

export async function reorderTags(items, token) {
  return apiRequest("/api/tags/reorder", {
    method: "POST",
    token,
    body: { items }
  });
}

export async function listTrashItems(options = {}) {
  const {
    token = "",
    scope = "",
    q = "",
    page = 1,
    pageSize = 20
  } = options;
  const params = new URLSearchParams();
  if (scope.trim()) {
    params.set("scope", scope.trim());
  }
  if (q.trim()) {
    params.set("q", q.trim());
  }
  params.set("page", String(page));
  params.set("page_size", String(pageSize));
  return apiRequest(`/api/trash/items?${params.toString()}`, { token });
}

export async function restoreTrashItem(itemId, token) {
  return apiRequest(`/api/trash/items/${itemId}/restore`, {
    method: "POST",
    token
  });
}

export async function purgeTrashItem(itemId, token) {
  return apiRequest(`/api/trash/items/${itemId}`, {
    method: "DELETE",
    token
  });
}

export async function purgeExpiredTrash(token, limit = 500) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  return apiRequest(`/api/trash/purge-expired?${params.toString()}`, {
    method: "POST",
    token
  });
}
