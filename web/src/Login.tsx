import { useState } from "react";
import { api, ApiError, type Me } from "./api";
import { ErrorAlert } from "./ui";

export function Login({ me, onSignedIn }: { me: Me | null; onSignedIn: (me: Me) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await api.login(username.trim(), password));
      window.location.hash = "#/setup";
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
      setPassword("");
    } finally {
      setBusy(false);
    }
  };

  if (me && !me.login_enabled) {
    return (
      <div className="login">
        <div className="page-head">
          <h1>Admin sign-in</h1>
        </div>
        <div className="alert alert-info">
          The admin login is not set up. Your IT team enables it with CXS_ADMIN_PASSWORD_HASH and CXS_SECRET_KEY
          (see backend/README.md).
        </div>
      </div>
    );
  }

  return (
    <div className="login">
      <div className="page-head">
        <h1>Admin sign-in</h1>
        <p>An admin can enter the connection settings and change the partners.</p>
      </div>
      <form className="card form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="login-user">Username</label>
          <input
            id="login-user"
            className="input"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="login-password">Password</label>
          <input
            id="login-password"
            className="input"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <ErrorAlert error={error} />
        <div className="actions">
          <button type="submit" className="btn btn-primary" disabled={busy || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
