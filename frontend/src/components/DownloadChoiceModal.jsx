export default function DownloadChoiceModal({
  open = false,
  title = "下载资源",
  openUrl = "",
  downloadUrl = "",
  onClose
}) {
  if (!open) {
    return null;
  }

  function launch(url) {
    if (!url) {
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
    if (typeof onClose === "function") {
      onClose();
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal-panel" onClick={(event) => event.stopPropagation()}>
        <h3>{title}</h3>
        <p className="hint">请选择操作方式</p>
        <div className="action-buttons">
          <button type="button" onClick={() => launch(openUrl)} disabled={!openUrl}>
            在新窗口打开
          </button>
          <button type="button" onClick={() => launch(downloadUrl)} disabled={!downloadUrl}>
            直接下载
          </button>
          <button type="button" className="ghost" onClick={onClose}>
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
