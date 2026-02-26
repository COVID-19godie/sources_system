export default function RagSemanticPanel({
  query,
  loading,
  results,
  threshold,
  onQueryChange,
  onRun,
  onSelectResult
}) {
  return (
    <section className="card rag-semantic-panel">
      <h3>语义搜索（Top20 + 概率阈值）</h3>
      <div className="row-inline">
        <input
          type="text"
          value={query}
          placeholder="输入问题，例如：电磁感应中楞次定律的实验题"
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <button type="button" onClick={onRun} disabled={loading}>
          {loading ? "检索中..." : "检索"}
        </button>
      </div>
      <p className="hint">当前阈值：{(Number(threshold || 0) * 100).toFixed(2)}%</p>
      <div className="rag-semantic-results">
        {results.length ? results.map((item, index) => (
          <button
            type="button"
            key={`${item.target?.source_id || item.resource?.id}-${index}`}
            className="rag-semantic-item"
            onClick={() => onSelectResult(item)}
          >
            <strong>{item.target?.title || item.resource?.title || "未命名"}</strong>
            <span>概率 {(Number(item.probability || 0) * 100).toFixed(1)}%</span>
            <span className="hint">
              向量 {Number(item.factors?.vector || 0).toFixed(2)} / 摘要 {Number(item.factors?.summary || 0).toFixed(2)} / 内容 {Number(item.factors?.content || 0).toFixed(2)} / 标签 {Number(item.factors?.tags || 0).toFixed(2)}
            </span>
          </button>
        )) : <p className="hint">暂无结果</p>}
      </div>
    </section>
  );
}
