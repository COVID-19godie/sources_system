import { formatTime } from "../lib/api";

const TYPE_LABELS = {
  document: "文档",
  ppt: "课件",
  video: "视频",
  image: "图片",
  audio: "音频",
  exercise: "习题"
};

export default function ResourceCard({ item, onClick, canDelete = false, onDelete }) {
  const sectionName = item.section?.name || "未分区";
  return (
    <article className="resource-card" onClick={() => onClick(item)}>
      <div className={`resource-cover type-${item.type}`}>
        <span>{TYPE_LABELS[item.type] || item.type}</span>
      </div>
      <div className="resource-body">
        <h3>{item.title}</h3>
        <p>{item.description || "暂无描述"}</p>
        <div className="resource-meta">
          <span>{item.subject || "未分类学科"}</span>
          <span>{item.grade || "全年级"}</span>
          <span>{sectionName}</span>
          <span>{formatTime(item.updated_at)}</span>
        </div>
        {canDelete ? (
          <div className="action-buttons" style={{ marginTop: 8 }}>
            <button
              type="button"
              className="ghost danger-item"
              onClick={(event) => {
                event.stopPropagation();
                if (typeof onDelete === "function") {
                  onDelete(item);
                }
              }}
            >
              删除到回收站
            </button>
          </div>
        ) : null}
      </div>
    </article>
  );
}
