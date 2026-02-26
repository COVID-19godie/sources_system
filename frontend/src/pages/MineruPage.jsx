import { useMemo, useState } from "react";

const DEFAULT_MINERU_URL = "https://mineru.net";

export default function MineruPage() {
  const [loaded, setLoaded] = useState(false);

  const mineruUrl = useMemo(() => {
    const envUrl = import.meta.env.VITE_MINERU_IFRAME_URL;
    if (typeof envUrl === "string" && envUrl.trim()) {
      return envUrl.trim();
    }
    return DEFAULT_MINERU_URL;
  }, []);

  return (
    <section className="card mineru-embed-card">
      <div className="mineru-embed-header">
        <div>
          <h2>MinerU 官方页面</h2>
          <p className="hint">已按你的要求改为官方页面 iframe 嵌入（1:1 使用官方界面）。</p>
        </div>
        <a href={mineruUrl} target="_blank" rel="noreferrer" className="button-link">
          新窗口打开官方页
        </a>
      </div>

      <div className="mineru-embed-wrap">
        {!loaded ? <div className="mineru-embed-loading">正在加载 MinerU 官方页面...</div> : null}
        <iframe
          title="MinerU 官方页面"
          src={mineruUrl}
          className="mineru-embed-iframe"
          onLoad={() => setLoaded(true)}
          allow="clipboard-read; clipboard-write"
          referrerPolicy="no-referrer-when-downgrade"
        />
      </div>

      <p className="hint">
        如果浏览器显示拒绝嵌入（X-Frame-Options/CSP），请点击“新窗口打开官方页”。
      </p>
    </section>
  );
}
