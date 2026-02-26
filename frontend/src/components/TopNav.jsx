import { NavLink } from "react-router-dom";

export default function TopNav({
  token,
  email,
  role,
  onLogout,
  searchInput,
  onSearchInputChange,
  onSearch,
  onSearchClear,
  showSearch = false
}) {
  return (
    <header className="top-nav-wrap">
      <div className="top-nav-main">
        <div className="brand">
          Edu Resource <span className="brand-badge">AI版</span>
        </div>
        <nav className="top-nav-links">
          <NavLink to="/discover" className={({ isActive }) => (isActive ? "active" : "")}>发现</NavLink>
          <NavLink to="/upload" className={({ isActive }) => (isActive ? "active" : "")}>上传</NavLink>
          <NavLink to="/mineru" className={({ isActive }) => (isActive ? "active" : "")}>MinerU</NavLink>
          <NavLink to="/rag" className={({ isActive }) => (isActive ? "active" : "")}>GraphRAG</NavLink>
          <NavLink to="/storage" className={({ isActive }) => (isActive ? "active" : "")}>存储</NavLink>
          {role === "admin" ? (
            <NavLink to="/storage/trash" className={({ isActive }) => (isActive ? "active" : "")}>回收站</NavLink>
          ) : null}
          <NavLink to="/admin" className={({ isActive }) => (isActive ? "active" : "")}>管理</NavLink>
        </nav>
        <div className="user-box">
          {token ? (
            <>
              <span>{email}（{role}）</span>
              <button type="button" onClick={onLogout}>退出</button>
            </>
          ) : (
            <span>游客浏览</span>
          )}
        </div>
      </div>
      {showSearch && (
        <div className="discover-search-bar">
          <input
            type="text"
            placeholder="搜索标题/描述"
            value={searchInput}
            onChange={(e) => onSearchInputChange(e.target.value)}
          />
          <button type="button" onClick={onSearch}>搜索</button>
          <button type="button" className="ghost" onClick={onSearchClear}>清空</button>
        </div>
      )}
    </header>
  );
}
