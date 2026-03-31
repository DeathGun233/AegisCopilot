import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAppContext } from "../context/AppContext";

const demoAccounts = [
  { username: "admin", password: "admin123", label: "Admin" },
  { username: "member", password: "member123", label: "Member" },
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
      setError(loginError.message || "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <section className="auth-card">
        <div className="auth-hero">
          <span className="hero-pill">AegisCopilot</span>
          <h1>Sign in to the workspace</h1>
          <p>
            This first migration version replaces the old role switcher with a real session flow and
            admin-only console access.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>Username</span>
            <input
              value={form.username}
              onChange={(event) => setForm((current) => ({ ...current, username: event.target.value }))}
              placeholder="admin"
              autoComplete="username"
            />
          </label>

          <label>
            <span>Password</span>
            <input
              type="password"
              value={form.password}
              onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
              placeholder="Enter password"
              autoComplete="current-password"
            />
          </label>

          {error || appError ? <div className="auth-error">{error || appError}</div> : null}

          <button type="submit" className="primary-action auth-submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign in"}
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
