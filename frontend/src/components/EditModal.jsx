export default function EditModal({
  open,
  title,
  onClose,
  onSubmit,
  submitText = "保存",
  disabled = false,
  children
}) {
  if (!open) {
    return null;
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="ghost" onClick={onClose}>关闭</button>
        </div>
        <form onSubmit={onSubmit}>
          {children}
          <div className="action-buttons">
            <button type="submit" disabled={disabled}>{submitText}</button>
            <button type="button" className="ghost" onClick={onClose}>取消</button>
          </div>
        </form>
      </div>
    </div>
  );
}
