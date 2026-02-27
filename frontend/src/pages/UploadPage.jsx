import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import UploadWizard from "../components/UploadWizard";
import { apiRequest, fetchUploadOptions, uploadWithProgress } from "../lib/api";
import { withGeneralChapterOption } from "../lib/chapterOptions";

export default function UploadPage({ token, onLogin, onRegister, setGlobalMessage }) {
  const [loginForm, setLoginForm] = useState({ email: "", password: "" });
  const [registerForm, setRegisterForm] = useState({ email: "", password: "" });
  const [volumes, setVolumes] = useState([]);
  const [chapters, setChapters] = useState([]);
  const [sections, setSections] = useState([]);
  const [tags, setTags] = useState([]);
  const [difficulties, setDifficulties] = useState(["基础", "进阶", "挑战"]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [aiCapability, setAiCapability] = useState({
    loaded: false,
    enabled: false,
    auto_enrich: false
  });
  const [aiTagRuntime, setAiTagRuntime] = useState("idle");

  useEffect(() => {
    if (!token) {
      setVolumes([]);
      setChapters([]);
      setSections([]);
      setTags([]);
      setAiCapability({ loaded: false, enabled: false, auto_enrich: false });
      setAiTagRuntime("idle");
      return;
    }

    async function loadOptions() {
      try {
        const [data, aiStatus] = await Promise.all([
          fetchUploadOptions({
            token,
            stage: "senior",
            subject: "物理"
          }),
          apiRequest("/api/resources/ai-status", { token })
        ]);
        setVolumes(data?.volumes || []);
        setChapters(withGeneralChapterOption(data?.chapters || []));
        setSections(data?.sections || []);
        setTags(data?.tags || []);
        setDifficulties(data?.difficulties?.length ? data.difficulties : ["基础", "进阶", "挑战"]);
        const nextCapability = {
          loaded: true,
          enabled: Boolean(aiStatus?.enabled),
          auto_enrich: Boolean(aiStatus?.auto_enrich)
        };
        setAiCapability(nextCapability);
        if (!nextCapability.enabled || !nextCapability.auto_enrich) {
          setAiTagRuntime("unavailable");
        } else {
          setAiTagRuntime("idle");
        }
      } catch (error) {
        setGlobalMessage(error.message);
      }
    }

    loadOptions();
  }, [token, setGlobalMessage]);

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

  async function handleRegister(event) {
    event.preventDefault();
    try {
      await onRegister(registerForm);
      setRegisterForm({ email: "", password: "" });
      setGlobalMessage("注册成功，请登录");
    } catch (error) {
      setGlobalMessage(error.message);
    }
  }

  async function handleUpload(payload) {
    const formData = new FormData();
    formData.append("title", payload.title || "");
    formData.append("type", payload.type);
    formData.append("description", payload.description || "");
    formData.append("subject", payload.subject || "物理");
    formData.append("grade", payload.grade || "");
    formData.append("tags", payload.tags || "");
    formData.append("resource_kind", payload.resource_kind || "tutorial");
    formData.append("difficulty", payload.difficulty || "");
    formData.append("chapter_mode", payload.chapter_mode || "normal");
    if (payload.chapter_id) {
      formData.append("chapter_id", payload.chapter_id);
    }
    if (payload.section_id) {
      formData.append("section_id", payload.section_id);
    }
    if (payload.volume_code) {
      formData.append("volume_code", payload.volume_code);
    }
    if (payload.external_url) {
      formData.append("external_url", payload.external_url);
    }
    if (payload.file) {
      formData.append("file", payload.file);
    }

    try {
      setUploadProgress(0);
      setIsUploading(true);
      if (aiCapability.enabled && aiCapability.auto_enrich) {
        setAiTagRuntime("processing");
      }
      const created = await uploadWithProgress("/api/resources", {
        token,
        body: formData,
        onProgress: (progress) => setUploadProgress(progress)
      });
      if (created?.ai_tags?.length || created?.ai_summary) {
        setAiTagRuntime("done");
      } else if (aiCapability.enabled && aiCapability.auto_enrich) {
        setAiTagRuntime("processing");
      }
      setUploadProgress(100);
      setGlobalMessage("资源已提交，等待管理员审核");
      return true;
    } catch (error) {
      setGlobalMessage(error.message);
      return false;
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadProgress(0), 800);
    }
  }

  if (!token) {
    return (
      <section className="card two-cols">
        <form onSubmit={handleLogin}>
          <h2>登录后上传</h2>
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
          <p className="hint">管理员账号：admin / admin123</p>
        </form>

        <form onSubmit={handleRegister}>
          <h2>教师注册</h2>
          <input
            type="text"
            placeholder="账号"
            value={registerForm.email}
            onChange={(event) => setRegisterForm({ ...registerForm, email: event.target.value })}
            required
          />
          <input
            type="password"
            placeholder="密码（至少6位）"
            value={registerForm.password}
            onChange={(event) => setRegisterForm({ ...registerForm, password: event.target.value })}
            required
            minLength={6}
          />
          <button type="submit">注册</button>
        </form>
      </section>
    );
  }

  return (
    <>
      <section className="card">
        <h2>上传资源</h2>
        <p className="hint">
          当前场景固定为高中物理，上传归档采用“先选册，再选章”的选择题流程。MinerU 解析请前往{" "}
          <Link to="/mineru">MinerU 页面</Link>。
        </p>
      </section>
      <UploadWizard
        token={token}
        volumes={volumes}
        chapters={chapters}
        sections={sections}
        tags={tags}
        difficulties={difficulties}
        aiCapability={aiCapability}
        aiTagRuntime={aiTagRuntime}
        isUploading={isUploading}
        uploadProgress={uploadProgress}
        onSubmit={handleUpload}
        setGlobalMessage={setGlobalMessage}
      />
    </>
  );
}
