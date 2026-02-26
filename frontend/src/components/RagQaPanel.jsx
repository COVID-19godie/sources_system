export default function RagQaPanel({
  question,
  loading,
  answer,
  citations,
  logs,
  onQuestionChange,
  onAsk,
  onLocateCitation
}) {
  return (
    <section className="card rag-qa-panel">
      <h3>问答与证据</h3>
      <div className="row-inline">
        <input
          type="text"
          value={question}
          placeholder="输入问题，例如：楞次定律如何判定感应电流方向？"
          onChange={(event) => onQuestionChange(event.target.value)}
        />
        <button type="button" onClick={onAsk} disabled={loading}>
          {loading ? "回答中..." : "提问"}
        </button>
      </div>

      {answer ? <p className="rag-answer">{answer}</p> : <p className="hint">暂无回答</p>}

      <div className="rag-citation-list">
        <h4>证据引用</h4>
        {citations.length ? citations.map((item, index) => (
          <button
            type="button"
            key={`${item.source_id}-${index}`}
            className="rag-citation-item"
            onClick={() => onLocateCitation(item)}
          >
            <strong>{item.title}</strong>
            <span className="hint">概率 {Number(item.score || 0).toFixed(3)}</span>
            <span>{item.evidence}</span>
          </button>
        )) : <p className="hint">暂无证据</p>}
      </div>

      <div className="rag-log-list">
        <h4>最近问答日志</h4>
        {logs.length ? logs.map((item) => (
          <div key={item.id} className="rag-log-item">
            <strong>Q: {item.question}</strong>
            <p>A: {item.answer}</p>
          </div>
        )) : <p className="hint">暂无日志</p>}
      </div>
    </section>
  );
}
