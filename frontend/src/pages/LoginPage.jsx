import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppContext } from "../context/AppContext";

const showDemoAccounts =
  typeof window !== "undefined" && ["localhost", "127.0.0.1"].includes(window.location.hostname);

const demoAccounts = [
  { username: "admin", password: "admin123", label: "???" },
  { username: "member", password: "member123", label: "??" },
];

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { appError, login } = useAppContext();
  const [form, setForm] = useState({ username: "admin", password: "" });
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
      setError(loginError.message || "????");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-card">
        <div className="auth-hero">
          <span className="hero-pill">AegisCopilot</span>
          <h1>?????</h1>
          <p>?????????????????????????????????????????</p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>???</span>
            <input
              value={form.username}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
              placeholder="??????"
              autoComplete="username"
            />
          </label>

          <label>
            <span>??</span>
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              placeholder="?????"
              autoComplete="current-password"
            />
          </label>

          {error || appError ? <div className="auth-error">{error || appError}</div> : null}

          <button type="submit" className="primary-action auth-submit" disabled={submitting}>
            {submitting ? "???..." : "??"}
          </button>
        </form>

        {showDemoAccounts ? (
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
        ) : null}
      </section>
    </div>
  );
}
