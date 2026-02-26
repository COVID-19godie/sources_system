function renderNodeType(type) {
  if (type === "chapter") return "章节";
  if (type === "section") return "板块";
  if (type === "format") return "格式分层";
  if (type === "resource") return "资源";
  if (type === "knowledge_point") return "知识点";
  if (type === "formula") return "公式";
  if (type === "experiment") return "实验";
  if (type === "problem_type") return "题型";
  return type || "节点";
}

function renderTags(tags) {
  if (!Array.isArray(tags) || !tags.length) {
    return null;
  }
  return (
    <div className="rag-node-tags">
      {tags.slice(0, 8).map((tag) => (
        <span key={tag}>{tag}</span>
      ))}
    </div>
  );
}

export default function RagNodeInspector({
  node,
  linkedResources = [],
  loadingLinks = false,
  variants = [],
  variantsMeta = null,
  loadingVariants = false
}) {
  if (!node) {
    return (
      <section className="rag-inspector card">
        <h3>节点详情</h3>
        <p className="hint">点击画布节点查看关联资源</p>
      </section>
    );
  }

  const autoKind = variantsMeta?.autoOpenVariantKind || null;
  const autoVariant = variants.find((item) => item.variant_kind === autoKind) || null;
  const primaryVariant = variants.find((item) => item.is_primary) || null;
  const originVariant = variants.find((item) => item.variant_kind === "origin") || null;
  const preferredVariant = autoVariant || primaryVariant || null;
  const openPath = preferredVariant?.open_url || (node.resource_id ? `/viewer/resource/${node.resource_id}` : null);
  const downloadOriginalPath = originVariant?.download_url || preferredVariant?.download_url || null;

  return (
    <section className="rag-inspector card">
      <h3>节点详情</h3>
      <h4 title={node.label}>{node.keyword_label || node.label}</h4>
      <p className="hint">类型：{renderNodeType(node.node_type)}</p>
      {node.resource_id ? <p className="hint">资源ID：{node.resource_id}</p> : null}
      {node.meta?.difficulty ? <p className="hint">难度：{node.meta.difficulty}</p> : null}
      {node.meta?.file_format ? <p className="hint">格式：{node.meta.file_format}</p> : null}
      {node.meta?.visibility ? <p className="hint">可见性：{node.meta.visibility}</p> : null}

      {node.meta?.summary ? <p className="rag-node-summary">{node.meta.summary}</p> : null}
      {node.meta?.description ? <p className="rag-node-summary">{node.meta.description}</p> : null}
      {renderTags(node.meta?.tags)}

      <div className="rag-open-actions">
        {openPath ? (
          <a
            className="button-link"
            href={openPath}
            target="_blank"
            rel="noopener noreferrer"
          >
            打开资源
          </a>
        ) : (
          <button type="button" className="ghost" disabled>
            该节点无直接资源
          </button>
        )}
        {downloadOriginalPath ? (
          <a className="button-link" href={downloadOriginalPath} target="_blank" rel="noopener noreferrer">
            下载原件
          </a>
        ) : null}
      </div>

      <section className="rag-linked-list">
        <h4>文件变体</h4>
        {variantsMeta?.canonicalKey ? <p className="hint">Canonical: {variantsMeta.canonicalKey}</p> : null}
        {variantsMeta?.autoOpenVariantKind ? <p className="hint">默认打开策略：{variantsMeta.autoOpenVariantKind}</p> : null}
        {loadingVariants ? <p className="hint">变体加载中...</p> : null}
        {!loadingVariants && !variants.length ? <p className="hint">暂无可用变体</p> : null}
        {!loadingVariants ? variants.map((item) => (
          <div key={`${item.source_id}-${item.variant_kind || "variant"}`} className="rag-linked-item">
            <div>
              <strong>{item.title}</strong>
              <div className="hint">
                {item.variant_kind || "variant"} · {item.file_format || "-"} · {item.visibility}
              </div>
            </div>
            <div className="row-inline">
              {item.open_url ? (
                <a className="button-link" href={item.open_url} target="_blank" rel="noopener noreferrer">打开</a>
              ) : (
                <button type="button" className="ghost" disabled>不可打开</button>
              )}
              {item.download_url ? (
                <a className="button-link" href={item.download_url} target="_blank" rel="noopener noreferrer">下载</a>
              ) : null}
            </div>
          </div>
        )) : null}
      </section>

      <section className="rag-linked-list">
        <h4>关联资源 Top5</h4>
        {loadingLinks ? <p className="hint">加载中...</p> : null}
        {!loadingLinks && !linkedResources.length ? <p className="hint">暂无关联资源</p> : null}
        {!loadingLinks ? linkedResources.map((item) => (
          <div key={`${item.source_id}-${item.resource_id || "none"}`} className="rag-linked-item">
            <div>
              <strong>{item.keyword_title}</strong>
              <div className="hint">相关度 {Number(item.score || 0).toFixed(3)}</div>
            </div>
            {item.is_openable && item.open_path ? (
              <a
                className="button-link"
                href={item.open_path}
                target="_blank"
                rel="noopener noreferrer"
              >
                打开
              </a>
            ) : (
              <button type="button" className="ghost" disabled>{item.message || "不可打开"}</button>
            )}
          </div>
        )) : null}
      </section>
    </section>
  );
}
