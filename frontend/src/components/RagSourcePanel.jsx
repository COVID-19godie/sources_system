import { formatTime } from "../lib/api";

export default function RagSourcePanel({
  canManage,
  workspaces,
  activeWorkspaceId,
  onWorkspaceChange,
  onCreateWorkspace,
  newWorkspace,
  onNewWorkspaceChange,
  availableResources,
  selectedResourceIds,
  onToggleResource,
  onBindResources,
  uploadState,
  onUploadStateChange,
  onUpload,
  onExtractQuick,
  onExtractFull,
  onRefresh,
  sources,
  jobs,
  onPublishSource
}) {
  return (
    <details className="card rag-advanced-panel">
      <summary>高级设置</summary>
      <div className="rag-advanced-body">
        <section>
          <h4>工作台</h4>
          <select value={activeWorkspaceId || ""} onChange={(event) => onWorkspaceChange(event.target.value)}>
            <option value="">请选择工作台</option>
            {workspaces.map((item) => (
              <option key={item.id} value={item.id}>{item.name}（{item.subject}）</option>
            ))}
          </select>
          <div className="row-inline">
            <button type="button" className="ghost" onClick={onRefresh} disabled={!activeWorkspaceId}>刷新数据</button>
          </div>
        </section>

        {canManage ? (
          <section>
            <h4>创建工作台</h4>
            <input
              type="text"
              placeholder="新工作台名称"
              value={newWorkspace.name}
              onChange={(event) => onNewWorkspaceChange({ ...newWorkspace, name: event.target.value })}
            />
            <button type="button" onClick={onCreateWorkspace}>创建</button>
          </section>
        ) : null}

        {canManage ? (
          <section>
            <h4>手动绑定资源</h4>
            <div className="rag-resource-picker">
              {availableResources.length ? availableResources.map((item) => (
                <label key={item.id}>
                  <input
                    type="checkbox"
                    checked={selectedResourceIds.includes(item.id)}
                    onChange={() => onToggleResource(item.id)}
                  />
                  <span>{item.title}</span>
                </label>
              )) : <p className="hint">暂无可绑定资源</p>}
            </div>
            <button type="button" onClick={onBindResources} disabled={!activeWorkspaceId}>绑定选中资源</button>
          </section>
        ) : null}

        {canManage ? (
          <section>
            <h4>手动上传源</h4>
            <input
              type="file"
              onChange={(event) => onUploadStateChange({ ...uploadState, file: event.target.files?.[0] || null })}
            />
            <input
              type="text"
              placeholder="标题（可选）"
              value={uploadState.title}
              onChange={(event) => onUploadStateChange({ ...uploadState, title: event.target.value })}
            />
            <input
              type="text"
              placeholder="标签（逗号分隔）"
              value={uploadState.tags}
              onChange={(event) => onUploadStateChange({ ...uploadState, tags: event.target.value })}
            />
            <button type="button" onClick={onUpload} disabled={!activeWorkspaceId || !uploadState.file}>上传</button>
            <p className="hint">上传进度：{uploadState.progress}%</p>
          </section>
        ) : null}

        {canManage ? (
          <section>
            <h4>建图任务</h4>
            <div className="row-inline rag-extract-actions">
              <button type="button" onClick={onExtractQuick} disabled={!activeWorkspaceId}>Quick建图</button>
              <button type="button" onClick={onExtractFull} disabled={!activeWorkspaceId}>Full建图</button>
            </div>
            <div className="rag-job-list">
              {jobs.length ? jobs.map((item) => (
                <div key={item.id} className="rag-job-item">
                  <strong>{item.mode.toUpperCase()} · {item.status}</strong>
                  <span className="hint">{formatTime(item.created_at)}</span>
                </div>
              )) : <p className="hint">暂无任务</p>}
            </div>
          </section>
        ) : null}

        <section>
          <h4>数据源列表</h4>
          <div className="rag-source-list">
            {sources.length ? sources.map((item) => (
              <div key={item.id} className="rag-source-item">
                <strong>{item.title}</strong>
                <span className="hint">{item.source_type} · {item.file_format || "other"} · {item.status}</span>
                <span className="hint">更新时间：{formatTime(item.updated_at)}</span>
                {canManage && item.source_type === "upload" ? (
                  <button type="button" className="ghost" onClick={() => onPublishSource(item.id)}>发布到资源库</button>
                ) : null}
              </div>
            )) : <p className="hint">暂无数据源</p>}
          </div>
        </section>
      </div>
    </details>
  );
}
