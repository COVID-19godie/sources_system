import { useEffect, useState } from "react";
import {
  listTrashItems,
  notifyResourcesChanged,
  purgeExpiredTrash,
  purgeTrashItem,
  reconcileStorage,
  restoreTrashItem
} from "../lib/api";

export default function StorageTrashPage({ token, role, onLogin, setGlobalMessage }) {
  const isAdmin = role === "admin";
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [items, setItems] = useState([]);
  const [scope, setScope] = useState("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);

  async function loadTrash(targetPage = page) {
    if (!token || !isAdmin) {
      setItems([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    try {
      const data = await listTrashItems({
        token,
        scope: scope === "all" ? "" : scope,
        q: query,
        page: targetPage,
        pageSize
      });
      setItems(data?.items || []);
      setTotal(data?.total || 0);
      setPage(data?.page || targetPage);
    } catch (error) {
      setGlobalMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTrash(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, role, scope, query, pageSize]);

  async function handleLogin(event) {
    event.preventDefault();
    try {
      await onLogin(loginForm);
      setLoginForm({ email: "", password: "" });
      setGlobalMessage("登录成功");
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleRestore(itemId) {
    try {
      const result = await restoreTrashItem(itemId, token);
      setGlobalMessage(`恢复成功：${result.restored_key || "-"}`);
      notifyResourcesChanged();
      await loadTrash(page);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handlePurge(itemId) {
    const ok = window.confirm("确认彻底删除该回收站条目？该操作不可恢复。");
    if (!ok) {
      return;
    }
    try {
      await purgeTrashItem(itemId, token);
      setGlobalMessage("已彻底删除");
      await loadTrash(page);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleReconcile() {
    try {
      const result = await reconcileStorage({ token });
      setGlobalMessage(
        `对账完成：扫描 ${result.scanned_count}，缺失 ${result.missing_count}，入回收站 ${result.trashed_count}`
      );
      if ((result?.trashed_count || 0) > 0) {
        notifyResourcesChanged();
      }
      await loadTrash(page);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handlePurgeExpired() {
    try {
      const result = await purgeExpiredTrash(token);
      setGlobalMessage(`已清理过期条目 ${result.purged_count} 条`);
      await loadTrash(page);
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  if (!token) {
    return (
      <section className="card">
        <form onSubmit={handleLogin}>
          <h2>登录后使用回收站</h2>
          <input
            type="text"
            placeholder="账号"
            value={loginForm.email}
            onChange={(event) => setLoginForm({ ...loginForm, email: event.target.value })}
            required
          />
          <input
            type="password"
            placeholder="密码"
            value={loginForm.password}
            onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
            required
          />
          <button type="submit">登录</button>
        </form>
      </section>
    );
  }

  if (!isAdmin) {
    return (
      <section className="card">
        <h2>回收站</h2>
        <p className="hint">仅管理员可访问回收站页面。</p>
      </section>
    );
  }

  const totalPages = Math.max(1, Math.ceil((total || 0) / pageSize));

  return (
    <section className="card">
      <div className="storage-toolbar-top">
        <h2>存储回收站</h2>
        <div className="action-buttons">
          <button type="button" className="ghost" onClick={handleReconcile}>立即对账</button>
          <button type="button" className="ghost" onClick={handlePurgeExpired}>清理过期</button>
          <button type="button" className="ghost" onClick={() => loadTrash(page)}>刷新</button>
        </div>
      </div>

      <div className="action-row" style={{ marginTop: 12 }}>
        <select value={scope} onChange={(event) => setScope(event.target.value)}>
          <option value="all">全部范围</option>
          <option value="resource">资源删除</option>
          <option value="storage">存储删除</option>
        </select>
        <input
          type="text"
          placeholder="按对象 key 搜索"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <div style={{ marginTop: 12 }}>
        <table className="storage-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>范围</th>
              <th>来源</th>
              <th>原始路径</th>
              <th>可恢复文件</th>
              <th>删除时间</th>
              <th>到期时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8}>加载中...</td></tr>
            ) : null}
            {!loading && items.length === 0 ? (
              <tr><td colSpan={8} className="hint">回收站为空</td></tr>
            ) : null}
            {!loading ? items.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.scope}</td>
                <td>{item.source}</td>
                <td title={item.original_key}>{item.original_key}</td>
                <td>{item.has_binary ? "是" : "否（仅记录）"}</td>
                <td>{new Date(item.deleted_at).toLocaleString("zh-CN")}</td>
                <td>{new Date(item.expires_at).toLocaleString("zh-CN")}</td>
                <td>
                  <div className="action-buttons">
                    <button type="button" onClick={() => handleRestore(item.id)}>恢复</button>
                    <button type="button" className="ghost danger-item" onClick={() => handlePurge(item.id)}>彻底删除</button>
                  </div>
                </td>
              </tr>
            )) : null}
          </tbody>
        </table>
      </div>

      <div className="action-row" style={{ marginTop: 12 }}>
        <button type="button" className="ghost" disabled={page <= 1} onClick={() => loadTrash(page - 1)}>上一页</button>
        <span className="hint">第 {page} / {totalPages} 页（共 {total} 条）</span>
        <button type="button" className="ghost" disabled={page >= totalPages} onClick={() => loadTrash(page + 1)}>下一页</button>
      </div>
    </section>
  );
}
