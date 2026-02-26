const MODES = [
  { key: "browse", label: "浏览模式" },
  { key: "build", label: "建图模式" },
  { key: "qa", label: "问答模式" }
];

export default function RagModeSwitch({ mode, onChange }) {
  return (
    <div className="rag-mode-switch">
      {MODES.map((item) => (
        <button
          type="button"
          key={item.key}
          className={mode === item.key ? "active" : ""}
          onClick={() => onChange(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
