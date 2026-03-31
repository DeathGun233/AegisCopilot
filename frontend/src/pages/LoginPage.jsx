import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppContext } from "../context/AppContext";

const demoAccounts = [
  { username: "admin", password: "admin123", label: "管理员" },
  { username: "member", password: "member123", label: "成员" },
];

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { appError, login } = useAppContext();
  const [form, setForm] = useState({ username: "admin", password: "admin123" });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const nextPath = location.state?.from || "/chat";

  async function handleSubmit(event) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      await login(form.username, form.password);
      navigate(nextPath, { replace: true });
    } catch (loginError) {
      setError(loginError.message || "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-card">
        <div className="auth-hero">
          <span className="hero-pill">AegisCopilot</span>
          <h1>登录工作台</h1>
          <p>这一版已经从前端切换身份的演示模式，升级为真实登录态和后台权限控制。</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>用户名</span>
            <input
              value={form.username}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </label>

          <label>
            <span>密码</span>
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              placeholder="请输入密码"
              autoComplete="current-password"
            />
          </label>

          {error || appError ? <div className="auth-error">{error || appError}</div> : null}

          <button type="submit" className="primary-action auth-submit" disabled={submitting}>
            {submitting ? "登录中..." : "登录"}
          </button>
        </form>

        <div className="auth-demo-list">
          {demoAccounts.map((account) => (
            <button
              key={account.username}
              type="button"
              className="auth-demo-card"
              onClick={() => setForm({ username: account.username, password: account.password })}
            >
              <strong>{account.label}</strong>
              <span>{account.username}</span>
              <small>{account.password}</small>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
