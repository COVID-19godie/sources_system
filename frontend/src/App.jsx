import { Suspense, lazy, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import TopNav from "./components/TopNav";
import DiscoverPage from "./pages/DiscoverPage";
import UploadPage from "./pages/UploadPage";
import AdminPage from "./pages/AdminPage";
import MineruPage from "./pages/MineruPage";
import StoragePage from "./pages/StoragePage";
import StorageTrashPage from "./pages/StorageTrashPage";
import BrowserViewerPage from "./pages/BrowserViewerPage";
import { apiRequest } from "./lib/api";

const RagWorkspacePage = lazy(() => import("./pages/RagWorkspacePage"));

function AppShell() {
  const location = useLocation();
  const [token, setToken] = useState(localStorage.getItem("token") || "");
  const [role, setRole] = useState(localStorage.getItem("role") || "");
  const [email, setEmail] = useState(localStorage.getItem("email") || "");
  const [message, setMessage] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");

  useEffect(() => {
    function handleAuthExpired() {
      setToken("");
      setRole("");
      setEmail("");
      setMessage("登录状态已失效，请重新登录");
    }

    window.addEventListener("auth-expired", handleAuthExpired);
    return () => window.removeEventListener("auth-expired", handleAuthExpired);
  }, []);

  async function onLogin(form) {
    const data = await apiRequest("/api/auth/login", {
      method: "POST",
      body: form
    });
    localStorage.setItem("token", data.access_token);
    localStorage.setItem("role", data.role);
    localStorage.setItem("email", data.email);
    setToken(data.access_token);
    setRole(data.role);
    setEmail(data.email);
  }

  async function onRegister(form) {
    await apiRequest("/api/auth/register", {
      method: "POST",
      body: form
    });
  }

  function onLogout() {
    localStorage.removeItem("token");
    localStorage.removeItem("role");
    localStorage.removeItem("email");
    setToken("");
    setRole("");
    setEmail("");
    setMessage("已退出登录");
  }

  const showSearch = location.pathname === "/discover";

  return (
    <div className="page">
      <TopNav
        token={token}
        email={email}
        role={role}
        onLogout={onLogout}
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        onSearch={() => setSearchKeyword(searchInput)}
        onSearchClear={() => {
          setSearchInput("");
          setSearchKeyword("");
        }}
        showSearch={showSearch}
      />

      {message && <div className="message">{message}</div>}

      <Routes>
        <Route path="/" element={<Navigate to="/discover" replace />} />
        <Route
          path="/discover"
          element={
            <DiscoverPage
              token={token}
              role={role}
              searchKeyword={searchKeyword}
              onLogin={onLogin}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/upload"
          element={
            <UploadPage
              token={token}
              onLogin={onLogin}
              onRegister={onRegister}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/admin"
          element={
            <AdminPage
              token={token}
              role={role}
              onLogin={onLogin}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/mineru"
          element={
            <MineruPage
              token={token}
              onLogin={onLogin}
              onRegister={onRegister}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/rag"
          element={
            <Suspense
              fallback={(
                <section className="card">
                  <h2>GraphRAG 工作台</h2>
                  <p className="hint">页面加载中...</p>
                </section>
              )}
            >
              <RagWorkspacePage
                token={token}
                role={role}
                onLogin={onLogin}
                setGlobalMessage={setMessage}
              />
            </Suspense>
          }
        />
        <Route
          path="/storage"
          element={
            <StoragePage
              token={token}
              role={role}
              onLogin={onLogin}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/storage/trash"
          element={
            <StorageTrashPage
              token={token}
              role={role}
              onLogin={onLogin}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/viewer/resource/:resourceId"
          element={
            <BrowserViewerPage
              token={token}
              setGlobalMessage={setMessage}
            />
          }
        />
        <Route
          path="/viewer/storage"
          element={
            <BrowserViewerPage
              token={token}
              setGlobalMessage={setMessage}
            />
          }
        />
      </Routes>
    </div>
  );
}

export default function App() {
  return <AppShell />;
}
