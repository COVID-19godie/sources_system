export default function QuickSuggestionChips({
  title = "推荐",
  items = [],
  onPick
}) {
  if (!items.length) {
    return null;
  }

  return (
    <div className="quick-suggestion">
      <div className="hint">{title}</div>
      <div className="chip-group">
        {items.map((item) => (
          <button key={item} type="button" className="chip" onClick={() => onPick(item)}>
            {item}
          </button>
        ))}
      </div>
    </div>
  );
}
