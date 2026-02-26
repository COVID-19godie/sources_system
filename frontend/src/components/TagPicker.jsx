import { useMemo, useState } from "react";

const CATEGORY_LABELS = {
  mechanics: "力学",
  electromagnetism: "电磁学",
  thermodynamics: "热学",
  optics: "光学",
  modern_physics: "近代物理",
  experiment: "实验",
  problem_solving: "解题",
  other: "其他"
};

function groupByCategory(tags) {
  const groups = {};
  for (const item of tags) {
    const key = item.category || "other";
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(item);
  }
  return Object.entries(groups).sort((a, b) => {
    const left = CATEGORY_LABELS[a[0]] || a[0];
    const right = CATEGORY_LABELS[b[0]] || b[0];
    return left.localeCompare(right, "zh-CN");
  });
}

export default function TagPicker({
  tagOptions = [],
  selectedTags = [],
  onChange,
  allowCustom = true
}) {
  const [customTag, setCustomTag] = useState("");
  const grouped = useMemo(() => groupByCategory(tagOptions), [tagOptions]);

  function toggleTag(tag) {
    if (selectedTags.includes(tag)) {
      onChange(selectedTags.filter((item) => item !== tag));
      return;
    }
    onChange([...selectedTags, tag]);
  }

  function addCustomTag() {
    const value = customTag.trim();
    if (!value || selectedTags.includes(value)) {
      setCustomTag("");
      return;
    }
    onChange([...selectedTags, value]);
    setCustomTag("");
  }

  return (
    <div className="tag-picker">
      {grouped.map(([category, items]) => (
        <div key={category}>
          <div className="hint">{CATEGORY_LABELS[category] || category}</div>
          <div className="chip-group">
            {items.map((item) => {
              const active = selectedTags.includes(item.tag);
              return (
                <button
                  type="button"
                  key={item.id}
                  className={`chip ${active ? "active" : ""}`}
                  onClick={() => toggleTag(item.tag)}
                >
                  {item.tag}
                </button>
              );
            })}
          </div>
        </div>
      ))}

      {allowCustom && (
        <div className="row-inline">
          <input
            type="text"
            placeholder="其他标签（可选）"
            value={customTag}
            onChange={(event) => setCustomTag(event.target.value)}
          />
          <button type="button" className="ghost" onClick={addCustomTag}>添加</button>
        </div>
      )}

      {selectedTags.length ? (
        <div className="chip-group selected-chip-wrap">
          {selectedTags.map((tag) => (
            <button key={tag} type="button" className="chip active" onClick={() => toggleTag(tag)}>
              {tag} ×
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
